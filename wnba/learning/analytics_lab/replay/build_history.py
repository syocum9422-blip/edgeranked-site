"""Normalize player-game and team-game history onto true tip-off timestamps.

Joins the production/V2 box scores to the lab's game index so every row carries
``start_utc`` and ``slate_date_et``. This is the only supported input to
:class:`~analytics_lab.replay.as_of_state.HistoryStore`.

Read-only w.r.t. production. Writes to ``analytics_lab/data/normalized/``.
Idempotent: rerunning regenerates the same output from the same inputs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from analytics_lab.config import lab_config as C
    from analytics_lab.inventory.build_game_index import load_game_index
else:
    from ..config import lab_config as C
    from ..inventory.build_game_index import load_game_index

PLAYER_OUT = ("normalized", "player_games_indexed.csv")
TEAM_OUT = ("normalized", "team_games_indexed.csv")


def _index_frame() -> pd.DataFrame:
    index = load_game_index()
    index["game_id"] = index["game_id"].astype(str)
    return index[["game_id", "start_utc", "slate_date_et", "tip_hour_et"]]


def build_player_games() -> pd.DataFrame:
    """Prefer the V2 box scores (they carry starter/played/position per game).

    Rows whose ``game_id`` is absent from the index cannot be placed on the
    timeline and are dropped rather than guessed at — a dropped row is a visible
    gap, an invented timestamp is a silent leak.
    """
    source = C.V2_PLAYER_BOXSCORES if C.V2_PLAYER_BOXSCORES.exists() else C.PROD_PLAYER_GAMES
    frame = pd.read_csv(source, low_memory=False)
    frame["source_file"] = source.name
    frame = frame[frame["game_id"].notna()].copy()
    frame["game_id"] = pd.to_numeric(frame["game_id"], errors="coerce").astype("Int64").astype(str)

    merged = frame.merge(_index_frame(), on="game_id", how="left")
    dropped = int(merged["start_utc"].isna().sum())
    merged = merged[merged["start_utc"].notna()].copy()
    merged.attrs["dropped_unindexed_rows"] = dropped
    return merged.sort_values("start_utc").reset_index(drop=True)


def build_team_games() -> pd.DataFrame:
    frame = pd.read_csv(C.V2_TEAM_GAME_LOGS, low_memory=False)
    frame["game_id"] = pd.to_numeric(frame["game_id"], errors="coerce").astype("Int64").astype(str)
    merged = frame.merge(_index_frame(), on="game_id", how="left")
    dropped = int(merged["start_utc"].isna().sum())
    merged = merged[merged["start_utc"].notna()].copy()
    merged.attrs["dropped_unindexed_rows"] = dropped
    return merged.sort_values("start_utc").reset_index(drop=True)


def main() -> int:
    players = build_player_games()
    teams = build_team_games()
    C.write_csv(players, *PLAYER_OUT)
    C.write_csv(teams, *TEAM_OUT)

    print(f"player-games {len(players):>6} rows  "
          f"({players.attrs['dropped_unindexed_rows']} dropped: no indexed game)")
    print(f"team-games   {len(teams):>6} rows  "
          f"({teams.attrs['dropped_unindexed_rows']} dropped: no indexed game)")
    print(f"span         {players.slate_date_et.min()} -> {players.slate_date_et.max()}")
    dupes = int(players.duplicated(["player_key", "game_id"]).sum())
    print(f"duplicate (player_key, game_id) rows: {dupes}")
    print(f"wrote {C.LAB_NORMALIZED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
