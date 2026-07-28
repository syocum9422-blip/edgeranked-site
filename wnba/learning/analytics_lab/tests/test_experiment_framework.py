"""Phase 3 — tests for the experiment framework.

The framework's whole value is that its guarantees hold automatically: identical
samples, one variable per experiment, a verdict that needs both statistical and
practical evidence, and no path to production. Each is pinned here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from analytics_lab.config import lab_config as C  # noqa: E402
from analytics_lab.experiments.framework import baseline as BL  # noqa: E402
from analytics_lab.experiments.framework import registry, significance  # noqa: E402
from analytics_lab.experiments.framework.base import (  # noqa: E402
    Experiment, ExperimentContext, SingleVariableViolation,
    assert_single_variable, changed_columns,
)
from analytics_lab.experiments.framework.manifest import ExperimentManifest  # noqa: E402


# --- manifest ---------------------------------------------------------------

def test_manifest_rejects_unknown_status():
    with pytest.raises(ValueError):
        ExperimentManifest(experiment_id="X", title="t", question="does this work at all?",
                           hypothesis="h", features_modified=["a"],
                           expected_improvement="e", status="deployed")


def test_manifest_requires_a_modified_feature():
    with pytest.raises(ValueError):
        ExperimentManifest(experiment_id="X", title="t", question="does this work at all?",
                           hypothesis="h", features_modified=[], expected_improvement="e")


def test_manifest_rejects_a_label_masquerading_as_a_question():
    with pytest.raises(ValueError):
        ExperimentManifest(experiment_id="X", title="t", question="minutes",
                           hypothesis="h", features_modified=["a"], expected_improvement="e")


def test_manifest_round_trips(tmp_path):
    manifest = ExperimentManifest(
        experiment_id="X", title="t", question="does this round trip correctly?",
        hypothesis="h", features_modified=["a"], expected_improvement="e")
    path = manifest.write(tmp_path / "manifest.json")
    assert ExperimentManifest.read(path).to_dict() == manifest.to_dict()


# --- single-variable guard --------------------------------------------------

@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame({
        "minutes": [10.0, 20.0, 30.0],
        "rest_days": [1.0, 2.0, 3.0],
        "team": ["A", "B", "C"],
        "nullable": [1.0, np.nan, 3.0],
    })


def test_changed_columns_detects_a_numeric_change(frame):
    variant = frame.copy()
    variant.loc[0, "minutes"] = 11.0
    assert changed_columns(frame, variant) == ["minutes"]


def test_changed_columns_detects_a_categorical_change(frame):
    variant = frame.copy()
    variant.loc[0, "team"] = "Z"
    assert changed_columns(frame, variant) == ["team"]


def test_changed_columns_treats_nan_equal_to_nan(frame):
    assert changed_columns(frame, frame.copy()) == []


def test_changed_columns_detects_nulling_a_value(frame):
    """Ablation by nulling must register as a change, not slip through."""
    variant = frame.copy()
    variant.loc[0, "minutes"] = np.nan
    assert "minutes" in changed_columns(frame, variant)


def test_changed_columns_detects_filling_a_null(frame):
    variant = frame.copy()
    variant.loc[1, "nullable"] = 2.0
    assert "nullable" in changed_columns(frame, variant)


def test_undeclared_column_change_aborts_the_run(frame):
    variant = frame.copy()
    variant["minutes"] = variant["minutes"] + 1
    variant["rest_days"] = variant["rest_days"] + 1
    with pytest.raises(SingleVariableViolation, match="rest_days"):
        assert_single_variable(frame, variant, declared=["minutes"])


def test_declared_change_is_accepted(frame):
    variant = frame.copy()
    variant["minutes"] = variant["minutes"] + 1
    assert assert_single_variable(frame, variant, declared=["minutes"]) == ["minutes"]


def test_declaring_more_than_changed_is_allowed(frame):
    """A variant may leave a declared column untouched on a given sample."""
    variant = frame.copy()
    variant["minutes"] = variant["minutes"] + 1
    assert assert_single_variable(frame, variant, declared=["minutes", "rest_days"]) == ["minutes"]


def test_row_count_change_aborts_the_run(frame):
    with pytest.raises(SingleVariableViolation, match="identical player-games"):
        assert_single_variable(frame, frame.iloc[:2].copy(), declared=["minutes"])


def test_schema_change_aborts_the_run(frame):
    variant = frame.copy().drop(columns=["team"])
    with pytest.raises(SingleVariableViolation):
        assert_single_variable(frame, variant, declared=["minutes"])


# --- significance -----------------------------------------------------------

def _series(values) -> pd.Series:
    return pd.Series(values, dtype=float)


def test_identical_predictions_are_not_significant():
    rng = np.random.default_rng(0)
    actual = _series(rng.normal(15, 5, 500))
    prediction = actual + rng.normal(0, 3, 500)
    result = significance.paired_compare(actual, prediction, prediction.copy(), "points")
    assert result.mae_delta == pytest.approx(0.0)
    assert significance.classify(significance.holm_adjust([result])[0]) == significance.NOT_SIGNIFICANT


def test_a_tiny_but_significant_change_is_marginal_not_meaningful():
    """The whole point of the practical threshold: n makes anything significant."""
    rng = np.random.default_rng(1)
    actual = _series(rng.normal(15, 5, 20_000))
    baseline = actual + rng.normal(0, 3, 20_000)
    variant = baseline - 0.001 * np.sign(baseline - actual)   # 0.001 better, everywhere
    result = significance.holm_adjust(
        [significance.paired_compare(actual, baseline, variant, "points")])[0]
    assert result.holm_p < significance.ALPHA, "expected significance at this n"
    assert abs(result.relative_change) < significance.PRACTICAL_THRESHOLD
    assert significance.classify(result) == significance.MARGINAL


def test_a_large_significant_improvement_is_meaningful():
    rng = np.random.default_rng(2)
    actual = _series(rng.normal(15, 5, 3_000))
    baseline = actual + rng.normal(0, 4, 3_000)
    variant = actual + rng.normal(0, 2, 3_000)
    result = significance.holm_adjust(
        [significance.paired_compare(actual, baseline, variant, "points")])[0]
    assert significance.classify(result) == significance.MEANINGFUL
    assert result.relative_change < 0


def test_a_large_significant_degradation_is_a_regression():
    rng = np.random.default_rng(3)
    actual = _series(rng.normal(15, 5, 3_000))
    baseline = actual + rng.normal(0, 2, 3_000)
    variant = actual + rng.normal(0, 5, 3_000)
    result = significance.holm_adjust(
        [significance.paired_compare(actual, baseline, variant, "points")])[0]
    assert significance.classify(result) == significance.REGRESSION


def test_verdict_rule_is_symmetric():
    """A tiny significant *worsening* must not be called a regression, for the
    same reason a tiny significant improvement is not called meaningful."""
    better = significance.PairedResult(
        stat="s", n=10_000, baseline_mae=1.0, variant_mae=0.999, mae_delta=-0.001,
        relative_change=-0.001, ci_low=-0.002, ci_high=-0.0005, wilcoxon_p=1e-9,
        holm_p=1e-9, cohens_d=-0.1, variant_win_rate=0.55, verdict="")
    worse = significance.PairedResult(
        stat="s", n=10_000, baseline_mae=1.0, variant_mae=1.001, mae_delta=0.001,
        relative_change=0.001, ci_low=0.0005, ci_high=0.002, wilcoxon_p=1e-9,
        holm_p=1e-9, cohens_d=0.1, variant_win_rate=0.45, verdict="")
    assert significance.classify(better) == significance.MARGINAL
    assert significance.classify(worse) == significance.MARGINAL


def test_holm_correction_is_monotone_and_raises_p_values():
    results = []
    for index, p in enumerate([0.001, 0.02, 0.04, 0.5]):
        results.append(significance.PairedResult(
            stat=f"s{index}", n=100, baseline_mae=1.0, variant_mae=1.0, mae_delta=0.0,
            relative_change=0.0, ci_low=0.0, ci_high=0.0, wilcoxon_p=p, holm_p=float("nan"),
            cohens_d=0.0, variant_win_rate=0.5, verdict=""))
    adjusted = significance.holm_adjust(results)
    values = [r.holm_p for r in sorted(adjusted, key=lambda r: r.wilcoxon_p)]
    assert values == sorted(values), "Holm p-values must be monotone in raw p"
    assert all(a.holm_p >= a.wilcoxon_p for a in adjusted)


def test_one_stat_regression_sinks_the_pooled_verdict():
    """Helping points while breaking rebounds is not an improvement."""
    table = pd.DataFrame([
        {"stat": "points", "n": 1000, "baseline_mae": 1.0, "variant_mae": 0.9,
         "verdict": significance.MEANINGFUL},
        {"stat": "rebounds", "n": 1000, "baseline_mae": 1.0, "variant_mae": 1.2,
         "verdict": significance.REGRESSION},
    ])
    assert significance.pooled_verdict(table)["verdict"] == significance.REGRESSION


# --- registry ---------------------------------------------------------------

def test_registry_discovers_the_expected_experiments():
    catalog = registry.discover()
    assert set(catalog) >= {"EXP001", "EXP002", "EXP003", "EXP004", "EXP005"}


def test_every_registered_experiment_satisfies_the_contract():
    for experiment_id, experiment in registry.discover().items():
        assert isinstance(experiment, Experiment)
        manifest = experiment.manifest
        assert manifest.experiment_id == experiment_id
        assert manifest.features_modified
        assert manifest.hypothesis and manifest.expected_improvement
        assert manifest.baseline_kind == "reconstructed_production_logic"


def test_unknown_experiment_id_raises():
    with pytest.raises(KeyError):
        registry.get("EXP999")


def test_runner_does_not_import_any_experiment_by_name():
    """The runner must stay generic; experiments reach it only via the registry.

    Checked against import statements rather than raw text, so a CLI help string
    that mentions an id as an example does not trip the guard.
    """
    import ast

    for module in ("runner.py", "reporting.py", "significance.py", "baseline.py"):
        tree = ast.parse((C.LAB_EXPERIMENTS / "framework" / module).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "catalog" not in node.module, f"{module} imports {node.module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert "catalog" not in alias.name, f"{module} imports {alias.name}"


# --- isolation --------------------------------------------------------------

def test_framework_writes_only_inside_the_lab():
    for path in (C.LAB_EXPERIMENTS / "runs").rglob("*"):
        if path.is_file():
            assert C.is_lab_path(path), f"{path} escaped the lab"
    for path in (C.LAB_REPORTS / "experiments").rglob("*"):
        if path.is_file():
            assert C.is_lab_path(path)


def test_framework_never_writes_a_model_binary():
    """Nothing in the framework may call joblib.dump or fit a production model."""
    for path in (C.LAB_EXPERIMENTS).rglob("*.py"):
        source = path.read_text()
        assert "joblib.dump" not in source, f"{path.name} writes a model artifact"
        assert ".fit(" not in source, f"{path.name} trains a model"


# --- baseline ---------------------------------------------------------------

@pytest.fixture(scope="module")
def built_baseline():
    path = C.LAB_ROOT / "data" / "features" / "asof_features.parquet"
    if not path.exists():
        pytest.skip("as-of features not built")
    return BL.build_baseline()


def test_baseline_reproduces_production_minutes_behaviour(built_baseline):
    """Baseline `minutes` must be the previous game's actual minutes."""
    assert np.allclose(built_baseline.frame["minutes"],
                       built_baseline.rows["prev_game_minutes"], equal_nan=True)


