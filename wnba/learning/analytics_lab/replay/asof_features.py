"""Phase 2B — as-of feature reconstruction for upcoming player-games.

Builds a **new row for an upcoming game** rather than serving the player's last
historical row. Every rolling and expanding value is computed from games whose
result was already known at the target game's tip-off, and excludes the target
game itself.

The as-of rule
--------------
A prior game counts only when ``end_utc <= target start_utc``, where ``end_utc``
is the tip-off plus :data:`GAME_DURATION_HOURS`. Tip-off order alone is not
sufficient: on a normal slate a 19:00 game is still being played when a 20:00
game tips, so ordering by tip would leak an in-progress result into the later
game's features.

For player-, team- and opponent-level features this reduces to ``shift(1)`` over
a tip-ordered history, because no team plays two games inside one game-length
window. That equivalence is asserted at build time
(:func:`assert_no_overlapping_history`) rather than assumed, and the one known
ESPN artifact that violates it is excluded as a phantom row.

Identity is by ESPN numeric id throughout. A traded player keeps one
``player_id`` and carries the ``team_id`` recorded on each historical box score,
so pre-trade games stay attributed to the pre-trade team. Positions come from the
per-game ESPN box score, never from the current roster file.

Output: ``data/features/asof_features.parquet``
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from analytics_lab.config import lab_config as C
else:
    from ..config import lab_config as C

GAME_DURATION_HOURS = 2.25          # conservative WNBA game length incl. stoppages
STATS = ["minutes", "points", "rebounds", "assists", "threes_made", "steals", "blocks",
         "turnovers", "fga", "fta"]
WINDOWS = (3, 5, 10)
RECENT_DAY_WINDOWS = (3, 5, 7, 14)
EWM_ALPHA = 0.35


class OverlapError(RuntimeError):
    """A unit's history contains games that overlap in time."""


# --- loading ----------------------------------------------------------------

def load_player_games(include_preseason: bool = False) -> pd.DataFrame:
    """Canonical player-games, cleaned of rows that cannot inform a feature.

    Two exclusions, both evidence-driven:

    * **Preseason** (32 games, 937 rows). Rotations and minutes are not
      representative, and the production canonical file mixes them in unlabelled.
    * **Phantom listings** (32 rows, 0.17%): a player appears on a box score with
      no stat line and no DNP flag — an ESPN artifact around trades, e.g. Celeste
      Taylor listed for CON and PHX in two simultaneous 2024-08-23 games.
    """
    path = C.LAB_NORMALIZED / "player_games.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run inventory/parse_espn_cache.py first")
    frame = pd.read_parquet(path)

    frame["phantom_listing"] = (frame["minutes"].isna() & (frame["did_not_play"] == 0)).astype(int)
    frame = frame[frame["phantom_listing"] == 0].drop(columns=["phantom_listing"])
    if not include_preseason:
        frame = frame[frame["season_type"] != "preseason"]

    frame["start_ts"] = pd.to_datetime(frame["start_utc"], utc=True)
    frame["end_ts"] = frame["start_ts"] + pd.Timedelta(hours=GAME_DURATION_HOURS)
    return frame.sort_values(["start_ts", "game_id", "player_id"]).reset_index(drop=True)


def load_team_games(include_preseason: bool = False) -> pd.DataFrame:
    path = C.LAB_NORMALIZED / "team_games.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run inventory/parse_espn_cache.py first")
    frame = pd.read_parquet(path)
    if not include_preseason:
        frame = frame[frame["season_type"] != "preseason"]
    frame["start_ts"] = pd.to_datetime(frame["start_utc"], utc=True)
    frame["end_ts"] = frame["start_ts"] + pd.Timedelta(hours=GAME_DURATION_HOURS)
    return frame.sort_values(["start_ts", "team_id"]).reset_index(drop=True)


def assert_no_overlapping_history(frame: pd.DataFrame, unit: str) -> None:
    """shift(1) equals the end_utc rule only if a unit never overlaps itself."""
    ordered = frame.sort_values([unit, "start_ts"])
    previous_end = ordered.groupby(unit)["end_ts"].shift(1)
    overlapping = (previous_end > ordered["start_ts"]).fillna(False)
    if overlapping.any():
        sample = ordered.loc[overlapping, [unit, "game_id", "start_utc"]].head(5)
        raise OverlapError(
            f"{int(overlapping.sum())} {unit} rows overlap a previous game, so shift(1) "
            f"would leak an in-progress result:\n{sample.to_string(index=False)}"
        )


# --- player features --------------------------------------------------------

