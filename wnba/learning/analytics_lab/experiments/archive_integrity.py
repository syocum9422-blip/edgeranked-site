"""Phase 2F — which archived 2026 boards are genuinely pregame.

The dated projection archive is the only candidate for an *exact historical
production snapshot* baseline. It is only usable where the artifact was written
before every game it projects. This module builds a per-artifact ledger and
classifies each one.

Creation time. The boards carry no internal generation timestamp — the only
columns are projection values and `SIM_RUNS`. File mtime is therefore the
creation proxy. `simulate_wnba_today.py` rewrites the dated file on every
pipeline run, so mtime is the *last* run of that day, which is the correct
freeze instant for the archived content. The caveat is recorded on every row:
mtime is filesystem metadata and would be destroyed by a copy or restore.

Classifications:

    CLEAN_PREGAME      written before the earliest tip on its slate
    PARTIAL_POST_TIP   written after ≥1 game tipped, before the last one ended
    POSTGAME_REBUILD   written after every represented game had ended
    TIMESTAMP_UNKNOWN  no usable creation time
    SLATE_MISMATCH     board teams do not match the games found for that date
    INVALID            unreadable, empty, or no matching games

Output: ``data/baselines/archive_ledger.csv`` and ``reports/archive_integrity_report.md``.
"""
from __future__ import annotations

import sys
from datetime import timezone
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from analytics_lab.config import lab_config as C
else:
    from ..config import lab_config as C

GAME_DURATION_HOURS = 2.25

CLEAN, PARTIAL, POSTGAME = "CLEAN_PREGAME", "PARTIAL_POST_TIP", "POSTGAME_REBUILD"
UNKNOWN_TS, MISMATCH, INVALID = "TIMESTAMP_UNKNOWN", "SLATE_MISMATCH", "INVALID"

# The published board and the ESPN cache use different team abbreviations.
TEAM_ALIASES = {"LAS": "LA", "NYL": "NY", "GSV": "GS", "LVA": "LV", "WAS": "WSH"}


def load_games() -> pd.DataFrame:
    frame = pd.read_parquet(C.LAB_NORMALIZED / "team_games.parquet")
    frame["start_ts"] = pd.to_datetime(frame["start_utc"], utc=True)
    frame["end_ts"] = frame["start_ts"] + pd.Timedelta(hours=GAME_DURATION_HOURS)
    frame["utc_date"] = frame["start_ts"].dt.date.astype("string")
    return frame


