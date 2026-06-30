"""Probability-quality and betting-performance metrics for the V2 backtest.

All functions are pure and operate on numpy arrays / pandas Series so they can be
reused by the live calibration layer (Phase: calibration) later, not just Phase 0.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Probability-quality metrics
# --------------------------------------------------------------------------- #
def brier_score(y_true: np.ndarray, p_pred: np.ndarray) -> float:
    """Mean squared error of probabilistic forecasts. Lower is better.
    0.25 == always predicting 0.5; below 0.25 means the probabilities add value."""
    y_true = np.asarray(y_true, dtype=float)
    p_pred = np.clip(np.asarray(p_pred, dtype=float), 0.0, 1.0)
    return float(np.mean((p_pred - y_true) ** 2))


def log_loss(y_true: np.ndarray, p_pred: np.ndarray, eps: float = 1e-9) -> float:
    y_true = np.asarray(y_true, dtype=float)
    p = np.clip(np.asarray(p_pred, dtype=float), eps, 1 - eps)
    return float(-np.mean(y_true * np.log(p) + (1 - y_true) * np.log(1 - p)))


def reliability_table(y_true: np.ndarray, p_pred: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """Reliability curve: predicted-prob bin vs realized win rate.

    A well-calibrated model has realized_winrate ~= mean_predicted in every bin.
    """
    y_true = np.asarray(y_true, dtype=float)
    p_pred = np.clip(np.asarray(p_pred, dtype=float), 0.0, 1.0)
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(p_pred, edges, right=False) - 1, 0, bins - 1)
    rows = []
    for b in range(bins):
        mask = idx == b
        n = int(mask.sum())
        if n == 0:
            continue
        rows.append(
            {
                "bin": f"[{edges[b]:.2f},{edges[b + 1]:.2f})",
                "n": n,
                "mean_predicted": float(p_pred[mask].mean()),
                "realized_winrate": float(y_true[mask].mean()),
                "gap": float(p_pred[mask].mean() - y_true[mask].mean()),
            }
        )
    return pd.DataFrame(rows)


def expected_calibration_error(y_true: np.ndarray, p_pred: np.ndarray, bins: int = 10) -> float:
    """Sample-weighted mean |predicted - realized| across reliability bins."""
    tbl = reliability_table(y_true, p_pred, bins)
    if tbl.empty:
        return float("nan")
    w = tbl["n"] / tbl["n"].sum()
    return float((w * tbl["gap"].abs()).sum())


def overconfidence_index(y_true: np.ndarray, p_pred: np.ndarray) -> float:
    """Signed mean(predicted) - mean(realized). >0 means systematically overconfident."""
    return float(np.mean(p_pred) - np.mean(y_true))


# --------------------------------------------------------------------------- #
# Betting-performance metrics
# --------------------------------------------------------------------------- #
def american_to_decimal(odds: float) -> float:
    odds = float(odds)
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / abs(odds))


def roi_flat(y_true: np.ndarray, odds_american: float = -110) -> float:
    """ROI per unit staked, flat-betting at fixed American odds (a -110 proxy).
    Pushes should be removed before calling. Returns profit per unit (e.g. 0.03 = +3%)."""
    y_true = np.asarray(y_true, dtype=float)
    if y_true.size == 0:
        return float("nan")
    dec = american_to_decimal(odds_american)
    profit = np.where(y_true == 1, dec - 1.0, -1.0)
    return float(profit.mean())


@dataclass
class PerfSummary:
    n: int
    wins: int
    losses: int
    pushes: int
    win_rate: float
    roi_minus110: float
    brier: float
    log_loss: float
    ece: float
    overconf: float

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def performance_summary(
    won: np.ndarray, p_pred: np.ndarray, pushes: int = 0, bins: int = 10
) -> PerfSummary:
    won = np.asarray(won, dtype=float)
    p_pred = np.asarray(p_pred, dtype=float)
    wins = int((won == 1).sum())
    losses = int((won == 0).sum())
    n = wins + losses
    return PerfSummary(
        n=n,
        wins=wins,
        losses=losses,
        pushes=int(pushes),
        win_rate=float(wins / n) if n else float("nan"),
        roi_minus110=roi_flat(won, -110),
        brier=brier_score(won, p_pred),
        log_loss=log_loss(won, p_pred),
        ece=expected_calibration_error(won, p_pred, bins),
        overconf=overconfidence_index(won, p_pred),
    )


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a win rate — for significance vs breakeven."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = wins / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = (z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / denom
    return (float(centre - half), float(centre + half))


def beats_breakeven(wins: int, n: int, breakeven: float) -> dict:
    """Is the win rate significantly above breakeven (one-sided, 95%)?"""
    lo, hi = wilson_interval(wins, n)
    wr = wins / n if n else float("nan")
    return {
        "win_rate": wr,
        "ci95_low": lo,
        "ci95_high": hi,
        "breakeven": breakeven,
        "edge_pp": (wr - breakeven) * 100 if n else float("nan"),
        "significant": bool(lo > breakeven) if n else False,
    }
