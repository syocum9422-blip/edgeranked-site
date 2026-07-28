"""Phase 2B — proofs that as-of feature reconstruction cannot see the future.

Each test names the specific failure mode it rules out. Regression tests for the
Phase 1 and Phase 2 findings live at the bottom.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from analytics_lab.config import lab_config as C  # noqa: E402
from analytics_lab.replay import asof_features as AF  # noqa: E402


# --- synthetic fixtures -----------------------------------------------------

def _game(game_id, player_id, team_id, opponent_id, start, minutes, points,
          starter=1, played=1, position="G", season=2026, season_type="regular"):
    return {
        "game_id": game_id, "player_id": player_id, "player_name": f"p{player_id}",
        "team_id": team_id, "opponent_id": opponent_id, "team_abbrev": f"T{team_id}",
        "opponent_abbrev": f"T{opponent_id}", "start_utc": start,
        "slate_date_et": pd.Timestamp(start).tz_convert(C.SLATE_TIMEZONE).date().isoformat(),
        "season": season, "season_type": season_type, "position": position,
        "starter": starter, "played": played, "did_not_play": 0 if played else 1,
        "is_home": 1, "minutes": minutes, "points": points, "rebounds": 0.0,
        "assists": 0.0, "threes_made": 0.0, "steals": 0.0, "blocks": 0.0,
        "turnovers": 0.0, "fga": 0.0, "fta": 0.0,
    }


def _prepare(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["start_ts"] = pd.to_datetime(frame["start_utc"], utc=True)
    frame["end_ts"] = frame["start_ts"] + pd.Timedelta(hours=AF.GAME_DURATION_HOURS)
    return frame.sort_values(["start_ts", "game_id", "player_id"]).reset_index(drop=True)


@pytest.fixture
def simple_history() -> pd.DataFrame:
    """One player, four games, minutes 10 / 20 / 30 / 99."""
    return _prepare([
        _game("g1", "1", "10", "20", "2026-06-01T23:00:00+00:00", 10.0, 5.0),
        _game("g2", "1", "10", "20", "2026-06-03T23:00:00+00:00", 20.0, 15.0),
        _game("g3", "1", "10", "20", "2026-06-05T23:00:00+00:00", 30.0, 25.0),
        _game("g4", "1", "10", "20", "2026-06-07T23:00:00+00:00", 99.0, 99.0),
    ])


# --- the exclusion rules ----------------------------------------------------

def test_target_game_is_excluded_from_its_own_features(simple_history):
    built = AF.build_player_features(simple_history)
    target = built[built.game_id == "g4"].iloc[0]
    assert target["minutes_last_3"] == pytest.approx(20.0)   # mean(10, 20, 30)
    assert target["points_last_3"] == pytest.approx(15.0)    # mean(5, 15, 25)
    assert target["minutes_last_3"] != 99.0, "the target game leaked into its own feature"


def test_immediately_previous_game_is_included(simple_history):
    built = AF.build_player_features(simple_history)
    target = built[built.game_id == "g4"].iloc[0]
    assert target["prev_game_minutes"] == pytest.approx(30.0)
    # The one-game-stale production behaviour would give mean(10, 20) == 15.
    assert target["minutes_last_3"] != pytest.approx(15.0)


def test_first_game_has_no_history(simple_history):
    built = AF.build_player_features(simple_history)
    first = built[built.game_id == "g1"].iloc[0]
    assert pd.isna(first["prev_game_minutes"])
    assert pd.isna(first["minutes_last_3"])
    assert first["games_played_season"] == 0


def test_expanding_season_average_uses_prior_games_only(simple_history):
    built = AF.build_player_features(simple_history)
    target = built[built.game_id == "g4"].iloc[0]
    assert target["season_avg_points"] == pytest.approx(15.0)  # mean(5, 15, 25)


# --- same-day ordering ------------------------------------------------------

def test_same_day_earlier_completed_game_is_included():
    """An afternoon game that has finished is legitimate input to an evening game."""
    history = _prepare([
        # 13:00 ET tip, ends 15:15 ET — complete well before the 20:00 ET tip.
        _game("early", "1", "10", "20", "2026-06-10T17:00:00+00:00", 12.0, 8.0),
        _game("late", "1", "10", "30", "2026-06-11T00:00:00+00:00", 40.0, 40.0),
    ])
    built = AF.build_player_features(history)
    late = built[built.game_id == "late"].iloc[0]
    assert late["prev_game_minutes"] == pytest.approx(12.0)
    assert late["minutes_last_3"] == pytest.approx(12.0)


def test_later_game_on_same_day_is_excluded():
    """The earlier game must not see the later one, in either direction."""
    history = _prepare([
        _game("early", "1", "10", "20", "2026-06-10T17:00:00+00:00", 12.0, 8.0),
        _game("late", "1", "10", "30", "2026-06-11T00:00:00+00:00", 40.0, 40.0),
    ])
    built = AF.build_player_features(history)
    early = built[built.game_id == "early"].iloc[0]
    assert pd.isna(early["prev_game_minutes"])
    assert pd.isna(early["minutes_last_3"])


def test_overlapping_games_are_rejected_not_silently_shifted():
    """Two games inside one game-length window break the shift(1) equivalence."""
    history = _prepare([
        _game("a", "1", "10", "20", "2026-06-10T23:00:00+00:00", 12.0, 8.0),
        _game("b", "1", "11", "30", "2026-06-11T00:00:00+00:00", 20.0, 10.0),  # 1h later
    ])
    with pytest.raises(AF.OverlapError):
        AF.build_player_features(history)


def test_game_duration_defines_the_completion_boundary():
    """A game tipping exactly one game-length after another is legal; less is not."""
    boundary = pd.Timestamp("2026-06-10T23:00:00+00:00") + pd.Timedelta(hours=AF.GAME_DURATION_HOURS)
    history = _prepare([
        _game("a", "1", "10", "20", "2026-06-10T23:00:00+00:00", 12.0, 8.0),
        _game("b", "1", "11", "30", boundary.isoformat(), 20.0, 10.0),
    ])
    built = AF.build_player_features(history)          # must not raise
    assert built[built.game_id == "b"].iloc[0]["prev_game_minutes"] == pytest.approx(12.0)


# --- identity ---------------------------------------------------------------

def test_traded_player_keeps_one_id_and_correct_historical_teams():
    history = _prepare([
        _game("g1", "1", "10", "20", "2026-06-01T23:00:00+00:00", 20.0, 10.0),
        _game("g2", "1", "10", "20", "2026-06-03T23:00:00+00:00", 22.0, 12.0),
        _game("g3", "1", "77", "20", "2026-06-06T23:00:00+00:00", 30.0, 18.0),  # traded to 77
    ])
    built = AF.build_player_features(history)
    assert built["player_id"].nunique() == 1
    post_trade = built[built.game_id == "g3"].iloc[0]
    assert post_trade["team_id"] == "77", "post-trade game must carry the new team"
    assert post_trade["prev_game_team_id"] == "10", "history must keep the pre-trade team"
    assert post_trade["changed_team"] == 1
    # Form still carries across the trade — the player is the same player.
    assert post_trade["minutes_last_3"] == pytest.approx(21.0)
    pre_trade = built[built.game_id == "g1"].iloc[0]
    assert pre_trade["team_id"] == "10", "pre-trade rows must not be rewritten to the new team"


def test_rest_hours_measured_from_tipoff_not_calendar_date():
    history = _prepare([
        # 22:00 ET Jun 10 (= Jun 11 02:00 UTC) then 15:30 ET Jun 12: 41.5 hours.
        _game("g1", "1", "10", "20", "2026-06-11T02:00:00+00:00", 20.0, 10.0),
        _game("g2", "1", "10", "20", "2026-06-12T19:30:00+00:00", 24.0, 12.0),
    ])
    built = AF.build_player_features(history)
    second = built[built.game_id == "g2"].iloc[0]
    assert second["rest_hours"] == pytest.approx(41.5)
    assert second["is_back_to_back"] == 0


def test_back_to_back_detected_across_a_utc_date_boundary():
    history = _prepare([
        _game("g1", "1", "10", "20", "2026-06-11T02:00:00+00:00", 20.0, 10.0),  # Jun 10 ET
        _game("g2", "1", "10", "20", "2026-06-12T00:00:00+00:00", 24.0, 12.0),  # Jun 11 ET
    ])
    built = AF.build_player_features(history)
    second = built[built.game_id == "g2"].iloc[0]
    assert second["rest_hours"] == pytest.approx(22.0)
    assert second["is_back_to_back"] == 1


def test_recent_game_counts_exclude_the_target_game():
    history = _prepare([
        _game("g1", "1", "10", "20", "2026-06-01T23:00:00+00:00", 20.0, 10.0),
        _game("g2", "1", "10", "20", "2026-06-03T23:00:00+00:00", 20.0, 10.0),
        _game("g3", "1", "10", "20", "2026-06-05T23:00:00+00:00", 20.0, 10.0),
    ])
    built = AF._add_recent_game_counts(AF.build_player_features(history))
    third = built[built.game_id == "g3"].iloc[0]
    assert third["games_prior_7d"] == 2, "target game must not count itself"
    assert built[built.game_id == "g1"].iloc[0]["games_prior_7d"] == 0


# --- built artifact ---------------------------------------------------------

@pytest.fixture(scope="module")
def asof() -> pd.DataFrame:
    path = C.LAB_ROOT / "data" / "features" / "asof_features.parquet"
    if not path.exists():
        pytest.skip("as-of features not built — run replay/asof_features.py")
    return pd.read_parquet(path)


def test_asof_features_unique_by_player_and_game(asof):
    assert asof.duplicated(["player_id", "game_id"]).sum() == 0


def test_asof_features_keep_utc_and_local_date_separate(asof):
    """slate_date_et must be the ET date, not a copy of the UTC date."""
    utc_date = pd.to_datetime(asof["start_utc"], utc=True).dt.date.astype("string")
    et_date = asof["slate_date_et"].astype("string")
    assert (utc_date != et_date).mean() > 0.3, "slate_date_et looks like the UTC date"


def test_asof_features_exclude_preseason(asof):
    assert "preseason" not in set(asof["season_type"])


def test_no_asof_rolling_feature_equals_its_own_target(asof):
    """A last-3 mean matching the target's own value on most rows would mean
    the target had been folded in."""
    subset = asof.dropna(subset=["minutes_last_3", "minutes"])
    identical = np.isclose(subset["minutes_last_3"], subset["minutes"]).mean()
    assert identical < 0.10, f"{identical:.1%} of rows have last-3 minutes equal to actual minutes"


def test_asof_position_is_a_profile_attribute_not_per_game(asof):
    """Documents a known limitation, so it cannot be quietly forgotten.

    The ``position`` embedded in each cached box score is the athlete's *profile*
    position, identical across every game and season (verified: 0 of 419 players
    have more than one). The whole cache was scraped in 2026, so 2024 games carry
    2026 labels. It is therefore an anachronism of the same kind as the
    production roster file — better only in coverage (100% of players vs 20).
    Any position-conditioned feature inherits this and must say so.
    """
    per_player = asof.groupby("player_id")["position"].nunique()
    assert per_player.max() == 1, (
        "positions now vary within a player career — the cache may carry genuine "
        "per-game positions; re-check the limitation recorded in the Phase 2 reports"
    )
    assert asof["position"].notna().mean() > 0.99


# --- regression tests for known findings ------------------------------------

def test_regression_production_game_date_is_utc_not_slate_date():
    """Phase 1 finding. Guards against anyone reintroducing game_date ordering."""
    production = C.PROD_PLAYER_GAMES
    canonical = C.LAB_NORMALIZED / "player_games.parquet"
    if not (production.exists() and canonical.exists()):
        pytest.skip("inputs unavailable")
    prod = pd.read_csv(production, low_memory=False).dropna(subset=["game_id"])
    prod["game_id"] = prod["game_id"].astype("int64").astype(str)
    lab = pd.read_parquet(canonical)[["game_id", "slate_date_et", "start_utc"]].drop_duplicates("game_id")
    merged = prod.merge(lab, on="game_id", how="inner")
    stored = pd.to_datetime(merged["game_date"]).dt.date.astype("string")
    utc = pd.to_datetime(merged["start_utc"], utc=True).dt.date.astype("string")
    assert (stored != merged["slate_date_et"].astype("string")).mean() > 0.3
    assert (stored != utc).mean() < 0.01


def test_regression_phantom_listings_are_excluded():
    """A traded player can appear on two simultaneous box scores with no stat
    line (Celeste Taylor, 2024-08-23). Those rows must not reach features."""
    raw = pd.read_parquet(C.LAB_NORMALIZED / "player_games.parquet")
    phantom = raw[(raw["minutes"].isna()) & (raw["did_not_play"] == 0)]
    assert len(phantom) > 0, "fixture assumption changed: no phantom rows in the cache"
    cleaned = AF.load_player_games()
    overlap = cleaned.merge(phantom[["player_id", "game_id"]], on=["player_id", "game_id"])
    assert overlap.empty


def test_regression_dnp_rows_carry_zero_not_null_stats():
    """A DNP is a real zero. Nulls here would silently drop players from rolling
    windows and inflate their averages."""
    raw = pd.read_parquet(C.LAB_NORMALIZED / "player_games.parquet")
    dnp = raw[raw["did_not_play"] == 1]
    assert len(dnp) > 0
    assert dnp["minutes"].isna().sum() == 0
    assert (dnp["minutes"] == 0).all()
