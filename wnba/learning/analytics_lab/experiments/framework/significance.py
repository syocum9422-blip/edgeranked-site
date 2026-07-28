"""Statistical comparison of a variant against the baseline.

Baseline and variant are scored on **identical player-games**, so every test
here is paired. Pairing removes the between-player variance that dominates
absolute error and makes a same-sample comparison far more sensitive than two
independent samples would be.

Why significance alone is not enough. With ~14k paired rows per stat, a
difference of 0.005 MAE reaches p < 0.001 while meaning nothing. Every verdict
therefore requires **both** a significant paired test and a practical effect
size, and the thresholds are stated in the report rather than buried here.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from scipy import stats

ALPHA = 0.01                     # per-family, after Holm correction across stats
PRACTICAL_THRESHOLD = 0.01       # 1% relative MAE change to count as meaningful
BOOTSTRAP_SAMPLES = 2000
RANDOM_SEED = 42

MEANINGFUL, MARGINAL, NOT_SIGNIFICANT, REGRESSION = (
    "meaningful", "marginal", "not_significant", "regression")


@dataclass
class PairedResult:
    """One stat's paired comparison. Negative deltas favour the variant."""

    stat: str
    n: int
    baseline_mae: float
    variant_mae: float
    mae_delta: float
    relative_change: float
    ci_low: float
    ci_high: float
    wilcoxon_p: float
    holm_p: float
    cohens_d: float
    variant_win_rate: float
    verdict: str

    def to_dict(self) -> dict:
        return asdict(self)


def _bootstrap_ci(differences: np.ndarray, samples: int = BOOTSTRAP_SAMPLES,
                  alpha: float = 0.05) -> tuple[float, float]:
    """Percentile CI on the mean paired difference in absolute error."""
    rng = np.random.default_rng(RANDOM_SEED)
    n = len(differences)
    if n == 0:
        return float("nan"), float("nan")
    means = differences[rng.integers(0, n, size=(samples, n))].mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def paired_compare(actual: pd.Series, baseline_pred: pd.Series,
                   variant_pred: pd.Series, stat: str) -> PairedResult:
    frame = pd.DataFrame({"a": actual, "b": baseline_pred, "v": variant_pred}).dropna()
    if frame.empty:
        return PairedResult(stat, 0, *[float("nan")] * 9, NOT_SIGNIFICANT)

    baseline_error = (frame["b"] - frame["a"]).abs()
    variant_error = (frame["v"] - frame["a"]).abs()
    differences = (variant_error - baseline_error).to_numpy()

    baseline_mae = float(baseline_error.mean())
    variant_mae = float(variant_error.mean())
    delta = variant_mae - baseline_mae
    relative = delta / baseline_mae if baseline_mae else float("nan")

    # Wilcoxon signed-rank: paired, no normality assumption, and robust to the
    # heavy right tail of absolute errors. Ties are dropped by the test.
    if np.allclose(differences, 0):
        p_value = 1.0
    else:
        try:
            p_value = float(stats.wilcoxon(variant_error, baseline_error,
                                           zero_method="zsplit").pvalue)
        except ValueError:
            p_value = 1.0

    spread = differences.std(ddof=1)
    cohens_d = float(differences.mean() / spread) if spread > 0 else 0.0
    low, high = _bootstrap_ci(differences)
    win_rate = float((variant_error < baseline_error).mean())

    return PairedResult(
        stat=stat, n=int(len(frame)), baseline_mae=baseline_mae, variant_mae=variant_mae,
        mae_delta=delta, relative_change=relative, ci_low=low, ci_high=high,
        wilcoxon_p=p_value, holm_p=float("nan"), cohens_d=cohens_d,
        variant_win_rate=win_rate, verdict=NOT_SIGNIFICANT,
    )


def holm_adjust(results: list[PairedResult]) -> list[PairedResult]:
    """Holm-Bonferroni across the stats tested in one experiment.

    Six stats tested at once is six chances to find a false positive; Holm
    controls the family-wise error rate without the conservatism of plain
    Bonferroni.
    """
    ordered = sorted(range(len(results)), key=lambda i: results[i].wilcoxon_p)
    m = len(results)
    running = 0.0
    for rank, index in enumerate(ordered):
        adjusted = min(1.0, (m - rank) * results[index].wilcoxon_p)
        running = max(running, adjusted)   # enforce monotonicity
        results[index].holm_p = running
    return results


def classify(result: PairedResult, alpha: float = ALPHA,
             threshold: float = PRACTICAL_THRESHOLD) -> str:
    """Four-way verdict requiring both statistical and practical evidence.

    `relative_change` is negative when the variant is better.

    The rule is deliberately **symmetric**. At ~14k paired rows a 0.02% change
    reaches significance, so demoting a variant to `regression` on statistical
    evidence alone would be the same mistake as promoting one — just pointed the
    other way. A verdict of `meaningful` or `regression` therefore needs the
    effect to be both detectable and large enough to care about; anything that
    clears only one bar is `marginal`, and the report states its direction.
    """
    if not np.isfinite(result.holm_p) or result.n == 0:
        return NOT_SIGNIFICANT
    significant = result.holm_p < alpha
    material = abs(result.relative_change) >= threshold
    improved = result.relative_change < 0

    if significant and material:
        return MEANINGFUL if improved else REGRESSION
    if significant or material:
        return MARGINAL
    return NOT_SIGNIFICANT


def compare_all(actual: pd.DataFrame, baseline_pred: pd.DataFrame,
                variant_pred: pd.DataFrame, stats_list: list[str]) -> pd.DataFrame:
    results = [paired_compare(actual[s], baseline_pred[s], variant_pred[s], s)
               for s in stats_list if s in variant_pred.columns]
    results = holm_adjust(results)
    for result in results:
        result.verdict = classify(result)
    return pd.DataFrame([r.to_dict() for r in results])


def pooled_verdict(table: pd.DataFrame) -> dict:
    """Roll the per-stat verdicts into one headline for the leaderboard.

    A regression on any stat dominates: a variant that helps points while
    breaking rebounds is not an improvement.
    """
    if table.empty:
        return {"verdict": NOT_SIGNIFICANT, "pooled_baseline_mae": float("nan"),
                "pooled_variant_mae": float("nan"), "pooled_relative_change": float("nan"),
                "stats_meaningful": 0, "stats_regressed": 0}

    weights = table["n"]
    pooled_baseline = float(np.average(table["baseline_mae"], weights=weights))
    pooled_variant = float(np.average(table["variant_mae"], weights=weights))
    relative = (pooled_variant - pooled_baseline) / pooled_baseline if pooled_baseline else float("nan")

    counts = table["verdict"].value_counts()
    regressed = int(counts.get(REGRESSION, 0))
    meaningful = int(counts.get(MEANINGFUL, 0))
    marginal = int(counts.get(MARGINAL, 0))

    # A stat-level regression now means significant *and* material, so one is
    # enough to sink the variant: helping points while breaking rebounds is not
    # an improvement.
    if regressed:
        verdict = REGRESSION
    elif meaningful and -relative >= PRACTICAL_THRESHOLD:
        verdict = MEANINGFUL
    elif meaningful or marginal:
        verdict = MARGINAL
    else:
        verdict = NOT_SIGNIFICANT

    return {
        "verdict": verdict,
        "direction": "better" if relative < 0 else "worse" if relative > 0 else "unchanged",
        "pooled_baseline_mae": pooled_baseline,
        "pooled_variant_mae": pooled_variant,
        "pooled_relative_change": relative,
        "stats_meaningful": meaningful,
        "stats_marginal": marginal,
        "stats_regressed": regressed,
    }