def test_baseline_uses_production_rest_day_construction(built_baseline):
    """UTC-date differenced, minus one, clipped to 0-7 — including the clip."""
    rest = built_baseline.frame["rest_days"]
    assert rest.min() >= 0 and rest.max() <= 7
    exact = np.floor(built_baseline.rows["rest_hours"] / 24.0)
    assert (rest.to_numpy() != exact.clip(0, 7).to_numpy()).mean() > 0.1, (
        "baseline rest looks identical to the exact construction; it should differ "
        "because production differences UTC dates"
    )


def test_baseline_rows_are_regular_season_and_played(built_baseline):
    assert (built_baseline.rows["played"] == 1).all()
    assert (built_baseline.rows["season_type"] == "regular").all()


def test_baseline_is_deterministic():
    """Two builds must give the same rows and predictions, or paired comparison
    across separately-run experiments is invalid."""
    if not (C.LAB_ROOT / "data" / "features" / "asof_features.parquet").exists():
        pytest.skip("as-of features not built")
    first, second = BL.build_baseline(), BL.build_baseline()
    assert first.rows.index.equals(second.rows.index)
    assert np.allclose(first.predictions.to_numpy(), second.predictions.to_numpy())
    assert first.model_fingerprint == second.model_fingerprint


# --- persisted results ------------------------------------------------------

