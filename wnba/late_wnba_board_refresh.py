#!/usr/bin/env python3
"""Phase 8: late pregame board refresh — capture late injury news and line movement.

Runs between the final full pipeline build (22:30 UTC) and tip-offs. Re-fetches the
PrizePicks lines and the ESPN injury feed, then adjusts the *published board only*:

  - removes bets on players who became OUT-like after the last build ("late_scratch")
  - removes bets whose line is no longer offered ("line_pulled")
  - removes bets whose line moved beyond a stat-specific threshold ("line_moved")
  - annotates smaller moves in the audit log without touching the board

Strictly removal/annotation-only: this script can never add a bet, never touches the
slate pipeline, features, models, or guards, and only acts on games that have not
started. Bet history is not rewritten — removals are recorded in
Best_Bets/wnba_late_refresh_audit.csv (a removed bet that was already recorded grades
normally; an OUT player's bet voids at the book anyway).

Every publish path goes through the one authoritative slate gate first
(wnba_model.pipeline.publish_gate): if today's canonical slate cannot be independently
validated, this script changes nothing and exits non-zero so the last verified board stays
up untouched.

Prints LATE_REFRESH_CHANGES=<n> so the cron wrapper knows whether to republish.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from wnba_model_config import (
    BEST_BETS_ARCHIVE_PATH,
    BEST_BETS_PATH,
    CANONICAL_PLAYER_STATUS_PATH,
    CANONICAL_SCHEDULE_TODAY_PATH,
    RAW_SPORTSBOOK_LINES_PATH,
)
from wnba_model_utils import canonicalize_name, normalize_player_status, setup_logging, today_timestamp

import fetch_wnba_data as fwd
import fetch_wnba_lines as fwl

from wnba_model.pipeline.publish_gate import (
    GATE_STATUS_PATH,
    PublishBlocked,
    require_validated_slate,
    resolve_slate_status,
)

AUDIT_PATH = BEST_BETS_PATH.parent / "wnba_late_refresh_audit.csv"
OUT_LIKE_STATUSES = {"out", "inactive", "suspended", "doubtful"}
LINE_MOVE_REMOVE_THRESHOLD = {
    "points": 1.5, "pra": 1.5, "pr": 1.5, "pa": 1.5,
    "rebounds": 1.0, "assists": 1.0, "ra": 1.0, "sb": 1.0,
    "steals": 0.5, "blocks": 0.5, "threes_made": 0.5,
}


def refresh_lines(logger, dry_run: bool = False) -> pd.DataFrame:
    """Re-fetch PrizePicks lines; on failure keep the existing file (stale but usable)."""
    if dry_run:
        try:
            return pd.read_csv(RAW_SPORTSBOOK_LINES_PATH)
        except Exception:
            return pd.DataFrame()
    try:
        payload, is_off_season = fwl.fetch_prizepicks_payload()
        if is_off_season:
            logger.info("PrizePicks reports off-season; keeping existing lines file.")
        else:
            raw = fwl.extract_rows(payload)
            filtered = fwl.filter_and_normalize(raw, logger)
            if not filtered.empty:
                fwl.write_lines(filtered, "api:prizepicks", logger)  # also appends snapshot
    except Exception as exc:
        logger.warning("Late line refresh failed (%s); using last fetched lines.", exc)
    try:
        return pd.read_csv(RAW_SPORTSBOOK_LINES_PATH)
    except Exception:
        return pd.DataFrame()


def refresh_status(logger, dry_run: bool = False) -> pd.DataFrame:
    """Re-fetch ESPN injuries; on failure keep the existing canonical status file."""
    if dry_run:
        try:
            return pd.read_csv(CANONICAL_PLAYER_STATUS_PATH)
        except Exception:
            return pd.DataFrame()
    try:
        raw, source = fwd.resolve_player_status(logger)
        status = normalize_player_status(raw)
        status["_data_source"] = source
        if status.empty and not str(source).startswith("api:"):
            # No live feed and no CSV — keep the build-time status instead of wiping it.
            logger.warning("Late status refresh got no data (source=%s); keeping existing file.", source)
            return pd.read_csv(CANONICAL_PLAYER_STATUS_PATH)
        status.to_csv(CANONICAL_PLAYER_STATUS_PATH, index=False)
        logger.info("Late status refresh: %d rows [source=%s]", len(status), source)
        return status
    except Exception as exc:
        logger.warning("Late status refresh failed (%s); using existing status file.", exc)
        try:
            return pd.read_csv(CANONICAL_PLAYER_STATUS_PATH)
        except Exception:
            return pd.DataFrame()


def team_start_times() -> dict[str, pd.Timestamp]:
    try:
        schedule = pd.read_csv(CANONICAL_SCHEDULE_TODAY_PATH)
    except Exception:
        return {}
    column = "start_time_utc" if "start_time_utc" in schedule.columns else "start_time"
    if column not in schedule.columns:
        return {}
    starts = {}
    for _, row in schedule.iterrows():
        start = pd.to_datetime(row.get(column), utc=True, errors="coerce")
        if pd.isna(start):
            continue
        for side in ("home_team", "away_team"):
            team = str(row.get(side, "")).strip().upper()
            if team:
                starts[team] = start
    return starts


def gate_or_block(logger) -> bool:
    """Central slate gate. Returns True when this run may touch the published board."""
    slate_date, message = resolve_slate_status()
    if not slate_date:
        logger.info("Late refresh: no current WNBA slate (%s); nothing to refresh.", message.replace("\n", " "))
        return False
    try:
        payload = require_validated_slate(slate_date, context="late_refresh")
    except PublishBlocked as exc:
        manifest = exc.manifest or {}
        logger.error(
            "Late refresh BLOCKED by slate gate: status=%s reason=%s validator=%s independence=%s",
            manifest.get("status"),
            manifest.get("failure_reason"),
            manifest.get("validator_source"),
            manifest.get("validation_independence"),
        )
        logger.error("Late refresh gate detail: %s", exc)
        print("LATE_REFRESH_CHANGES=0")
        print(f"LATE_REFRESH_BLOCKED=1 reason={manifest.get('failure_reason') or 'slate_validation_failed'}")
        print(f"Internal gate status written to {GATE_STATUS_PATH}")
        notify_freshness_monitor(logger)
        return False
    logger.info(
        "Late refresh slate gate: status=%s validator=%s independence=%s",
        payload.get("status"),
        payload.get("validator_source"),
        payload.get("validation_independence"),
    )
    return True


def notify_freshness_monitor(logger) -> None:
    """Reuse the existing freshness/alert mechanism instead of adding a second one."""
    try:
        import subprocess
        import sys as _sys

        subprocess.run([_sys.executable, str(Path(__file__).resolve().parent / "wnba_freshness_monitor.py")], timeout=120)
    except Exception as exc:
        logger.warning("Could not trigger WNBA freshness monitor after gate block: %s", exc)


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="WNBA late pregame board refresh")
    parser.add_argument("--dry-run", action="store_true", help="run the gate and compute removals without writing anything")
    args = parser.parse_args(argv)

    logger = setup_logging("late_wnba_board_refresh")
    now = pd.Timestamp.now(tz="UTC")

    if not gate_or_block(logger):
        return 3
    if args.dry_run:
        logger.info("Late refresh DRY RUN: slate gate cleared; computing removals without writing.")

    try:
        board = pd.read_csv(BEST_BETS_PATH)
    except Exception as exc:
        logger.warning("No best-bets board to refresh (%s).", exc)
        print("LATE_REFRESH_CHANGES=0")
        return 0
    if board.empty or "player_name" not in board.columns:
        logger.info("Board empty; nothing to refresh.")
        print("LATE_REFRESH_CHANGES=0")
        return 0

    # Slate dates are ET dates: a 00:45 UTC late run is still the previous ET evening.
    today = pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d")
    board_dates = set(board["bet_date"].dropna().astype(str)) if "bet_date" in board.columns else set()
    if board_dates and today not in board_dates:
        logger.info("Board is for %s, not today ET (%s); refusing to modify.", sorted(board_dates), today)
        print("LATE_REFRESH_CHANGES=0")
        return 0

    real = board[board["player_name"].fillna("").astype(str).str.strip() != ""]
    if real.empty:
        logger.info("Board has no player rows (empty-state); nothing to refresh.")
        print("LATE_REFRESH_CHANGES=0")
        return 0

    lines = refresh_lines(logger, dry_run=args.dry_run)
    status = refresh_status(logger, dry_run=args.dry_run)
    starts = team_start_times()

    out_keys = set()
    if not status.empty and "status" in status.columns:
        status = status.copy()
        status["player_key"] = status["player_name"].map(canonicalize_name)
        out_keys = set(
            status.loc[
                status["status"].astype(str).str.lower().isin(OUT_LIKE_STATUSES), "player_key"
            ]
        )

    line_lookup: dict[tuple[str, str], float] = {}
    if not lines.empty and {"player_name", "stat", "line"}.issubset(lines.columns):
        current = lines.copy()
        current["player_key"] = current["player_name"].map(canonicalize_name)
        current["stat"] = current["stat"].astype(str).str.strip().str.lower()
        current["line"] = pd.to_numeric(current["line"], errors="coerce")
        current = current.dropna(subset=["line"])
        line_lookup = {
            (row.player_key, row.stat): float(row.line) for row in current.itertuples()
        }

    keep_mask = []
    audit_rows = []
    for _, bet in board.iterrows():
        player_name = str(bet.get("player_name", "") or "").strip()
        if not player_name:
            keep_mask.append(True)
            continue
        player_key = canonicalize_name(player_name)
        stat = str(bet.get("stat", "")).strip().lower()
        bet_line = pd.to_numeric(bet.get("line"), errors="coerce")
        team = str(bet.get("team", "")).strip().upper()
        start = starts.get(team)
        base_audit = {
            "refreshed_at": now.isoformat(),
            "bet_date": bet.get("bet_date", ""),
            "player_name": player_name,
            "team": team,
            "stat": stat,
            "line": bet_line,
            "side": bet.get("side", ""),
            "game_start_utc": start.isoformat() if start is not None else "",
        }

        if start is not None and start <= now:
            keep_mask.append(True)  # game started: bet is locked history, never modify
            continue

        if player_key in out_keys:
            keep_mask.append(False)
            audit_rows.append({**base_audit, "action": "removed", "reason": "late_scratch", "current_line": np.nan})
            logger.info("Late scratch: removing %s %s %s", player_name, stat, bet_line)
            continue

        current_line = line_lookup.get((player_key, stat))
        if line_lookup and current_line is None:
            keep_mask.append(False)
            audit_rows.append({**base_audit, "action": "removed", "reason": "line_pulled", "current_line": np.nan})
            logger.info("Line pulled: removing %s %s %s", player_name, stat, bet_line)
            continue

        if current_line is not None and pd.notna(bet_line):
            move = abs(current_line - float(bet_line))
            threshold = LINE_MOVE_REMOVE_THRESHOLD.get(stat, 1.5)
            if move >= threshold:
                keep_mask.append(False)
                audit_rows.append({**base_audit, "action": "removed", "reason": "line_moved", "current_line": current_line})
                logger.info(
                    "Line moved %.1f (>=%.1f): removing %s %s %s -> %s",
                    move, threshold, player_name, stat, bet_line, current_line,
                )
                continue
            if move > 0:
                audit_rows.append({**base_audit, "action": "annotated", "reason": "line_drift", "current_line": current_line})

        keep_mask.append(True)

    removed = int(len(board) - sum(keep_mask))
    if args.dry_run:
        print(f"LATE_REFRESH_DRY_RUN_CHANGES={removed}")
        print("LATE_REFRESH_CHANGES=0")
        logger.info("Late refresh DRY RUN complete: %d bet(s) would be removed, %d annotation(s). Nothing written.", removed, len(audit_rows))
        return 0

    if audit_rows:
        audit = pd.DataFrame(audit_rows)
        audit.to_csv(AUDIT_PATH, mode="a", header=not AUDIT_PATH.exists(), index=False)

    if removed > 0:
        updated = board[pd.Series(keep_mask, index=board.index)].reset_index(drop=True)
        updated.to_csv(BEST_BETS_PATH, index=False)
        updated.to_csv(BEST_BETS_ARCHIVE_PATH, index=False)
        logger.info("Late refresh removed %d of %d bets; board updated.", removed, len(board))
    else:
        logger.info("Late refresh: no removals needed (%d annotations).", len(audit_rows))

    print(f"LATE_REFRESH_CHANGES={removed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
