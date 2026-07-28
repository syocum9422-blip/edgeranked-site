"""Isolation and correctness tests for the WNBA Analytics Lab.

Run:  python3 -m pytest learning/analytics_lab/tests -q     (from sports/wnba)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from analytics_lab.config import lab_config as C  # noqa: E402
from analytics_lab.replay.as_of_state import AsOfState, HistoryStore, LeakageError  # noqa: E402


# --- path guards ------------------------------------------------------------

PRODUCTION_TARGETS = [
    C.WNBA_ROOT / "projections.csv",
    C.WNBA_ROOT / "wnba_best_bets_today.csv",
    C.WNBA_ROOT / "data" / "raw" / "wnba_player_games.csv",
    C.WNBA_ROOT / "data" / "processed" / "wnba_training_dataset.csv",
    C.WNBA_ROOT / "data" / "models" / "wnba_points_model.joblib",
    C.WNBA_ROOT / "models" / "wnba_minutes_model.joblib",
    C.WNBA_ROOT / "outputs" / "archive" / "projections" / "wnba_projections_20260722.csv",
    C.WNBA_ROOT / "Best_Bets" / "graded_bets.csv",
    C.V2_ROOT / "data" / "team_games" / "team_game_logs.csv",
    Path("/home/ubuntu/edgeranked-sportsai/wnba/projections.csv"),
    Path("/home/ubuntu/EdgeRanked/site/app.py"),
]


@pytest.mark.parametrize("target", PRODUCTION_TARGETS, ids=lambda p: Path(p).name)
def test_lab_path_guard_rejects_production(target):
    with pytest.raises(C.LabPathViolation):
        C.assert_lab_path(target)


def test_lab_path_guard_rejects_traversal_escape():
    """A `..` chain out of the lab must be caught after resolution."""
    with pytest.raises(C.LabPathViolation):
        C.assert_lab_path(C.LAB_DATA / ".." / ".." / ".." / "projections.csv")


def test_lab_path_guard_rejects_sibling_learning_artifacts():
    """learning/ holds live canary ledgers; the lab must not write there."""
    with pytest.raises(C.LabPathViolation):
        C.assert_lab_path(C.LEARNING_ROOT / "graded_predictions_ledger.csv")


def test_lab_path_guard_accepts_lab_outputs():
    for parts, root in (
        (("normalized", "x.csv"), C.LAB_DATA),
        (("report.json",), C.LAB_REPORTS),
        (("exp", "manifest.json"), C.LAB_EXPERIMENTS),
    ):
        assert C.is_lab_path(C.assert_lab_path(root.joinpath(*parts)))


def test_write_csv_cannot_escape_lab(tmp_path):
    frame = pd.DataFrame({"a": [1]})
    with pytest.raises(C.LabPathViolation):
        C.write_csv(frame, "..", "..", "escaped.csv")


def test_no_lab_artifact_lives_outside_the_lab():
    """Everything the lab has generated so far must sit under analytics_lab/."""
    generated = list(C.LAB_DATA.rglob("*.csv")) + list(C.LAB_REPORTS.rglob("*"))
    assert generated, "lab has produced no artifacts yet; run the inventory scripts"
    for path in generated:
        if path.is_file():
            assert C.is_lab_path(path), f"{path} escaped the lab"


def test_lab_does_not_import_side_effecting_production_modules():
    """Importing a production pipeline module runs ensure_directories() and, in
    some cases, network fetches. No lab module may do it."""
    forbidden = (
        "simulate_wnba_today", "build_wnba_features_today", "build_wnba_best_bets",
        "fetch_wnba_data", "build_wnba_dataset", "wnba_model_config", "wnba_model_utils",
    )
    offenders = []
    for path in C.LAB_ROOT.rglob("*.py"):
        text = path.read_text()
        for module in forbidden:
            if f"import {module}" in text or f"from {module}" in text:
                offenders.append(f"{path.name} -> {module}")
    assert not offenders, f"lab modules import production pipeline code: {offenders}"


# --- data integrity ---------------------------------------------------------

@pytest.fixture(scope="module")
def game_index() -> pd.DataFrame:
    path = C.LAB_NORMALIZED / "game_index.csv"
    if not path.exists():
        pytest.skip("game index not built — run inventory/build_game_index.py")
    return pd.read_csv(path)


@pytest.fixture(scope="module")
def player_games() -> pd.DataFrame:
    path = C.LAB_NORMALIZED / "player_games_indexed.csv"
    if not path.exists():
        pytest.skip("normalized history not built — run replay/build_history.py")
    return pd.read_csv(path, low_memory=False)


def test_game_index_dates_parse(game_index):
    stamps = pd.to_datetime(game_index["start_utc"], utc=True, errors="coerce")
    assert stamps.isna().sum() == 0
    assert stamps.min().year >= 2024


def test_game_index_has_unique_game_ids(game_index):
    assert game_index["game_id"].duplicated().sum() == 0


def test_every_indexed_game_has_ten_starters(game_index):
    assert (game_index["starters_flagged"] == 10).all()


def test_player_games_have_unique_player_game_keys(player_games):
    assert player_games.duplicated(["player_key", "game_id"]).sum() == 0


def test_player_games_carry_tipoff_timestamps(player_games):
    assert player_games["start_utc"].notna().all()
    assert player_games["slate_date_et"].notna().all()


def test_et_slate_date_differs_from_utc_date_for_evening_games(game_index):
    """Guards the reason the lab keys off tip-off time instead of game_date."""
    assert game_index["date_shifted"].mean() > 0.3


# --- leak-safety ------------------------------------------------------------

def _toy_store() -> HistoryStore:
    players = pd.DataFrame({
        "player_key": ["p1"] * 4 + ["p2"] * 2,
        "game_id": ["g1", "g2", "g3", "g4", "g1", "g2"],
        "start_utc": ["2026-06-01T23:00Z", "2026-06-03T23:00Z",
                      "2026-06-05T23:00Z", "2026-06-07T23:00Z",
                      "2026-06-01T23:00Z", "2026-06-03T23:00Z"],
        "slate_date_et": ["2026-06-01", "2026-06-03", "2026-06-05",
                          "2026-06-07", "2026-06-01", "2026-06-03"],
        "minutes": [30.0, 20.0, 10.0, 40.0, 5.0, 15.0],
        "points": [10.0, 20.0, 30.0, 99.0, 1.0, 2.0],
    })
    teams = players[["game_id", "start_utc", "slate_date_et"]].drop_duplicates()
    return HistoryStore(players, teams)


def test_as_of_state_excludes_the_target_game():
    state = _toy_store().as_of("2026-06-07T23:00Z")
    assert state.player_games["game_id"].tolist().count("g4") == 0
    assert state.player_games["points"].max() == 30.0, "the 99-point target game leaked in"


def test_rolling_mean_excludes_target_and_uses_prior_games_only():
    state = _toy_store().as_of("2026-06-07T23:00Z")
    # p1's three completed games are 10, 20, 30 -> last-3 mean is 20.
    assert state.rolling_mean("points", 3)["p1"] == pytest.approx(20.0)
    # Last-2 mean uses the two most recent completed games (20, 30).
    assert state.rolling_mean("points", 2)["p1"] == pytest.approx(25.0)


def test_as_of_state_rejects_future_rows_at_construction():
    store = _toy_store()
    everything = store.as_of("2026-07-01T00:00Z")
    with pytest.raises(LeakageError):
        AsOfState(
            cutoff=pd.Timestamp("2026-06-02T00:00Z"),
            player_games=everything.player_games,
            team_games=everything.team_games,
        )


def test_cutoff_is_exclusive_at_exact_tipoff():
    """A game starting exactly at the cutoff is in the future, not the past."""
    state = _toy_store().as_of("2026-06-03T23:00Z")
    assert "g2" not in set(state.player_games["game_id"])
    assert set(state.player_games["game_id"]) == {"g1"}


def test_rest_hours_measures_from_previous_tipoff():
    state = _toy_store().as_of("2026-06-07T23:00Z")
    assert state.rest_hours("p1") == pytest.approx(48.0)
    assert state.rest_hours("unknown_player") is None


def test_history_store_refuses_silent_fallback(monkeypatch, tmp_path):
    """Missing normalized history must raise, never fall back to date-only data."""
    monkeypatch.setattr(C, "LAB_NORMALIZED", tmp_path)
    with pytest.raises(FileNotFoundError):
        HistoryStore.from_lab_data()
