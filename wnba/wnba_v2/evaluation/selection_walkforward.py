"""Phase 0b — Walk-forward confirmation of the selection edge.

The baseline found that high z-edge (|proj-line|/stddev) plays hit ~61-66% IN-SAMPLE.
That number is untrustworthy until it survives out-of-sample. This module replays
the season day-by-day: each day we choose a selection rule using ONLY past graded
results, then apply it to that day's bets and bank the realized outcome. No peeking.

Strategies compared (all OOS):
  - full_book        : bet everything (the live baseline, ~53.8%)
  - zedge_wf         : each day, pick the z-edge threshold that maximized past ROI
  - calib_prob_wf    : isotonic-recalibrate past probs, bet today's calibrated p >= breakeven
  - combined_wf      : calibrated p >= breakeven AND z-edge above its learned threshold

Run:  .venv/bin/python -m wnba_v2.evaluation.selection_walkforward
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from wnba_v2 import config as C
from wnba_v2.evaluation import metrics as M
from wnba_v2.evaluation.backtest import graded_only, load_graded

OUT = C.BASELINE_DIR
BURN_IN_DAYS = 14            # initial history before we start selecting
MIN_HIST_BETS = 60          # need this many past graded bets to fit a rule
MIN_KEEP_FRAC = 0.10        # threshold must retain at least this share of past bets


def _best_zedge_threshold(hist: pd.DataFrame) -> float:
    """Threshold on z_edge that maximized ROI@-110 on history, with a volume guard."""
    h = hist[hist["z_edge"].notna()]
    if len(h) < MIN_HIST_BETS:
        return -np.inf
    cands = np.quantile(h["z_edge"], np.linspace(0.3, 0.9, 13))
    best_t, best_roi = -np.inf, -np.inf
    for t in cands:
        kept = h[h["z_edge"] >= t]
        if len(kept) < max(MIN_HIST_BETS * MIN_KEEP_FRAC, 20):
            continue
        roi = M.roi_flat(kept["won"].values, -110)
        if roi > best_roi:
            best_roi, best_t = roi, t
    return best_t


def _fit_calibrator(hist: pd.DataFrame) -> IsotonicRegression | None:
    h = hist[hist["p_pred"].notna()]
    if len(h) < MIN_HIST_BETS or h["won"].nunique() < 2:
        return None
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(h["p_pred"].values, h["won"].values)
    return iso


def walk_forward(df: pd.DataFrame) -> dict:
    df = graded_only(df).sort_values("date").copy()
    df = df[df["date"].notna()]
    days = sorted(df["date"].dt.normalize().unique())
    if len(days) <= BURN_IN_DAYS:
        return {"error": "not enough days"}

    picks = {k: [] for k in ["full_book", "zedge_wf", "calib_prob_wf", "combined_wf"]}
    for d in days[BURN_IN_DAYS:]:
        hist = df[df["date"].dt.normalize() < d]
        today = df[df["date"].dt.normalize() == d]
        if today.empty:
            continue

        picks["full_book"].append(today)

        t = _best_zedge_threshold(hist)
        if np.isfinite(t):
            picks["zedge_wf"].append(today[today["z_edge"] >= t])

        iso = _fit_calibrator(hist)
        if iso is not None:
            cp = iso.predict(today["p_pred"].fillna(0.5).values)
            today = today.assign(calib_p=cp)
            picks["calib_prob_wf"].append(today[today["calib_p"] >= C.BREAKEVEN_MINUS_110])
            if np.isfinite(t):
                picks["combined_wf"].append(
                    today[(today["calib_p"] >= C.BREAKEVEN_MINUS_110) & (today["z_edge"] >= t)]
                )

    results = {}
    for name, frames in picks.items():
        if not frames:
            continue
        sel = pd.concat(frames)
        if sel.empty:
            continue
        won, n = sel["won"], len(sel)
        wins = int(won.sum())
        bt = M.beats_breakeven(wins, n, C.BREAKEVEN_MINUS_110)
        results[name] = {
            "n_bets": n,
            "win_rate": round(float(won.mean()), 4),
            "roi_minus110": round(M.roi_flat(won.values, -110), 4),
            "ci95": [round(bt["ci95_low"], 4), round(bt["ci95_high"], 4)],
            "edge_pp_vs_-110": round(bt["edge_pp"], 2),
            "significant_vs_-110": bt["significant"],
        }
    return results


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    res = walk_forward(load_graded())
    (OUT / "selection_walkforward.json").write_text(json.dumps(res, indent=2, default=str))
    return res


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=2, default=str))
    base = r.get("full_book", {}).get("win_rate")
    print("\n--- VERDICT ---")
    for k, v in r.items():
        if k == "full_book":
            continue
        delta = (v["win_rate"] - base) * 100 if base else float("nan")
        flag = "CONFIRMED" if v["significant_vs_-110"] else "not significant"
        print(f"{k:16s} {v['win_rate']:.4f} ({delta:+.2f}pp vs full book, n={v['n_bets']}) -> {flag}")
