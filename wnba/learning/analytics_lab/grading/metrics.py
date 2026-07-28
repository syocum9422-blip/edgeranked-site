"""Grading metrics for WNBA projections.

Point projections get error metrics; only genuinely probabilistic outputs get
probabilistic metrics. The production stat models emit point projections plus
simulated percentiles, so log loss and Brier apply to the simulator's
over/under probabilities, not to the point projections themselves.

Betting profit is deliberately absent as an objective. It is a downstream
consequence of accuracy and selection, and optimizing it directly rewards
variance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TOLERANCES = (1.0, 2.0)


def point_metrics(actual: pd.Series, projected: pd.Series) -> dict:
    """Error metrics for a single stat category."""
    frame = pd.DataFrame({"a": actual, "p": projected}).dropna()
    if frame.empty:
        return {"n": 0}
    error = frame["p"] - frame["a"]
    result = {
        "n": int(len(frame)),
        "mae": float(error.abs().mean()),
        "rmse": float(np.sqrt((error ** 2).mean())),
        "bias": float(error.mean()),
        "median_abs_error": float(error.abs().median()),
        "actual_mean": float(frame["a"].mean()),
        "projected_mean": float(frame["p"].mean()),
    }
    for tolerance in TOLERANCES:
        result[f"within_{tolerance:g}"] = float((error.abs() <= tolerance).mean())
    # Correlation is undefined when either side is constant.
    result["correlation"] = (
        float(frame["a"].corr(frame["p"]))
        if frame["a"].nunique() > 1 and frame["p"].nunique() > 1 else float("nan")
    )
    # Normalized MAE makes categories with different scales comparable.
    result["normalized_mae"] = (
        result["mae"] / result["actual_mean"] if result["actual_mean"] else float("nan")
    )
    return result


def calibration_by_bucket(actual: pd.Series, projected: pd.Series, bins: int = 10) -> pd.DataFrame:
    """Mean actual vs mean projected within projection-value buckets.

    A well-calibrated projection sits on the diagonal: the players it projects
    for 18 points should average about 18.
    """
    frame = pd.DataFrame({"a": actual, "p": projected}).dropna()
    if frame.empty:
        return pd.DataFrame()
    frame["bucket"] = pd.qcut(frame["p"], min(bins, frame["p"].nunique()), duplicates="drop")
    grouped = frame.groupby("bucket", observed=True).agg(
        n=("a", "size"), projected_mean=("p", "mean"), actual_mean=("a", "mean")
    ).reset_index()
    grouped["bias"] = grouped["projected_mean"] - grouped["actual_mean"]
    return grouped


def segment_metrics(frame: pd.DataFrame, by: str, actual_col: str = "actual",
                    projected_col: str = "projection") -> pd.DataFrame:
    """Error broken out by a segment column (role, team, rest, season, ...)."""
    if by not in frame.columns:
        return pd.DataFrame()
    rows = []
    for value, group in frame.groupby(by, observed=True):
        rows.append({by: value, **point_metrics(group[actual_col], group[projected_col])})
    return pd.DataFrame(rows).sort_values("n", ascending=False)


def top_n_metrics(frame: pd.DataFrame, n_values: tuple[int, ...] = (5, 10, 20),
                  actual_col: str = "actual", projected_col: str = "projection",
                  group_col: str = "slate_date_et") -> pd.DataFrame:
    """Accuracy among the highest-projected players on each slate.

    These are the rows a user actually reads, so they deserve their own metric
    rather than being averaged into the pool.
    """
    rows = []
    for n in n_values:
        picked = (frame.sort_values(projected_col, ascending=False)
                       .groupby(group_col, observed=True).head(n))
        rows.append({"top_n": n, **point_metrics(picked[actual_col], picked[projected_col])})
    return pd.DataFrame(rows)


def disagreement_metrics(frame: pd.DataFrame, candidate_col: str, baseline_col: str,
                         actual_col: str = "actual", threshold: float = 2.0) -> dict:
    """How the candidate fares where it most disagrees with the baseline.

    Agreement rows carry no information about which model is better; the
    disagreements are the whole test.
    """
    subset = frame.dropna(subset=[candidate_col, baseline_col, actual_col])
    gap = (subset[candidate_col] - subset[baseline_col]).abs()
    subset = subset[gap >= threshold]
    if subset.empty:
        return {"n": 0, "threshold": threshold}
    candidate = point_metrics(subset[actual_col], subset[candidate_col])
    baseline = point_metrics(subset[actual_col], subset[baseline_col])
    return {
        "n": int(len(subset)), "threshold": threshold,
        "candidate_mae": candidate["mae"], "baseline_mae": baseline["mae"],
        "mae_delta": candidate["mae"] - baseline["mae"],
        "candidate_wins": float((
            (subset[candidate_col] - subset[actual_col]).abs()
            < (subset[baseline_col] - subset[actual_col]).abs()
        ).mean()),
    }


# --- probabilistic outputs only ---------------------------------------------

def log_loss(probability: pd.Series, outcome: pd.Series, eps: float = 1e-9) -> float:
    frame = pd.DataFrame({"p": probability, "y": outcome}).dropna()
    if frame.empty:
        return float("nan")
    p = frame["p"].clip(eps, 1 - eps)
    return float(-(frame["y"] * np.log(p) + (1 - frame["y"]) * np.log(1 - p)).mean())


def brier_score(probability: pd.Series, outcome: pd.Series) -> float:
    frame = pd.DataFrame({"p": probability, "y": outcome}).dropna()
    if frame.empty:
        return float("nan")
    return float(((frame["p"] - frame["y"]) ** 2).mean())


def reliability_curve(probability: pd.Series, outcome: pd.Series, bins: int = 10) -> pd.DataFrame:
    frame = pd.DataFrame({"p": probability, "y": outcome}).dropna()
    if frame.empty:
        return pd.DataFrame()
    frame["bucket"] = pd.cut(frame["p"], np.linspace(0, 1, bins + 1), include_lowest=True)
    curve = frame.groupby("bucket", observed=True).agg(
        n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean")
    ).reset_index()
    curve["gap"] = curve["predicted"] - curve["observed"]
    return curve
