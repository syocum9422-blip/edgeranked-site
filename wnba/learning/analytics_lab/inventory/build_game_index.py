"""Build the lab's chronological game index from the cached ESPN summaries.

The production pipeline stores ``game_date`` as the game's **UTC** date, which
is one day ahead of the real slate date for every evening tip-off. Ordering a
replay by that column mislabels slates and, on days that mix an afternoon and an
evening game, collapses two different ET slates onto one key. The lab therefore
derives its own index keyed on the exact tip-off timestamp.

Reads ``wnba_v2/data/team_games/_cache/<game_id>.json`` (read-only) and writes
``analytics_lab/data/normalized/game_index.csv`` with one row per game:

    game_id, start_utc, slate_date_et, tip_hour_et, utc_date, date_shifted,
    home_team, away_team, starters_flagged, athletes, dnp, injuries_listed,
    injuries_dated_pregame, has_odds

Idempotent and resumable: an existing index is reused for games already
processed unless ``--rebuild`` is passed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from analytics_lab.config import lab_config as C
else:
    from ..config import lab_config as C

INDEX_RELPATH = ("normalized", "game_index.csv")


def _summarize(game_id: str, payload: dict) -> dict:
    competition = (payload.get("header", {}).get("competitions") or [{}])[0]
    start_raw = competition.get("date")
    record: dict = {"game_id": game_id, "start_utc": start_raw}

    competitors = competition.get("competitors") or []
    for side in competitors:
        key = "home_team" if side.get("homeAway") == "home" else "away_team"
        record[key] = (side.get("team") or {}).get("abbreviation")

    starters = athletes = dnp = 0
    for team_block in payload.get("boxscore", {}).get("players", []) or []:
        for stat_block in team_block.get("statistics", []) or []:
            for athlete in stat_block.get("athletes", []) or []:
                athletes += 1
                starters += bool(athlete.get("starter"))
                dnp += bool(athlete.get("didNotPlay"))
    record.update(starters_flagged=starters, athletes=athletes, dnp=dnp)

    start_ts = pd.Timestamp(start_raw) if start_raw else pd.NaT
    listed = dated_pregame = 0
    for team_block in payload.get("injuries", []) or []:
        for entry in team_block.get("injuries", []) or []:
            listed += 1
            stamp = entry.get("date")
            if stamp and pd.notna(start_ts) and pd.Timestamp(stamp) < start_ts:
                dated_pregame += 1
    record.update(injuries_listed=listed, injuries_dated_pregame=dated_pregame)
    record["has_odds"] = bool(payload.get("pickcenter") or payload.get("odds"))
    return record


def build(rebuild: bool = False) -> pd.DataFrame:
    cache_dir = C.V2_ESPN_CACHE_DIR
    if not cache_dir.exists():
        raise FileNotFoundError(f"ESPN summary cache not found at {cache_dir}")

    target = C.lab_path(*INDEX_RELPATH)
    existing = pd.DataFrame()
    done: set[str] = set()
    if target.exists() and not rebuild:
        existing = pd.read_csv(target)
        done = set(existing["game_id"].astype(str))

    records: list[dict] = []
    skipped: list[str] = []
    for path in sorted(cache_dir.glob("*.json")):
        game_id = path.stem
        if game_id in done:
            continue
        try:
            payload = json.loads(path.read_text())
        except Exception as exc:  # a truncated cache entry must not kill the run
            skipped.append(f"{game_id}: {exc}")
            continue
        records.append(_summarize(game_id, payload))

    frame = pd.DataFrame(records)
    if not frame.empty:
        stamps = pd.to_datetime(frame["start_utc"], utc=True, errors="coerce")
        local = stamps.dt.tz_convert(C.SLATE_TIMEZONE)
        frame["slate_date_et"] = local.dt.date.astype("string")
        frame["tip_hour_et"] = local.dt.hour
        frame["utc_date"] = stamps.dt.date.astype("string")
        frame["date_shifted"] = frame["slate_date_et"] != frame["utc_date"]

    combined = pd.concat([existing, frame], ignore_index=True) if not existing.empty else frame
    combined = combined.drop_duplicates("game_id").sort_values("start_utc").reset_index(drop=True)
    C.write_csv(combined, *INDEX_RELPATH)

    print(f"game index: {len(combined)} games ({len(records)} newly parsed, {len(skipped)} skipped)")
    if not combined.empty:
        print(f"  span              {combined.slate_date_et.min()} -> {combined.slate_date_et.max()}")
        print(f"  start time known  {combined.start_utc.notna().mean():.1%}")
        print(f"  10 starters flagged {(combined.starters_flagged == 10).mean():.1%}")
        print(f"  UTC date != ET slate date {combined.date_shifted.mean():.1%}")
        pre = combined.injuries_dated_pregame
        print(f"  games w/ >=1 pregame-dated injury entry {(pre > 0).mean():.1%}")
    for line in skipped[:5]:
        print(f"  SKIPPED {line}")
    return combined


def load_game_index() -> pd.DataFrame:
    """Read the index, building it on first use."""
    target = C.lab_path(*INDEX_RELPATH)
    if not target.exists():
        return build()
    return pd.read_csv(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true", help="reparse every cached game")
    build(rebuild=parser.parse_args().rebuild)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