def classify_artifact(path: Path, games: pd.DataFrame) -> dict:
    """One ledger row for one archived board."""
    stamp = path.stem.split("_")[-1]
    record: dict = {
        "artifact_path": str(path),
        "artifact_name": path.name,
        "filename_date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}" if len(stamp) == 8 else None,
        "file_mtime_utc": pd.Timestamp(path.stat().st_mtime, unit="s", tz=timezone.utc).isoformat(),
        "internal_generation_timestamp": None,   # boards carry none
        "creation_time_source": "file_mtime",
        "size_bytes": path.stat().st_size,
    }
    try:
        board = pd.read_csv(path, low_memory=False)
    except Exception as exc:
        return {**record, "classification": INVALID, "reason": f"unreadable: {type(exc).__name__}"}
    record["rows"] = len(board)
    record["columns"] = len(board.columns)
    if board.empty or "GAME_DATE" not in board.columns:
        return {**record, "classification": INVALID, "reason": "empty or missing GAME_DATE"}

    board_dates = pd.to_datetime(board["GAME_DATE"], errors="coerce").dt.date.astype("string")
    record["board_game_dates"] = ";".join(sorted(board_dates.dropna().unique()))
    record["board_players"] = int(board["PLAYER_KEY"].nunique()) if "PLAYER_KEY" in board else None
    teams = set(board["TEAM_ABBREVIATION"].dropna().astype(str)) if "TEAM_ABBREVIATION" in board else set()
    record["board_teams"] = len(teams)
    record["model_metadata"] = (
        f"SIM_RUNS={int(board['SIM_RUNS'].dropna().iloc[0])}"
        if "SIM_RUNS" in board and board["SIM_RUNS"].notna().any() else None
    )

    # The board's GAME_DATE is the **ET slate date**, not the UTC date used by
    # `wnba_player_games.game_date`. Production runs both conventions at once.
    # Verified: joining on slate_date_et matches every board team; joining on the
    # UTC date finds zero games for a board whose slate is entirely in the evening.
    slate = games[games["slate_date_et"].isin(set(board_dates.dropna()))]
    if slate.empty:
        return {**record, "classification": INVALID, "reason": "no games found for the board's date"}

    record["games_represented"] = int(slate["game_id"].nunique())
    record["slate_dates_et"] = ";".join(sorted(slate["slate_date_et"].unique()))
    earliest, latest = slate["start_ts"].min(), slate["start_ts"].max()
    last_end = slate["end_ts"].max()
    record["earliest_tip_utc"] = earliest.isoformat()
    record["latest_tip_utc"] = latest.isoformat()
    record["last_game_end_utc"] = last_end.isoformat()

    slate_teams = set(slate["team_abbrev"].dropna().astype(str))
    normalized_board = {TEAM_ALIASES.get(t, t) for t in teams}
    normalized_slate = {TEAM_ALIASES.get(t, t) for t in slate_teams}
    unmatched = normalized_board - normalized_slate
    record["board_teams_not_playing"] = ";".join(sorted(unmatched)) if unmatched else None

    created = pd.Timestamp(record["file_mtime_utc"])
    if pd.isna(created):
        return {**record, "classification": UNKNOWN_TS, "reason": "no usable creation time"}

    tipped_before_creation = int((slate.drop_duplicates("game_id")["start_ts"] < created).sum())
    ended_before_creation = int((slate.drop_duplicates("game_id")["end_ts"] < created).sum())
    record["games_tipped_before_creation"] = tipped_before_creation
    record["games_completed_before_creation"] = ended_before_creation
    record["created_before_every_tip"] = bool(created <= earliest)

    if unmatched and len(unmatched) > len(normalized_board) / 2:
        classification, reason = MISMATCH, f"{len(unmatched)} board teams not on this slate"
    elif tipped_before_creation == 0:
        classification, reason = CLEAN, "written before the earliest tip"
    elif ended_before_creation >= record["games_represented"]:
        classification, reason = POSTGAME, "written after every represented game ended"
    else:
        classification = PARTIAL
        reason = f"{tipped_before_creation}/{record['games_represented']} games had tipped"
    return {**record, "classification": classification, "reason": reason}


def build_ledger() -> pd.DataFrame:
    games = load_games()
    paths = sorted(C.PROD_PROJECTION_ARCHIVE_DIR.glob("wnba_projections_*.csv"))
    ledger = pd.DataFrame([classify_artifact(p, games) for p in paths])
    return ledger.sort_values("filename_date").reset_index(drop=True)


