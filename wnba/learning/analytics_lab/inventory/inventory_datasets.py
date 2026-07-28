"""Dataset inventory + schema reporter for the WNBA Analytics Lab.

Read-only. Profiles every WNBA dataset the lab may consume and writes three
artifacts under ``analytics_lab/data/normalized/``:

  dataset_inventory.csv   one row per dataset (rows, date range, dupes, grain)
  dataset_schema.csv      one row per dataset column (dtype, null rate, sample)
  dataset_inventory.json  the same inventory as structured JSON

Usage::

    python3 -m learning.analytics_lab.inventory.inventory_datasets     # from sports/wnba
    python3 inventory/inventory_datasets.py                            # from the lab dir
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):  # direct-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from analytics_lab.config import lab_config as C
else:
    from ..config import lab_config as C


@dataclass
class DatasetSpec:
    """Declares how to profile one dataset."""

    name: str
    path: Path
    grain: str                       # player-game | team-game | slate | projection | snapshot
    temporality: str                 # pregame | postgame | mixed | reference
    date_columns: list[str] = field(default_factory=list)
    key_columns: list[str] = field(default_factory=list)
    notes: str = ""


SPECS: list[DatasetSpec] = [
    DatasetSpec(
        "prod_player_games", C.PROD_PLAYER_GAMES, "player-game", "postgame",
        ["game_date"], ["player_key", "game_id"],
        "Canonical actuals. game_date is the UTC date, not the ET slate date.",
    ),
    DatasetSpec(
        "prod_team_context", C.PROD_TEAM_CONTEXT, "team-game", "postgame",
        ["game_date"], ["team", "game_date"],
        "Pace / off+def rating source for the production feature builder.",
    ),
    DatasetSpec(
        "prod_player_status", C.PROD_PLAYER_STATUS, "snapshot", "pregame",
        ["fetched_at"], ["player_key"],
        "CURRENT injury snapshot only; overwritten each run. No history retained.",
    ),
    DatasetSpec(
        "prod_player_positions", C.PROD_PLAYER_POSITIONS, "snapshot", "reference",
        [], ["player_key"],
        "Manually maintained current positions; anachronistic if applied to past dates.",
    ),
    DatasetSpec(
        "prod_sportsbook_lines", C.PROD_SPORTSBOOK_LINES, "snapshot", "pregame",
        ["fetched_at"], ["player_key", "stat"],
        "Current slate lines only; overwritten each run.",
    ),
    DatasetSpec(
        "prod_training_dataset", C.PROD_TRAINING_DATASET, "player-game", "mixed",
        ["game_date"], ["player_key", "game_date"],
        "Rebuilt daily from prod_player_games. Rolling cols are shift(1); "
        "`minutes`/targets are same-game actuals.",
    ),
    DatasetSpec(
        "prod_today_features", C.PROD_TODAY_FEATURES, "slate", "pregame",
        ["game_date", "last_game_date"], ["player_key"],
        "Today's serving frame. Carries the player's LAST completed game row.",
    ),
    DatasetSpec(
        "prod_graded_ledger", C.PROD_GRADED_LEDGER, "projection", "mixed",
        ["date", "created_at_utc"], ["prediction_id"],
        "Frozen best-bet picks with actuals. Lined markets only, not full slate.",
    ),
    DatasetSpec(
        "v2_player_boxscores", C.V2_PLAYER_BOXSCORES, "player-game", "postgame",
        ["game_date"], ["player_key", "game_id"],
        "Adds starter / played / position / DNP vs the production canonical file.",
    ),
    DatasetSpec(
        "v2_team_game_logs", C.V2_TEAM_GAME_LOGS, "team-game", "postgame",
        ["date"], ["team", "game_id"],
        "Real possessions, pace_proxy, off/def/net rating. Fresher than prod_team_context.",
    ),
    DatasetSpec(
        "v2_prop_open_close", C.V2_PROP_OPEN_CLOSE, "projection", "pregame",
        ["open_at", "close_at"], ["player_name", "stat", "date"],
        "Per-prop opening and closing lines. `date` column is a malformed integer date.",
    ),
    DatasetSpec(
        "v2_game_open_close", C.V2_GAME_OPEN_CLOSE, "team-game", "pregame",
        ["game_date"], ["game_date", "home", "away"],
        "Game spread/total open and close.",
    ),
]


def _profile_dates(frame: pd.DataFrame, columns: list[str]) -> dict:
    out: dict = {}
    for column in columns:
        if column not in frame.columns:
            out[column] = {"present": False}
            continue
        parsed = pd.to_datetime(frame[column], errors="coerce", utc=False)
        # An all-NaT parse of a non-empty column means the stored format is broken.
        out[column] = {
            "present": True,
            "unparseable_rate": round(float(parsed.isna().mean()), 4),
            "min": None if parsed.notna().sum() == 0 else str(parsed.min()),
            "max": None if parsed.notna().sum() == 0 else str(parsed.max()),
            "distinct_days": int(parsed.dt.normalize().nunique()),
        }
    return out


def _missing_day_rate(frame: pd.DataFrame, column: str) -> float | None:
    """Share of calendar days inside the observed span with zero rows.

    Reported for context only: the WNBA does not play daily, so a nonzero rate
    is expected. It is a red flag only when compared against the schedule.
    """
    if column not in frame.columns:
        return None
    parsed = pd.to_datetime(frame[column], errors="coerce").dt.normalize().dropna()
    if parsed.empty:
        return None
    span = pd.date_range(parsed.min(), parsed.max(), freq="D")
    if len(span) == 0:
        return None
    return round(1.0 - parsed.nunique() / len(span), 4)


def profile_dataset(spec: DatasetSpec) -> tuple[dict, list[dict]]:
    record: dict = {
        "name": spec.name,
        "path": str(spec.path),
        "exists": spec.path.exists(),
        "grain": spec.grain,
        "temporality": spec.temporality,
        "notes": spec.notes,
    }
    if not spec.path.exists():
        return record, []

    record["file_type"] = spec.path.suffix.lstrip(".")
    record["size_bytes"] = spec.path.stat().st_size
    frame = pd.read_csv(spec.path, low_memory=False)
    record["rows"] = int(len(frame))
    record["columns"] = int(len(frame.columns))
    record["date_profile"] = _profile_dates(frame, spec.date_columns)

    primary_date = next((c for c in spec.date_columns if c in frame.columns), None)
    record["primary_date_column"] = primary_date
    record["missing_day_rate"] = _missing_day_rate(frame, primary_date) if primary_date else None

    present_keys = [c for c in spec.key_columns if c in frame.columns]
    record["key_columns"] = present_keys
    if present_keys:
        subset = frame.dropna(subset=present_keys)
        record["key_rows_non_null"] = int(len(subset))
        record["duplicate_key_rows"] = int(subset.duplicated(present_keys).sum())
        record["duplicate_key_rate"] = (
            round(float(subset.duplicated(present_keys).mean()), 5) if len(subset) else None
        )
    record["exact_duplicate_rows"] = int(frame.duplicated().sum())

    if "season" in frame.columns:
        record["seasons"] = sorted(
            str(int(s)) for s in pd.to_numeric(frame["season"], errors="coerce").dropna().unique()
        )
    if "player_key" in frame.columns:
        record["distinct_players"] = int(frame["player_key"].nunique())
    if "game_id" in frame.columns:
        record["distinct_games"] = int(frame["game_id"].nunique())
        record["game_id_null_rate"] = round(float(frame["game_id"].isna().mean()), 4)

    schema_rows = []
    for column in frame.columns:
        series = frame[column]
        non_null = series.dropna()
        schema_rows.append({
            "dataset": spec.name,
            "column": column,
            "dtype": str(series.dtype),
            "null_rate": round(float(series.isna().mean()), 4),
            "distinct": int(series.nunique(dropna=True)),
            "sample": "" if non_null.empty else str(non_null.iloc[0])[:60],
        })
    return record, schema_rows


def _archive_summary() -> dict:
    """Profile the dated projection archive, which is a directory not a file."""
    files = sorted(C.PROD_PROJECTION_ARCHIVE_DIR.glob("wnba_projections_*.csv"))
    summary = {
        "name": "prod_projection_archive",
        "path": str(C.PROD_PROJECTION_ARCHIVE_DIR),
        "exists": bool(files),
        "grain": "projection",
        "temporality": "pregame",
        "files": len(files),
        "notes": (
            "One frozen full-slate board per run date, written by the 22:30 UTC "
            "(18:30 ET) pipeline run. The exact-snapshot production baseline."
        ),
    }
    if not files:
        return summary
    rows = 0
    dates: list[str] = []
    schemas: set[int] = set()
    for path in files:
        frame = pd.read_csv(path, low_memory=False)
        rows += len(frame)
        schemas.add(len(frame.columns))
        if "GAME_DATE" in frame.columns:
            parsed = pd.to_datetime(frame["GAME_DATE"], errors="coerce").dropna()
            if not parsed.empty:
                dates.append(str(parsed.min().date()))
    summary["rows"] = rows
    summary["distinct_column_counts"] = sorted(schemas)
    summary["slate_date_min"] = min(dates) if dates else None
    summary["slate_date_max"] = max(dates) if dates else None
    summary["slates"] = len(set(dates))
    return summary


def main() -> int:
    records: list[dict] = []
    schema_rows: list[dict] = []
    for spec in SPECS:
        record, schema = profile_dataset(spec)
        records.append(record)
        schema_rows.extend(schema)
    records.append(_archive_summary())

    inventory = pd.json_normalize(records, sep=".")
    C.write_csv(inventory, "normalized", "dataset_inventory.csv")
    C.write_csv(pd.DataFrame(schema_rows), "normalized", "dataset_schema.csv")
    target = C.lab_path("normalized", "dataset_inventory.json")
    target.write_text(json.dumps(records, indent=2, default=str) + "\n")

    print(f"{'dataset':<26} {'rows':>8} {'cols':>5}  {'dupkeys':>8}  date range")
    print("-" * 92)
    for record in records:
        if not record.get("exists"):
            print(f"{record['name']:<26} {'MISSING':>8}")
            continue
        primary = record.get("primary_date_column")
        profile = (record.get("date_profile") or {}).get(primary, {}) if primary else {}
        span = ""
        if profile.get("min"):
            span = f"{profile['min'][:10]} -> {profile['max'][:10]}"
        elif record.get("slate_date_min"):
            span = f"{record['slate_date_min']} -> {record['slate_date_max']}"
        print(
            f"{record['name']:<26} {record.get('rows', record.get('files', 0)):>8} "
            f"{record.get('columns', 0):>5}  {str(record.get('duplicate_key_rows', '-')):>8}  {span}"
        )
    print(f"\nWrote inventory to {C.LAB_NORMALIZED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
