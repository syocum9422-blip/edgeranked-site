"""Phase 3 data — full per-player box scores parsed from the ESPN summary cache.

No new network calls: this parses the same cached game summaries the team
box-score ingestion already downloaded. It yields COMPLETE rosters (every
athlete, including DNPs) — which the curated player dataset lacked — enabling:
  * exact share conservation for the usage engine (team-sum of shares == 1)
  * real DNP rows (fixes Phase 1 Stage-A survivorship bias)
  * player 3PA (was missing from the curated dataset)

Run:  .venv/bin/python -m wnba_v2.data.player_boxscores
"""
from __future__ import annotations

import glob
import json

import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.data.team_boxscores import CACHE_DIR
from wnba_v2.engines.usage.features import ESPN_TO_PLAYER, REAL_TEAMS  # reuse the alias map

PLAYER_GAMES_PATH = C.V2_ROOT / "data" / "team_games" / "player_game_logs.csv"


def _ma(v: str) -> tuple[float, float]:
    if isinstance(v, str) and "-" in v:
        a, b = v.split("-", 1)
        try:
            return float(a), float(b)
        except ValueError:
            return np.nan, np.nan
    return np.nan, np.nan


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def parse_summary(summary: dict) -> list[dict]:
    bs = summary.get("boxscore", {})
    pblocks = bs.get("players", [])
    header = summary.get("header", {})
    comp = header.get("competitions", [{}])[0]
    date = str(comp.get("date", ""))[:10]
    season = header.get("season", {}).get("year")
    abbrs = [pb.get("team", {}).get("abbreviation") for pb in pblocks]
    if len(pblocks) != 2:
        return []

    rows = []
    for i, pb in enumerate(pblocks):
        espn_abbr = pb.get("team", {}).get("abbreviation")
        team = ESPN_TO_PLAYER.get(espn_abbr, espn_abbr)
        opp_espn = abbrs[1 - i]
        opponent = ESPN_TO_PLAYER.get(opp_espn, opp_espn)
        stat_group = (pb.get("statistics") or [{}])[0]
        labels = stat_group.get("labels", [])
        for ath in stat_group.get("athletes", []):
            dnp = bool(ath.get("didNotPlay"))
            vals = ath.get("stats") or []
            s = dict(zip(labels, vals)) if vals and not dnp else {}
            fgm, fga = _ma(s.get("FG"))
            fg3m, fg3a = _ma(s.get("3PT"))
            ftm, fta = _ma(s.get("FT"))
            athlete = ath.get("athlete", {})
            pos = athlete.get("position", {})
            rows.append({
                "date": date, "season": season, "game_id": summary.get("header", {}).get("id"),
                "team": team, "opponent": opponent,
                "player_name": athlete.get("displayName"),
                "player_id": athlete.get("id"),
                "position": pos.get("abbreviation") if isinstance(pos, dict) else None,
                "starter": int(bool(ath.get("starter"))),
                "played": 0 if dnp else 1,
                "minutes": 0.0 if dnp else _f(s.get("MIN")),
                "points": 0.0 if dnp else _f(s.get("PTS")),
                "fga": 0.0 if dnp else fga, "fgm": 0.0 if dnp else fgm,
                "fg3a": 0.0 if dnp else fg3a, "fg3m": 0.0 if dnp else fg3m,
                "fta": 0.0 if dnp else fta, "ftm": 0.0 if dnp else ftm,
                "reb": 0.0 if dnp else _f(s.get("REB")),
                "oreb": 0.0 if dnp else _f(s.get("OREB")),
                "dreb": 0.0 if dnp else _f(s.get("DREB")),
                "ast": 0.0 if dnp else _f(s.get("AST")),
                "tov": 0.0 if dnp else _f(s.get("TO")),
                "stl": 0.0 if dnp else _f(s.get("STL")),
                "blk": 0.0 if dnp else _f(s.get("BLK")),
                "pf": 0.0 if dnp else _f(s.get("PF")),
            })
    return rows


def build(only_real_teams: bool = True) -> pd.DataFrame:
    rows = []
    for f in sorted(glob.glob(str(CACHE_DIR / "*.json"))):
        rows.extend(parse_summary(json.load(open(f))))
    if not rows:
        raise RuntimeError("No cached summaries to parse — run team_boxscores first.")
    df = pd.DataFrame(rows)
    if only_real_teams:
        df = df[df["team"].isin(REAL_TEAMS)].copy()
    df = df.dropna(subset=["player_id", "date"])
    df.to_csv(PLAYER_GAMES_PATH, index=False)
    return df


if __name__ == "__main__":
    df = build()
    played = df[df["played"] == 1]
    print(f"parsed {len(df)} player-game rows ({df['game_id'].nunique()} games)")
    print(f"  played: {len(played)} | DNP: {(df['played']==0).sum()} "
          f"({(df['played']==0).mean()*100:.1f}% — real DNP signal, vs 0.1% in curated set)")
    print(f"  players per team-game (median): {played.groupby(['game_id','team']).size().median():.0f}")
    print(f"  seasons: {sorted(df['season'].dropna().unique().tolist())}")
    print(f"  -> {PLAYER_GAMES_PATH}")