def write_report(ledger: pd.DataFrame) -> Path:
    counts = ledger["classification"].value_counts()
    clean = ledger[ledger.classification == CLEAN]
    usable = clean[clean.filename_date.notna()]

    lines = [
        "# Phase 2F — Archive pregame integrity",
        "",
        f"**Date:** 2026-07-25  |  **Artifacts inventoried:** {len(ledger)}",
        "",
        "## Method",
        "",
        "Boards carry **no internal generation timestamp** — the only non-projection",
        "column is `SIM_RUNS`. File mtime is the creation proxy.",
        "`simulate_wnba_today.py` rewrites the dated file on every pipeline run, so",
        "mtime is the last run of that day, which is the freeze instant for the",
        "archived content. mtime is filesystem metadata and would not survive a copy",
        "or restore; that caveat applies to every row below.",
        "",
        "A game counts as tipped when `start_utc < creation`, and as completed when",
        f"`start_utc + {GAME_DURATION_HOURS}h < creation`.",
        "",
        "## Classification counts",
        "",
        "| Classification | Artifacts | Share |",
        "|---|---|---|",
    ]
    for name, count in counts.items():
        lines.append(f"| `{name}` | {count} | {count/len(ledger):.1%} |")

    lines += [
        "",
        f"**Only `{CLEAN}` artifacts may be used as exact historical production",
        "snapshots.**",
        "",
        "## Usable exact-snapshot range",
        "",
    ]
    if usable.empty:
        lines.append("No artifact qualifies as CLEAN_PREGAME.")
    else:
        lines += [
            f"- **{len(usable)} clean slates**, {usable.filename_date.min()} → "
            f"{usable.filename_date.max()}",
            f"- **{int(usable.rows.sum()):,} projection rows**",
            f"- covering **{int(usable.games_represented.sum())} games**",
        ]

    lines += ["", "## Per-artifact ledger", "",
              "| Artifact | rows | games | created (UTC) | earliest tip | tipped before creation | class |",
              "|---|---|---|---|---|---|---|"]
    for _, row in ledger.iterrows():
        created = str(row.get("file_mtime_utc", ""))[:16].replace("T", " ")
        earliest = str(row.get("earliest_tip_utc", ""))[:16].replace("T", " ")
        tipped = row.get("games_tipped_before_creation")
        total = row.get("games_represented")
        lines.append(
            f"| `{row.artifact_name}` | {row.get('rows', '')} | {total if pd.notna(total) else ''} | "
            f"{created} | {earliest} | "
            f"{'' if pd.isna(tipped) else f'{int(tipped)}/{int(total)}'} | `{row.classification}` |"
        )

    partial = ledger[ledger.classification == PARTIAL]
    if not partial.empty:
        share = partial["games_tipped_before_creation"].sum() / partial["games_represented"].sum()
        lines += [
            "", "## Why the partial artifacts are contaminated", "",
            f"{len(partial)} artifacts were written after at least one game tipped. Across",
            f"them, {int(partial['games_tipped_before_creation'].sum())} of "
            f"{int(partial['games_represented'].sum())} games ({share:.1%}) had already",
            "started. Because the pipeline refetches actuals at the start of every run and",
            "then serves each player's latest stored row, projections for the *remaining*",
            "games on such a board can incorporate results from the games that already",
            "finished. Those rows are not pregame and must not be graded as if they were.",
        ]

    lines += [
        "",
        "## Valid and invalid uses",
        "",
        "| Use | Verdict |",
        "|---|---|",
        f"| Exact historical production snapshot, `{CLEAN}` rows only | **Valid** |",
        f"| Exact snapshot using all archived rows | **Invalid** — mixes in post-tip rebuilds |",
        "| Measuring production *projection* accuracy over the clean slates | **Valid** |",
        "| Claiming this represents the historical model *version* | **Invalid** — binaries are overwritten in place, unversioned |",
        "| Extending the baseline before the first archived date | **Invalid** — no artifact exists |",
        "",
    ]
    target = C.lab_path("archive_integrity_report.md", root=C.LAB_REPORTS)
    target.write_text("\n".join(lines) + "\n")
    return target


def main() -> int:
    ledger = build_ledger()
    C.write_csv(ledger, "archive_ledger.csv", root=C.LAB_DATA / "baselines")
    report = write_report(ledger)

    counts = ledger["classification"].value_counts()
    clean = ledger[ledger.classification == CLEAN]
    print("PHASE 2F — ARCHIVE PREGAME INTEGRITY")
    print(f"  artifacts inventoried   {len(ledger)}")
    for name, count in counts.items():
        print(f"    {name:<20} {count}")
    if not clean.empty:
        print(f"\n  usable exact-snapshot range  {clean.filename_date.min()} -> "
              f"{clean.filename_date.max()}  ({len(clean)} slates, "
              f"{int(clean.rows.sum()):,} rows)")
    print(f"\n  wrote {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