def _shifted_rolling(grouped, window: int, how: str = "mean") -> pd.Series:
    return grouped.transform(
        lambda s: getattr(s.shift(1).rolling(window, min_periods=1), how)()
    )


def build_player_features(games: pd.DataFrame) -> pd.DataFrame:
    """Player-level as-of features. Every value excludes the target game."""
    assert_no_overlapping_history(games, "player_id")
    frame = games.sort_values(["player_id", "start_ts"]).copy()
    by_player = frame.groupby("player_id", sort=False)

    frame["prev_game_minutes"] = by_player["minutes"].shift(1)
    frame["prev_game_start_ts"] = by_player["start_ts"].shift(1)
    frame["prev_game_team_id"] = by_player["team_id"].shift(1)
    frame["prev_game_started"] = by_player["starter"].shift(1)
    frame["prev_game_played"] = by_player["played"].shift(1)

    for stat in STATS:
        column = by_player[stat]
        for window in WINDOWS:
            frame[f"{stat}_last_{window}"] = _shifted_rolling(column, window, "mean")
            frame[f"{stat}_std_{window}"] = column.transform(
                lambda s: s.shift(1).rolling(window, min_periods=2).std()
            )
        frame[f"{stat}_ewm"] = column.transform(
            lambda s: s.shift(1).ewm(alpha=EWM_ALPHA, adjust=False).mean()
        )

    # Expanding season averages: prior games in this season only.
    by_player_season = frame.groupby(["player_id", "season"], sort=False)
    for stat in STATS:
        frame[f"season_avg_{stat}"] = by_player_season[stat].transform(
            lambda s: s.shift(1).expanding().mean()
        )
    frame["games_played_season"] = by_player_season.cumcount()
    frame["games_started_season"] = by_player_season["starter"].transform(
        lambda s: s.shift(1).expanding().sum()
    )
    frame["start_rate_season"] = (
        frame["games_started_season"] / frame["games_played_season"].replace(0, np.nan)
    )
    frame["games_appeared_season"] = by_player_season["played"].transform(
        lambda s: s.shift(1).expanding().sum()
    )

    for window in WINDOWS:
        frame[f"starts_last_{window}"] = _shifted_rolling(by_player["starter"], window, "sum")
        frame[f"played_rate_last_{window}"] = _shifted_rolling(by_player["played"], window, "mean")
    frame["minutes_trend_3_over_10"] = frame["minutes_last_3"] - frame["minutes_last_10"]

    # Rest, measured from the previous tip-off — exact, not date-differenced.
    rest_hours = (frame["start_ts"] - frame["prev_game_start_ts"]).dt.total_seconds() / 3600.0
    frame["rest_hours"] = rest_hours
    frame["rest_days"] = np.floor(rest_hours / 24.0)
    frame["is_back_to_back"] = (rest_hours < 36.0).astype("Int64")
    frame.loc[rest_hours.isna(), "is_back_to_back"] = pd.NA

    # Team change since the previous game — an explicit trade signal rather than
    # a silently rewritten history.
    frame["changed_team"] = (
        frame["prev_game_team_id"].notna() & (frame["prev_game_team_id"] != frame["team_id"])
    ).astype(int)

    frame = _add_recent_game_counts(frame)
    return frame


def _add_recent_game_counts(frame: pd.DataFrame) -> pd.DataFrame:
    """Games played in the N days before the target tip, target excluded."""
    out = frame.sort_values(["player_id", "start_ts"]).copy()
    for window in RECENT_DAY_WINDOWS:
        out[f"games_prior_{window}d"] = 0
    for player_id, group in out.groupby("player_id", sort=False):
        starts = group["start_ts"].to_numpy()
        ends = group["end_ts"].to_numpy()
        for window in RECENT_DAY_WINDOWS:
            span = np.timedelta64(window * 24, "h")
            counts = [
                int(((ends[:i] <= starts[i]) & (starts[:i] >= starts[i] - span)).sum())
                for i in range(len(starts))
            ]
            out.loc[group.index, f"games_prior_{window}d"] = counts
    return out


# --- team and opponent features ---------------------------------------------

TEAM_ROLL_COLUMNS = {
    "pace": "pace", "off_rating": "off_rating", "def_rating": "def_rating",
    "net_rating": "net_rating", "team_points": "team_points",
    "opponent_points": "points_allowed", "possessions": "possessions",
}