@pytest.fixture(scope="module")
def runs() -> dict[str, pd.DataFrame]:
    root = C.LAB_EXPERIMENTS / "runs"
    if not root.exists():
        pytest.skip("no experiment runs on disk")
    return {p.name: pd.read_csv(p / "per_stat.csv")
            for p in sorted(root.iterdir()) if (p / "per_stat.csv").exists()}


def test_all_experiments_scored_on_the_same_sample(runs):
    """The central guarantee: never compare different samples."""
    if len(runs) < 2:
        pytest.skip("need at least two runs")
    signatures = {name: tuple(frame.sort_values("stat")["n"]) for name, frame in runs.items()}
    assert len(set(signatures.values())) == 1, f"sample sizes diverged: {signatures}"


def test_all_experiments_share_one_baseline(runs):
    if len(runs) < 2:
        pytest.skip("need at least two runs")
    baselines = {name: tuple(frame.sort_values("stat")["baseline_mae"].round(6))
                 for name, frame in runs.items()}
    assert len(set(baselines.values())) == 1, "baseline MAE differs between experiments"


def test_every_run_records_a_verdict_and_holm_p(runs):
    for name, frame in runs.items():
        assert frame["verdict"].notna().all(), name
        assert frame["holm_p"].notna().all(), name
        assert (frame["holm_p"] >= frame["wilcoxon_p"] - 1e-12).all(), name
