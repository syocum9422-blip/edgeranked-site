"""Point-in-time state: what was knowable before a given tip-off.

Every historical feature the lab builds goes through :class:`AsOfState`, whose
one job is to make future data unreachable. It holds the full player-game
history plus the tip-off timestamp index, and exposes only ``before(cutoff)``
views.

Why a timestamp cutoff rather than a date cutoff: the production ``game_date``
column is the game's UTC date, so an evening ET game is filed under the next
day and a slate that mixes an afternoon and an evening game lands two different
ET slates on one key. Filtering on tip-off time is exact and needs no
convention.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from analytics_lab.config import lab_config as C
else:
    from ..config import lab_config as C


class LeakageError(RuntimeError):
    """Raised when a caller reaches for data at or after the cutoff."""


@dataclass(frozen=True)
class AsOfState:
    """Immutable view of history strictly before ``cutoff``."""

    cutoff: pd.Timestamp
    player_games: pd.DataFrame       # one row per player-game, with start_utc
    team_games: pd.DataFrame         # one row per team-game, with start_utc

    def __post_init__(self) -> None:
        for name in ("player_games", "team_games"):
            frame = getattr(self, name)
            if frame.empty:
                continue
            latest = pd.to_datetime(frame["start_utc"], utc=True).max()
            if latest >= self.cutoff:
                raise LeakageError(
                    f"{name} contains a game starting {latest} at or after cutoff {self.cutoff}"
                )

    # -- leak-safe primitives -------------------------------------------------

    def player_history(self, player_key: str) -> pd.DataFrame:
        frame = self.player_games
        return frame[frame["player_key"] == player_key].sort_values("start_utc")

    def rolling_mean(self, column: str, window: int) -> pd.Series:
        """Mean of a player's last ``window`` completed games, indexed by player_key.

        Unlike production this is computed at the cutoff, so it *includes* the
        player's most recent completed game. Production instead carries the
        shift(1) value stored on that game's row, which drops it.
        """
        frame = self.player_games.sort_values("start_utc")
        return frame.groupby("player_key")[column].apply(lambda s: s.tail(window).mean())

    def games_played(self) -> pd.Series:
        return self.player_games.groupby("player_key").size()

    def last_game_time(self) -> pd.Series:
        stamps = pd.to_datetime(self.player_games["start_utc"], utc=True)
        return stamps.groupby(self.player_games["player_key"]).max()

    def rest_hours(self, player_key: str) -> float | None:
        """Hours between the player's previous tip-off and the cutoff."""
        history = self.player_history(player_key)
        if history.empty:
            return None
        previous = pd.to_datetime(history["start_utc"], utc=True).max()
        return float((self.cutoff - previous).total_seconds() / 3600.0)


class HistoryStore:
    """Loads history once, then serves cheap :class:`AsOfState` slices."""

    def __init__(self, player_games: pd.DataFrame, team_games: pd.DataFrame) -> None:
        self._players = player_games.sort_values("start_utc").reset_index(drop=True)
        self._teams = team_games.sort_values("start_utc").reset_index(drop=True)
        self._player_ts = pd.to_datetime(self._players["start_utc"], utc=True)
        self._team_ts = pd.to_datetime(self._teams["start_utc"], utc=True)

    @classmethod
    def from_lab_data(cls) -> "HistoryStore":
        """Build from the lab's normalized player-game and team-game tables.

        Requires ``replay/build_history.py`` to have run. Deliberately does not
        fall back to the production canonical files: those carry no tip-off
        timestamps, and a silent fallback to date-only ordering is exactly the
        kind of quiet leak this class exists to prevent.
        """
        players = C.LAB_NORMALIZED / "player_games_indexed.csv"
        teams = C.LAB_NORMALIZED / "team_games_indexed.csv"
        missing = [str(p) for p in (players, teams) if not p.exists()]
        if missing:
            raise FileNotFoundError(
                "normalized history not built: " + ", ".join(missing)
                + " — run replay/build_history.py first"
            )
        return cls(pd.read_csv(players, low_memory=False), pd.read_csv(teams, low_memory=False))

    def as_of(self, cutoff: pd.Timestamp | str) -> AsOfState:
        moment = pd.Timestamp(cutoff)
        if moment.tzinfo is None:
            moment = moment.tz_localize("UTC")
        return AsOfState(
            cutoff=moment,
            player_games=self._players[self._player_ts < moment].copy(),
            team_games=self._teams[self._team_ts < moment].copy(),
        )

    def slate_cutoffs(self) -> pd.DataFrame:
        """One replay checkpoint per (ET slate date, tip-off time).

        Games on the same slate that tip at different times get separate
        checkpoints, so an evening game may legitimately use an afternoon game's
        result while an afternoon game never sees the evening's.
        """
        frame = self._teams[["game_id", "start_utc", "slate_date_et"]].drop_duplicates("game_id")
        return frame.sort_values("start_utc").reset_index(drop=True)
