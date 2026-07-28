"""Regression tests for every leakage and date-boundary issue found in Phase 2.

Each test pins one finding so a later change cannot quietly undo it or reopen the
underlying defect unnoticed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from analytics_lab.config import lab_config as C  # noqa: E402
from analytics_lab.experiments import archive_integrity as AI  # noqa: E402
from analytics_lab.experiments import production_adapter as PA  # noqa: E402
from analytics_lab.experiments import rolling_staleness as RS  # noqa: E402


@pytest.fixture(scope="module")
def asof() -> pd.DataFrame:
    path = C.LAB_ROOT / "data" / "features" / "asof_features.parquet"
    if not path.exists():
        pytest.skip("as-of features not built")
    return pd.read_parquet(path)


@pytest.fixture(scope="module")
def evaluation() -> pd.DataFrame:
    path = C.LAB_DATA / "baselines" / "model_evaluation.csv"
    if not path.exists():
        pytest.skip("minutes experiment not run")
    return pd.read_csv(path)


@pytest.fixture(scope="module")
def ledger() -> pd.DataFrame:
    path = C.LAB_DATA / "baselines" / "archive_ledger.csv"
    if not path.exists():
        pytest.skip("archive ledger not built")
    return pd.read_csv(path)


# --- date boundaries --------------------------------------------------------

def test_board_game_date_is_et_slate_date_not_utc_date():
    """Production runs two date conventions. Joining the archive to games on the
    UTC date silently finds nothing for an all-evening slate."""
    games = AI.load_games()
    boards = sorted(C.PROD_PROJECTION_ARCHIVE_DIR.glob("wnba_projections_2026*.csv"))
    if not boards:
        pytest.skip("no 2026 archived boards")
    et_hits = utc_hits = 0
    for path in boards[-20:]:
        board = pd.read_csv(path, low_memory=False)
        if "GAME_DATE" not in board.columns:
            continue
        dates = set(pd.to_datetime(board["GAME_DATE"], errors="coerce").dt.date.astype("string"))
        et_hits += games["slate_date_et"].isin(dates).sum() > 0
        utc_hits += games["utc_date"].isin(dates).sum() > 0
    assert et_hits > utc_hits, "board GAME_DATE no longer joins better on the ET slate date"


def test_production_actuals_game_date_is_utc_date():
    """The other half of the same finding, pinned separately."""
    if not C.PROD_PLAYER_GAMES.exists():
        pytest.skip("production actuals unavailable")
    prod = pd.read_csv(C.PROD_PLAYER_GAMES, low_memory=False).dropna(subset=["game_id"])
    prod["game_id"] = prod["game_id"].astype("int64").astype(str)
    lab = pd.read_parquet(C.LAB_NORMALIZED / "player_games.parquet")
    lab = lab[["game_id", "slate_date_et", "start_utc"]].drop_duplicates("game_id")
    merged = prod.merge(lab, on="game_id", how="inner")
    stored = pd.to_datetime(merged["game_date"]).dt.date.astype("string")
    utc = pd.to_datetime(merged["start_utc"], utc=True).dt.date.astype("string")
    assert (stored != utc).mean() < 0.01
    assert (stored != merged["slate_date_et"].astype("string")).mean() > 0.3


def test_utc_date_grouping_creates_duplicate_player_dates():
    """The concrete damage: mixing an afternoon and an evening ET slate onto one
    UTC date makes a team look like it played twice."""
    if not C.PROD_PLAYER_GAMES.exists():
        pytest.skip("production actuals unavailable")
    prod = pd.read_csv(C.PROD_PLAYER_GAMES, low_memory=False)
    duplicates = prod.duplicated(["player_key", "game_date"]).sum()
    assert duplicates > 0, "fixture assumption changed"
    lab = pd.read_parquet(C.LAB_NORMALIZED / "player_games.parquet")
    assert lab.duplicated(["player_id", "slate_date_et"]).sum() < duplicates


# --- minutes leakage --------------------------------------------------------

def test_minutes_is_still_in_the_production_feature_list():
    """If this ever fails, the leak was fixed upstream and the audit's framing
    must be revisited rather than left stale."""
    models = PA.load_stat_models()
    if not models:
        pytest.skip("production stat models unavailable")
    for stat, bundle in models.items():
        assert "minutes" in bundle["feature_list"], f"{stat} no longer consumes `minutes`"


def test_minutes_model_does_not_consume_minutes():
    """Variant D is only leak-safe because of this."""
    bundle = PA.load_minutes_model()
    if bundle is None:
        pytest.skip("minutes model unavailable")
    assert "minutes" not in bundle["feature_list"]


def test_leaked_minutes_variant_beats_every_leak_safe_variant(evaluation):
    """Confirms the diagnostic is doing its job: if the leaked variant were not
    the most accurate, the feature would not be carrying target information."""
    overall = evaluation[evaluation.segment == "ALL"]
    pooled = overall.groupby("variant").apply(
        lambda g: float(np.average(g["mae"], weights=g["n"])), include_groups=False
    )
    leaked = pooled["A_LEAKED_ACTUAL_MINUTES"]
    assert leaked == pooled.min(), "leaked variant is no longer the most accurate"
    assert pooled.drop("A_LEAKED_ACTUAL_MINUTES").min() > leaked


def test_shipped_minutes_behaviour_is_worse_than_leak_safe_alternatives(evaluation):
    """Previous-game actual minutes — what production serves — must remain the
    weakest option, or the P1 recommendation no longer holds."""
    overall = evaluation[evaluation.segment == "ALL"]
    pooled = overall.groupby("variant").apply(
        lambda g: float(np.average(g["mae"], weights=g["n"])), include_groups=False
    )
    assert pooled["B_PREVIOUS_GAME_MINUTES"] == pooled.max()


def test_every_variant_scored_on_identical_rows(evaluation):
    """A metric difference is only attributable to the knob if the rows match."""
    overall = evaluation[evaluation.segment == "ALL"]
    counts = overall.groupby("variant")["n"].apply(tuple)
    assert counts.nunique() == 1, "variants were scored on different row sets"


# --- staleness --------------------------------------------------------------

def test_stale_features_are_one_more_shift_than_fresh(asof):
    """Pins the reconstruction of production behaviour itself."""
    sample = asof[asof.player_id == asof.player_id.value_counts().idxmax()].copy()
    sample = sample.sort_values("start_utc")
    stale = RS.build_stale_features(sample)
    fresh_values = sample["minutes_last_3"].to_numpy()
    stale_values = stale["minutes_last_3"].to_numpy()
    assert np.allclose(stale_values[1:], fresh_values[:-1], equal_nan=True)
    assert pd.isna(stale_values[0])


def test_stale_features_never_beat_fresh_on_pooled_error():
    """Discarding the most recent completed game cannot help on average."""
    path = C.LAB_REPORTS / "staleness_metrics.csv"
    if not path.exists():
        pytest.skip("staleness experiment not run")
    metrics = pd.read_csv(path)
    pivot = metrics.pivot_table(index="stat", columns="features", values="mae")
    weights = metrics[metrics.features == "fresh"].set_index("stat")["n"]
    pooled_fresh = float(np.average(pivot["fresh"], weights=weights[pivot.index]))
    pooled_stale = float(np.average(pivot["stale"], weights=weights[pivot.index]))
    assert pooled_stale >= pooled_fresh


# --- team context -----------------------------------------------------------

def test_production_team_context_pace_is_dead_after_the_outage_date():
    if not C.PROD_TEAM_CONTEXT.exists():
        pytest.skip("production team context unavailable")
    frame = pd.read_csv(C.PROD_TEAM_CONTEXT, low_memory=False)
    frame["game_date"] = pd.to_datetime(frame["game_date"])
    after = frame[frame["game_date"] > pd.Timestamp("2026-06-28")]
    assert len(after) > 0
    assert after["pace"].notna().sum() == 0, "pace feed appears to have been repaired"


def test_reconstructed_team_context_has_full_coverage():
    path = C.LAB_NORMALIZED / "team_context_reconstructed.csv"
    if not path.exists():
        pytest.skip("team context not reconstructed")
    frame = pd.read_csv(path)
    for column in ("pace", "off_rating", "def_rating"):
        assert frame[column].notna().mean() > 0.99


def test_reconstructed_team_context_agrees_with_healthy_production():
    path = C.LAB_REPORTS / "team_context_comparison.csv"
    if not path.exists():
        pytest.skip("comparison not built")
    comparison = pd.read_csv(path)
    assert len(comparison) == 3
    assert (comparison["correlation"] > 0.95).all()


def test_team_context_rolling_excludes_the_target_game():
    path = C.LAB_NORMALIZED / "team_context_reconstructed.csv"
    if not path.exists():
        pytest.skip("team context not reconstructed")
    frame = pd.read_csv(path).sort_values(["team_id", "start_utc"])
    openers = frame[frame["season_opener"] == 1]
    assert len(openers) > 0
    assert openers["pace_last_10"].isna().all(), "a season opener has prior-form values"


# --- archive integrity ------------------------------------------------------

def test_archive_ledger_classifies_every_artifact(ledger):
    valid = {AI.CLEAN, AI.PARTIAL, AI.POSTGAME, AI.UNKNOWN_TS, AI.MISMATCH, AI.INVALID}
    assert set(ledger["classification"]) <= valid
    assert ledger["classification"].isna().sum() == 0


def test_clean_pregame_artifacts_precede_every_represented_tip(ledger):
    clean = ledger[ledger.classification == AI.CLEAN]
    assert len(clean) > 0
    assert (clean["games_tipped_before_creation"] == 0).all()
    assert clean["created_before_every_tip"].all()


def test_not_all_archived_boards_are_clean(ledger):
    """Guards against a future change that classifies everything CLEAN and
    quietly readmits post-tip rebuilds to the exact-snapshot baseline."""
    assert (ledger["classification"] != AI.CLEAN).sum() > 0


def test_partial_artifacts_have_at_least_one_tipped_game(ledger):
    partial = ledger[ledger.classification == AI.PARTIAL]
    if partial.empty:
        pytest.skip("no partial artifacts")
    assert (partial["games_tipped_before_creation"] >= 1).all()


# --- data quality -----------------------------------------------------------

def test_preseason_present_in_production_history_but_unlabelled():
    """Production cannot filter preseason out; the lab must keep doing it."""
    lab = pd.read_parquet(C.LAB_NORMALIZED / "player_games.parquet")
    preseason_ids = set(lab.loc[lab.season_type == "preseason", "game_id"])
    assert len(preseason_ids) > 0
    if not C.PROD_PLAYER_GAMES.exists():
        pytest.skip("production actuals unavailable")
    prod = pd.read_csv(C.PROD_PLAYER_GAMES, low_memory=False).dropna(subset=["game_id"])
    prod_ids = set(prod["game_id"].astype("int64").astype(str))
    assert preseason_ids & prod_ids, "preseason no longer reaches production history"
    assert "season_type" not in prod.columns, "production gained a season_type column"


def test_canonical_history_reaches_the_latest_cached_game():
    """Pins the Phase 2A gap closure so a stale intermediate cannot creep back."""
    lab = pd.read_parquet(C.LAB_NORMALIZED / "player_games.parquet")
    assert lab["slate_date_et"].max() >= "2026-07-22"
    assert len(lab) > 18000