def build_team_context(teams: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """As-of team form, shift(1) rolling over the team's completed games."""
    assert_no_overlapping_history(teams, "team_id")
    frame = teams.sort_values(["team_id", "start_ts"]).copy()
    by_team = frame.groupby("team_id", sort=False)
    for source, name in TEAM_ROLL_COLUMNS.items():
        frame[f"{name}_last_{window}"] = _shifted_rolling(by_team[source], window, "mean")
    frame["team_games_played"] = by_team.cumcount()
    keep = ["game_id", "team_id", "team_games_played"] + [
        f"{n}_last_{window}" for n in TEAM_ROLL_COLUMNS.values()
    ]
    return frame[keep]


def build_opponent_allowance(games: pd.DataFrame, window: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """What a defence has been allowing, overall and by position.

    Built from the same player-game table, aggregated by the *defending* team.
    Positions come from each historical box score, so the grouping is correct for
    the date rather than reflecting today's roster.
    """
    played = games[games["played"] == 1]
    allowed_stats = ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]

    team_allowed = (
        played.groupby(["game_id", "opponent_id", "start_ts", "end_ts"], as_index=False)[allowed_stats]
        .sum().rename(columns={"opponent_id": "team_id"})
        .sort_values(["team_id", "start_ts"])
    )
    by_defence = team_allowed.groupby("team_id", sort=False)
    for stat in allowed_stats:
        team_allowed[f"allowed_{stat}_last_{window}"] = _shifted_rolling(by_defence[stat], window, "mean")
    team_columns = ["game_id", "team_id"] + [f"allowed_{s}_last_{window}" for s in allowed_stats]

    position_allowed = (
        played.groupby(["game_id", "opponent_id", "position", "start_ts", "end_ts"], as_index=False)[allowed_stats]
        .sum().rename(columns={"opponent_id": "team_id"})
        .sort_values(["team_id", "position", "start_ts"])
    )
    by_defence_position = position_allowed.groupby(["team_id", "position"], sort=False)
    for stat in allowed_stats:
        position_allowed[f"pos_allowed_{stat}_last_{window}"] = _shifted_rolling(
            by_defence_position[stat], window, "mean"
        )
    position_columns = ["game_id", "team_id", "position"] + [
        f"pos_allowed_{s}_last_{window}" for s in allowed_stats
    ]
    return team_allowed[team_columns], position_allowed[position_columns]


# --- assembly ---------------------------------------------------------------

def build_asof_features(include_preseason: bool = False, window: int = 10) -> pd.DataFrame:
    games = load_player_games(include_preseason=include_preseason)
    teams = load_team_games(include_preseason=include_preseason)

    frame = build_player_features(games)
    team_context = build_team_context(teams, window=window)
    team_allowed, position_allowed = build_opponent_allowance(games, window=window)

    frame = frame.merge(team_context, on=["game_id", "team_id"], how="left")
    frame = frame.merge(
        team_context.rename(columns=lambda c: (
            "opponent_id" if c == "team_id" else
            c if c == "game_id" else f"opp_{c}"
        )),
        on=["game_id", "opponent_id"], how="left",
    )
    frame = frame.merge(
        team_allowed.rename(columns={"team_id": "opponent_id"}),
        on=["game_id", "opponent_id"], how="left",
    )
    frame = frame.merge(
        position_allowed.rename(columns={"team_id": "opponent_id"}),
        on=["game_id", "opponent_id", "position"], how="left",
    )
    return frame.sort_values(["start_ts", "game_id", "player_id"]).reset_index(drop=True)


def main() -> int:
    frame = build_asof_features()
    target = C.lab_path("features", "asof_features.parquet")
    frame.drop(columns=["start_ts", "end_ts", "prev_game_start_ts"]).to_parquet(target, index=False)

    print("PHASE 2B — AS-OF FEATURE RECONSTRUCTION")
    print(f"  rows                     {len(frame)}")
    print(f"  columns                  {frame.shape[1]}")
    print(f"  players / games          {frame.player_id.nunique()} / {frame.game_id.nunique()}")
    print(f"  span (ET slate)          {frame.slate_date_et.min()} -> {frame.slate_date_et.max()}")
    print(f"  duplicate (player_id, game_id)  {frame.duplicated(['player_id','game_id']).sum()}")
    print(f"  rows with a prior game   {frame.prev_game_minutes.notna().sum()} "
          f"({frame.prev_game_minutes.notna().mean():.1%})")
    print(f"  rows flagged changed_team {int(frame.changed_team.sum())}")
    print("\n  coverage of key as-of features (non-null share)")
    for column in ["minutes_last_3", "minutes_last_10", "season_avg_points",
                   "pace_last_10", "opp_def_rating_last_10", "allowed_points_last_10",
                   "pos_allowed_points_last_10", "rest_hours", "games_prior_7d"]:
        print(f"    {column:<30} {frame[column].notna().mean():.1%}")
    print(f"\n  wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
