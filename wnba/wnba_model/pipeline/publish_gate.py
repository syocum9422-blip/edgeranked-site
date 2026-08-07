"""The single authoritative WNBA slate-validation / publish gate.

Every path that can put WNBA artifacts in front of a customer — the full production run,
the scheduled refreshes, the late pregame board refresh, and any manual publish wrapper —
must clear this gate. There is exactly one implementation of the policy; callers either
import ``require_validated_slate`` or shell out to this module's CLI.

    python -m wnba_model.pipeline.publish_gate --context late_refresh [--dry-run]

Exit codes: 0 = publication allowed (PASS or DEGRADED_PASS), 3 = blocked, 4 = no slate.

The gate owns:
  * canonical slate-date selection
  * canonical-source provenance lookup (so the validator stays independent of it)
  * independent corroboration gathering
  * the validation manifest and the internal gate-status artifact

It owns no projection, model, scoring, simulation or calibration behaviour.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from wnba_model.pipeline.slate_sources import (
    STATUS_DEGRADED_PASS,
    STATUS_FAIL,
    corroborate_subset,
    fetch_thesportsdb_slate,
    normalize_team_code,
    publication_allowed,
    run_slate_validation,
    summarize_corroboration,
)
from wnba_model.settings import (
    BASE_DIR,
    CANONICAL_SCHEDULE_TODAY_PATH,
    CANONICAL_SPORTSBOOK_LINES_PATH,
    TODAY_OVERRIDE,
)

PROCESSED_DIR = BASE_DIR / "data" / "processed"
SLATE_VALIDATION_MANIFEST_PATH = PROCESSED_DIR / "wnba_slate_validation_manifest.json"
CANONICAL_PROVENANCE_PATH = PROCESSED_DIR / "wnba_canonical_schedule_provenance.json"
GATE_STATUS_PATH = PROCESSED_DIR / "wnba_publish_gate_status.json"

MAX_UPCOMING_SLATE_DAYS = 3
EASTERN = "America/New_York"

FAILURE_CATEGORIES = {
    "validator_infrastructure_unavailable": "slate_validation_unavailable",
    "same_source_validation_without_independent_evidence": "slate_validation_unavailable",
}


class PublishBlocked(RuntimeError):
    """Raised when a publish path must not proceed. Carries public-safe categorisation."""

    def __init__(self, internal_message: str, *, category: str, manifest: dict | None = None):
        super().__init__(internal_message)
        self.category = category
        self.manifest = manifest or {}


def _json_default(value):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def today_et_date():
    if TODAY_OVERRIDE:
        return pd.Timestamp(TODAY_OVERRIDE).date()
    return pd.Timestamp.now(tz=EASTERN).date()


# --- canonical slate reading -------------------------------------------------
def normalize_schedule_rows(schedule: pd.DataFrame, slate_date: object) -> list[dict]:
    """Canonical schedule CSV -> the normalized row shape every source is compared in."""
    if schedule.empty:
        return []
    date_col = next((col for col in schedule.columns if str(col).lower() in {"game_date", "date"}), None)
    frame = schedule.copy()
    if date_col:
        parsed = pd.to_datetime(frame[date_col], errors="coerce")
        frame = frame[parsed.dt.date == pd.Timestamp(slate_date).date()].copy()
    rows = []
    for _, row in frame.iterrows():
        start_raw = row.get("start_time_utc", row.get("start_time", ""))
        start = pd.to_datetime(start_raw, utc=True, errors="coerce")
        rows.append(
            {
                "game_id": str(row.get("game_id", "")),
                "home_team": normalize_team_code(row.get("home_team", "")),
                "away_team": normalize_team_code(row.get("away_team", "")),
                "start_time_utc": "" if pd.isna(start) else start.strftime("%Y-%m-%dT%H:%MZ"),
            }
        )
    return sorted(rows, key=lambda item: (item["start_time_utc"], item["away_team"], item["home_team"]))


def canonical_source_label() -> str:
    """Which provider produced the canonical slate on disk (provenance file wins)."""
    provenance = read_json(CANONICAL_PROVENANCE_PATH)
    label = str(provenance.get("canonical_source") or "")
    if label:
        return label
    try:
        schedule = pd.read_csv(CANONICAL_SCHEDULE_TODAY_PATH)
    except Exception:
        return ""
    if schedule.empty or "_data_source" not in schedule.columns:
        return ""
    values = schedule["_data_source"].dropna().astype(str)
    return values.iloc[0] if not values.empty else ""


def canonical_provenance_is_stale() -> tuple[bool, str]:
    """True when acquisition explicitly marked the schedule on disk as not-current."""
    provenance = read_json(CANONICAL_PROVENANCE_PATH)
    if not provenance:
        return False, ""
    if provenance.get("stale_retained"):
        return True, str(provenance.get("failure_reason") or "canonical_schedule_marked_stale")
    slate_date = str(provenance.get("slate_date") or "")
    if slate_date and slate_date != str(today_et_date()) and not TODAY_OVERRIDE:
        return True, f"canonical_provenance_slate_date={slate_date}"
    return False, ""


def resolve_slate_status() -> tuple[object, str]:
    """Pick the slate date the pipeline/publish paths should act on. Single implementation."""
    if not CANONICAL_SCHEDULE_TODAY_PATH.exists():
        return None, f"Missing schedule file: {CANONICAL_SCHEDULE_TODAY_PATH}"

    try:
        schedule = pd.read_csv(CANONICAL_SCHEDULE_TODAY_PATH)
    except Exception as exc:
        return None, f"Could not read schedule file: {exc}"

    if schedule.empty:
        return None, "Schedule file is empty. Treating as no WNBA slate."

    date_col = next((col for col in schedule.columns if str(col).lower() in {"game_date", "date"}), None)
    if not date_col:
        return None, f"Schedule has no game_date/date column. Found: {list(schedule.columns)}"

    dates = pd.to_datetime(schedule[date_col], errors="coerce").dropna()
    if dates.empty:
        return None, "Schedule has no valid game dates."

    today = today_et_date()
    date_values = pd.to_datetime(schedule[date_col], errors="coerce")
    today_rows = schedule[date_values.dt.date == today]
    selected_date = today
    selected_rows = today_rows
    reason = "today"

    if today_rows.empty:
        max_date = (pd.Timestamp(today) + pd.Timedelta(days=MAX_UPCOMING_SLATE_DAYS)).date()
        upcoming_dates = sorted({value.date() for value in date_values.dropna() if today < value.date() <= max_date})
        if not upcoming_dates:
            latest = dates.max().date()
            return None, f"No WNBA games found for {today}. Latest schedule date is {latest}."
        selected_date = upcoming_dates[0]
        selected_rows = schedule[date_values.dt.date == selected_date]
        reason = "no_games_next_available"

    team_cols = [col for col in ["home_team", "away_team"] if col in schedule.columns]
    if team_cols:
        teams = set()
        for col in team_cols:
            teams.update(str(team).strip().upper() for team in selected_rows[col].dropna().tolist() if str(team).strip())
        if len(teams) < 2:
            return None, f"Selected WNBA slate has only {len(teams)} teams."

    return selected_date, (
        f"selected_slate_date={selected_date}\n"
        f"reason={reason}\n"
        f"WNBA slate rows: {len(selected_rows)}"
    )


# --- independent corroboration ----------------------------------------------
def sportsbook_coverage_record(generated: list) -> dict:
    """Does the (independent) sportsbook feed post props for every team on the slate?

    Weak evidence by design — the feed lists future slates too, so it can confirm that the
    slate's teams are live but can never define the slate.
    """
    record = {
        "name": "sportsbook_lines",
        "status": "UNAVAILABLE",
        "verdict": "UNAVAILABLE",
        "confirmed_games": 0,
        "contradictions": [],
        "detail": "",
    }
    try:
        lines = pd.read_csv(CANONICAL_SPORTSBOOK_LINES_PATH)
    except Exception as exc:
        record["detail"] = f"{type(exc).__name__}: {exc}"
        return record
    if lines.empty or "team" not in lines.columns:
        record["status"] = "OK"
        record["verdict"] = "INCONCLUSIVE"
        record["detail"] = "no lined teams available"
        return record
    source = lines.get("_data_source", pd.Series("", index=lines.index)).fillna("").astype(str).str.lower()
    live = lines[source.str.startswith("api:")]
    if live.empty:
        record["status"] = "OK"
        record["verdict"] = "INCONCLUSIVE"
        record["detail"] = "no live sportsbook rows"
        return record
    lined_teams = {normalize_team_code(value) for value in live["team"].dropna().astype(str)}
    slate_teams = {row["home_team"] for row in generated} | {row["away_team"] for row in generated}
    record["status"] = "OK"
    if not slate_teams:
        record["verdict"] = "INCONCLUSIVE"
        return record
    missing = sorted(slate_teams - lined_teams)
    record["confirmed_games"] = len(slate_teams & lined_teams)
    record["detail"] = f"slate_teams_without_lines={missing}" if missing else "all slate teams have live lines"
    record["verdict"] = "INCONCLUSIVE" if missing else "CONFIRMED"
    return record


def gather_corroboration(slate_date: object, generated: list) -> dict:
    records = [corroborate_subset(generated, fetch_thesportsdb_slate(slate_date))]
    records.append(sportsbook_coverage_record(generated))
    return summarize_corroboration(records)


# --- the gate ----------------------------------------------------------------
def validate_canonical_slate(
    slate_date: object,
    *,
    context: str = "pipeline",
    write_manifest: bool = True,
    collect_corroboration: bool = True,
) -> dict:
    """Run the authoritative validation policy for ``slate_date`` and record the result."""
    generated = normalize_schedule_rows(pd.read_csv(CANONICAL_SCHEDULE_TODAY_PATH), slate_date)
    canonical_source = canonical_source_label()
    corroboration = gather_corroboration(slate_date, generated) if collect_corroboration else None

    payload = run_slate_validation(
        slate_date,
        generated,
        canonical_source=canonical_source or "unknown",
        corroboration=corroboration,
    )
    payload["context"] = context

    stale, stale_reason = canonical_provenance_is_stale()
    if stale:
        payload["status"] = STATUS_FAIL
        payload["failure_reason"] = "canonical_schedule_is_stale"
        payload["stale_canonical_detail"] = stale_reason
        payload["public_label"] = "Not verified"

    if write_manifest:
        write_json(SLATE_VALIDATION_MANIFEST_PATH, payload)
        write_json(
            GATE_STATUS_PATH,
            {
                "checked_at": payload["generated_at"],
                "context": context,
                "slate_date": payload["slate_date"],
                "status": payload["status"],
                "publish_allowed": publication_allowed(payload),
                "validator_source": payload.get("validator_source"),
                "validation_independence": payload.get("validation_independence"),
                "canonical_source": payload.get("canonical_source"),
                "primary_source_status": payload.get("primary_source_status"),
                "secondary_source_status": payload.get("secondary_source_status"),
                "failure_reason": payload.get("failure_reason"),
                "internal_detail": payload.get("internal_detail"),
                "corroboration": payload.get("corroboration"),
            },
        )
    return payload


def failure_category(payload: dict) -> str:
    return FAILURE_CATEGORIES.get(str(payload.get("failure_reason") or ""), "slate_mismatch")


def require_validated_slate(slate_date: object, *, context: str = "pipeline", write_manifest: bool = True) -> dict:
    payload = validate_canonical_slate(slate_date, context=context, write_manifest=write_manifest)
    if not publication_allowed(payload):
        raise PublishBlocked(
            "WNBA slate validation failed: "
            f"context={context} status={payload.get('status')} failure_reason={payload.get('failure_reason')} "
            f"canonical_source={payload.get('canonical_source')} validator={payload.get('validator_source')} "
            f"independence={payload.get('validation_independence')} "
            f"primary={payload.get('primary_source_status')} secondary={payload.get('secondary_source_status')} "
            f"mismatch_reasons={payload.get('mismatch_reasons')} missing={payload.get('missing_games')} "
            f"unexpected={payload.get('unexpected_games')} duplicates={payload.get('duplicate_games')} "
            f"detail={payload.get('internal_detail')}",
            category=failure_category(payload),
            manifest=payload,
        )
    return payload


def describe(payload: dict) -> str:
    return (
        f"status={payload.get('status')}\n"
        f"canonical_source={payload.get('canonical_source')}\n"
        f"validator_source={payload.get('validator_source')}\n"
        f"validation_independence={payload.get('validation_independence')}\n"
        f"primary_source_status={payload.get('primary_source_status')}\n"
        f"secondary_source_status={payload.get('secondary_source_status')}\n"
        f"generated_game_count={payload.get('generated_game_count')} expected_game_count={payload.get('expected_game_count')}\n"
        f"corroboration={[(item.get('name'), item.get('verdict'), item.get('confirmed_games')) for item in (payload.get('corroboration') or {}).get('sources', [])]}\n"
        f"time_discrepancies={len(payload.get('time_discrepancies') or [])} "
        f"material_time_differences={len(payload.get('material_time_differences') or [])}"
    )


def recent_manifest(max_age_minutes: float) -> dict:
    """A manifest young enough to reuse instead of re-hitting the network."""
    if max_age_minutes <= 0:
        return {}
    manifest = read_json(SLATE_VALIDATION_MANIFEST_PATH)
    checked = pd.to_datetime(manifest.get("generated_at"), errors="coerce")
    if manifest and not pd.isna(checked):
        age = (pd.Timestamp.now(tz=EASTERN) - checked).total_seconds() / 60.0
        if 0 <= age <= max_age_minutes:
            manifest["_reused_manifest_age_minutes"] = round(age, 2)
            return manifest
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="WNBA publish gate — authoritative slate validation")
    parser.add_argument("--context", default="manual", help="which publish path is asking (pipeline/late_refresh/...)")
    parser.add_argument("--dry-run", action="store_true", help="do not write manifest/gate artifacts")
    parser.add_argument("--max-age-minutes", type=float, default=0.0, help="reuse a manifest younger than this instead of refetching")
    parser.add_argument("--slate-date", default="", help="override the slate date (diagnostics)")
    args = parser.parse_args()

    if args.slate_date:
        slate_date = pd.Timestamp(args.slate_date).date()
        message = f"selected_slate_date={slate_date} (override)"
    else:
        slate_date, message = resolve_slate_status()
    print(f"===== WNBA Publish Gate ({args.context}) =====\n{message}")
    if not slate_date:
        print("WNBA_SLATE_GATE=NO_SLATE")
        return 4

    payload = recent_manifest(args.max_age_minutes)
    if payload and str(payload.get("slate_date")) == str(slate_date):
        print(f"Reusing validation manifest from {payload['_reused_manifest_age_minutes']} minutes ago.")
    else:
        payload = validate_canonical_slate(slate_date, context=args.context, write_manifest=not args.dry_run)

    print(describe(payload))
    allowed = publication_allowed(payload)
    print(f"WNBA_SLATE_GATE={payload.get('status')}")
    if not allowed:
        print(f"WNBA_SLATE_GATE_BLOCKED_REASON={payload.get('failure_reason')}")
        return 3
    if payload.get("status") == STATUS_DEGRADED_PASS:
        print("WNBA slate gate: DEGRADED_PASS — publication allowed on reduced-strength evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
