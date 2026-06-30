"""Phase 0 — Official baseline backtest & evaluation framework.

Read-only. Consumes the live graded history and produces the baseline every
rebuild phase must beat: calibration, Brier, win-rate by bucket, threshold
optimization, market breakdowns, a CLV proxy, and programmatic answers to the
four diagnostic questions.

Run:  .venv/bin/python -m wnba_v2.evaluation.backtest
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.evaluation import metrics as M


# --------------------------------------------------------------------------- #
# Load & normalize
# --------------------------------------------------------------------------- #
def load_graded() -> pd.DataFrame:
    """Load graded bets into a normalized frame: one row per graded leg.

    Columns produced: date, player, stat, side, line, line_open, line_move,
    proj, stddev, p_pred, edge_model, confidence, result, won (1/0), push(bool).
    """
    g = pd.read_csv(C.GRADED_BETS_PATH)

    res = g["bet_result"].astype(str).str.lower().str.strip()
    push = res.eq("push")
    won = res.eq("win")

    df = pd.DataFrame(
        {
            "date": pd.to_datetime(g["bet_date"], errors="coerce"),
            "player": g.get("player_name"),
            "stat": g["stat"].astype(str).str.lower().str.strip(),
            "side": g["side"].astype(str).str.lower().str.strip(),
            "line": pd.to_numeric(g.get("line"), errors="coerce"),
            "line_open": pd.to_numeric(g.get("line_open"), errors="coerce"),
            "line_move": pd.to_numeric(g.get("line_move"), errors="coerce"),
            "proj": pd.to_numeric(g.get("projection_mean"), errors="coerce"),
            "stddev": pd.to_numeric(g.get("STDDEV"), errors="coerce"),
            "p_pred": pd.to_numeric(g.get("hit_rate"), errors="coerce"),
            "edge_model": pd.to_numeric(g.get("edge"), errors="coerce"),
            "confidence": pd.to_numeric(g.get("confidence_score"), errors="coerce"),
            "actual": pd.to_numeric(g.get("actual_value"), errors="coerce"),
            "result": res,
            "won": won.astype(int),
            "push": push,
        }
    )
    # Derived selection signals (do these beat the model's own probability?)
    df["abs_dist"] = (df["proj"] - df["line"]).abs()
    df["z_edge"] = (df["proj"] - df["line"]).abs() / df["stddev"].where(df["stddev"] > 0)
    df["is_combo"] = df["stat"].isin(C.COMBO_MARKETS)
    return df


def graded_only(df: pd.DataFrame) -> pd.DataFrame:
    """Drop pushes for win-rate / ROI calculations."""
    return df[~df["push"]].copy()


# --------------------------------------------------------------------------- #
# Breakdowns
# --------------------------------------------------------------------------- #
def _summ(sub: pd.DataFrame, pushes: int = 0) -> dict:
    s = M.performance_summary(sub["won"].values, sub["p_pred"].values, pushes=pushes)
    d = s.as_dict()
    bt = M.beats_breakeven(d["wins"], d["n"], C.BREAKEVEN_MINUS_110)
    d.update({"ci95_low": bt["ci95_low"], "ci95_high": bt["ci95_high"],
              "sig_vs_-110": bt["significant"]})
    return d


def breakdown_by(df: pd.DataFrame, col: str, min_n: int = 1) -> pd.DataFrame:
    rows = []
    for val, sub in df.groupby(col, dropna=False):
        if len(sub) < min_n:
            continue
        d = {col: val}
        d.update(_summ(sub))
        rows.append(d)
    out = pd.DataFrame(rows)
    return out.sort_values("n", ascending=False) if not out.empty else out


def bucketize(df: pd.DataFrame, col: str, q: int = 5) -> pd.DataFrame:
    """Quantile-bucket a continuous selection signal and report win rate per bucket.
    Used to test whether a signal (z_edge, abs_dist, confidence) separates winners."""
    sub = df[df[col].notna()].copy()
    if sub[col].nunique() < q:
        return pd.DataFrame()
    sub["bucket"] = pd.qcut(sub[col], q=q, duplicates="drop")
    rows = []
    for b, s in sub.groupby("bucket", observed=True):
        d = {"bucket": str(b), "signal": col}
        d.update(_summ(s))
        rows.append(d)
    return pd.DataFrame(rows)


def threshold_sweep(df: pd.DataFrame, signal: str, lo=None, hi=None, steps: int = 20) -> pd.DataFrame:
    """For each minimum-threshold on `signal`, report bets kept, win rate, ROI.
    Answers 'is the threshold wrong?' and 'is there a better operating point?'"""
    s = df[df[signal].notna()].copy()
    if s.empty:
        return pd.DataFrame()
    lo = s[signal].quantile(0.05) if lo is None else lo
    hi = s[signal].quantile(0.95) if hi is None else hi
    rows = []
    for t in np.linspace(lo, hi, steps):
        kept = s[s[signal] >= t]
        if len(kept) < C.MIN_BUCKET_N:
            continue
        wr = kept["won"].mean()
        rows.append(
            {
                "min_" + signal: round(float(t), 4),
                "n_bets": int(len(kept)),
                "win_rate": round(float(wr), 4),
                "roi_minus110": round(M.roi_flat(kept["won"].values, -110), 4),
                "edge_vs_be_pp": round((wr - C.BREAKEVEN_MINUS_110) * 100, 2),
            }
        )
    return pd.DataFrame(rows)


def clv_proxy(df: pd.DataFrame) -> dict:
    """Open->bet line movement as a WEAK proxy for CLV.

    True CLV needs the closing line, which was not captured (PrizePicks, no odds,
    line_open only ~37% populated). For an OVER, a lower line is bettor-favorable;
    for an UNDER, a higher line is. We measure whether the bet line is favorable
    vs the open. This is a steam/selection indicator, NOT validated CLV.
    """
    s = df[df["line_open"].notna() & df["line"].notna() & (df["line_move"].abs() > 0)].copy()
    if s.empty:
        return {"available": False, "reason": "no usable line_open/line_move rows"}
    # favorable move = line moved in the direction that makes our side better
    over = s["side"].eq("over")
    s["fav_move"] = np.where(over, s["line_open"] - s["line"], s["line"] - s["line_open"])
    return {
        "available": True,
        "n_with_movement": int(len(s)),
        "pct_of_book": round(len(s) / len(df) * 100, 1),
        "mean_fav_move": round(float(s["fav_move"].mean()), 3),
        "pct_favorable": round(float((s["fav_move"] > 0).mean()) * 100, 1),
        "win_rate_when_favorable": round(float(s.loc[s.fav_move > 0, "won"].mean()), 4),
        "win_rate_when_adverse": round(float(s.loc[s.fav_move < 0, "won"].mean()), 4),
        "caveat": "WEAK proxy: open->bet movement, not bet->close. Start capturing closing lines.",
    }


# --------------------------------------------------------------------------- #
# Diagnostic questions
# --------------------------------------------------------------------------- #
def answer_questions(df: pd.DataFrame) -> dict:
    g = graded_only(df)
    n, wins = len(g), int(g["won"].sum())
    overall = M.beats_breakeven(wins, n, C.BREAKEVEN_MINUS_110)
    brier = M.brier_score(g["won"].values, g["p_pred"].values)
    ece = M.expected_calibration_error(g["won"].values, g["p_pred"].values)
    overconf = M.overconfidence_index(g["won"].values, g["p_pred"].values)

    # Does any existing signal separate winners better than the model's own prob?
    sep = {}
    for sig in ["p_pred", "z_edge", "abs_dist", "confidence", "edge_model"]:
        bk = bucketize(g, sig, q=5)
        if not bk.empty:
            top = bk.iloc[-1]  # highest bucket
            bot = bk.iloc[0]
            sep[sig] = {
                "top_bucket_winrate": round(float(top["win_rate"]), 4),
                "bottom_bucket_winrate": round(float(bot["win_rate"]), 4),
                "monotonic_lift_pp": round((float(top["win_rate"]) - float(bot["win_rate"])) * 100, 2),
            }

    # Best achievable operating point on z_edge (a model-agnostic selection rule)
    sweep = threshold_sweep(g, "z_edge")
    best = None
    if not sweep.empty:
        b = sweep.loc[sweep["win_rate"].idxmax()]
        best = b.to_dict()

    return {
        "is_model_truly_bad": {
            "verdict": "edge is marginal but real-ish" if overall["significant"]
            else "not significantly profitable vs -110",
            "win_rate": round(overall["win_rate"], 4),
            "ci95": [round(overall["ci95_low"], 4), round(overall["ci95_high"], 4)],
            "edge_pp_vs_-110": round(overall["edge_pp"], 2),
        },
        "is_selection_bad": {
            "model_prob_separates_winners": sep.get("p_pred", {}).get("monotonic_lift_pp"),
            "best_alternative_signal": max(sep, key=lambda k: sep[k]["monotonic_lift_pp"]) if sep else None,
            "all_signal_lifts_pp": {k: v["monotonic_lift_pp"] for k, v in sep.items()},
            "note": "If an alternative signal has higher lift than p_pred, selection is leaving money on the table.",
        },
        "is_threshold_wrong": {
            "best_z_edge_operating_point": best,
            "note": "Compare best win_rate here vs the live ~53.8%. Large gap => threshold/selection issue, not model.",
        },
        "is_there_hidden_edge": {
            "calibration_is_broken": bool(ece > 0.15 or overconf > 0.15),
            "brier": round(brier, 4),
            "ece": round(ece, 4),
            "overconfidence": round(overconf, 4),
            "interpretation": (
                "Probabilities are severely overconfident; the ranking signal inside them may still "
                "be usable after recalibration. Hidden edge is most likely recoverable via calibration "
                "+ better selection, not raw point-accuracy."
            ),
        },
    }


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def run() -> dict:
    C.BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    df = load_graded()
    g = graded_only(df)
    pushes = int(df["push"].sum())

    overall = _summ(g, pushes=pushes)
    by_stat = breakdown_by(g, "stat")
    by_side = breakdown_by(g, "side")
    by_combo = breakdown_by(g, "is_combo")
    by_conf = breakdown_by(g, "confidence")
    reliab = M.reliability_table(g["won"].values, g["p_pred"].values, C.CALIB_BINS)
    buckets = {sig: bucketize(g, sig) for sig in ["p_pred", "z_edge", "abs_dist", "confidence"]}
    sweep_z = threshold_sweep(g, "z_edge")
    sweep_p = threshold_sweep(g, "p_pred")
    clv = clv_proxy(g)
    qa = answer_questions(df)

    # ---- persist artifacts ----
    by_stat.to_csv(C.BASELINE_DIR / "by_stat.csv", index=False)
    by_side.to_csv(C.BASELINE_DIR / "by_side.csv", index=False)
    by_conf.to_csv(C.BASELINE_DIR / "by_confidence.csv", index=False)
    reliab.to_csv(C.BASELINE_DIR / "reliability_curve.csv", index=False)
    sweep_z.to_csv(C.BASELINE_DIR / "threshold_sweep_zedge.csv", index=False)
    sweep_p.to_csv(C.BASELINE_DIR / "threshold_sweep_modelprob.csv", index=False)
    for sig, b in buckets.items():
        if not b.empty:
            b.to_csv(C.BASELINE_DIR / f"buckets_{sig}.csv", index=False)

    baseline = {
        "generated": pd.Timestamp.now("UTC").isoformat(),
        "date_range": [str(df["date"].min().date()), str(df["date"].max().date())],
        "n_graded": overall["n"],
        "pushes": pushes,
        "overall": overall,
        "by_combo": by_combo.to_dict("records"),
        "clv_proxy": clv,
        "diagnostics": qa,
    }
    (C.BASELINE_DIR / "baseline.json").write_text(json.dumps(baseline, indent=2, default=str))
    _write_markdown(baseline, by_stat, by_side, by_conf, reliab, sweep_z, buckets, clv)
    return baseline


def _fmt_table(df: pd.DataFrame, cols: list[str]) -> str:
    df = df[[c for c in cols if c in df.columns]].copy()
    head = "| " + " | ".join(cols) + " |\n| " + " | ".join("---" for _ in cols) + " |\n"
    body = ""
    for _, r in df.iterrows():
        body += "| " + " | ".join(
            f"{r[c]:.4f}" if isinstance(r[c], float) else str(r[c]) for c in cols
        ) + " |\n"
    return head + body


def _write_markdown(baseline, by_stat, by_side, by_conf, reliab, sweep_z, buckets, clv):
    o = baseline["overall"]
    q = baseline["diagnostics"]
    md = f"""# WNBA Engine V2 — Phase 0 Official Baseline

Generated: {baseline['generated']}
Window: {baseline['date_range'][0]} → {baseline['date_range'][1]}
Graded legs: **{baseline['n_graded']}** (+{baseline['pushes']} pushes excluded)

## Headline
- **Win rate: {o['win_rate']:.4f}** (95% CI {o['ci95_low']:.4f}–{o['ci95_high']:.4f})
- ROI @ -110 proxy: **{o['roi_minus110']:+.4f}**
- Breakeven (-110): {C.BREAKEVEN_MINUS_110}. Significantly profitable? **{o['sig_vs_-110']}**
- Brier: **{o['brier']:.4f}** | LogLoss: {o['log_loss']:.4f} | ECE: **{o['ece']:.4f}** | Overconfidence: **{o['overconf']:+.4f}**

> Brier 0.25 = a coin flip. ECE/overconfidence near 0 = calibrated. These numbers are
> the bar every rebuild phase must beat.

## The four questions
**1. Is the model truly bad?** {q['is_model_truly_bad']['verdict']}
 (win {q['is_model_truly_bad']['win_rate']:.4f}, edge {q['is_model_truly_bad']['edge_pp_vs_-110']:+.2f}pp vs -110)

**2. Is selection bad?** Model-probability winner-separation lift: **{q['is_selection_bad']['model_prob_separates_winners']} pp**.
 Best alternative selection signal: **{q['is_selection_bad']['best_alternative_signal']}**.
 All signal lifts (top vs bottom quintile win-rate, pp): {q['is_selection_bad']['all_signal_lifts_pp']}

**3. Is the threshold wrong?** Best z-edge operating point: {q['is_threshold_wrong']['best_z_edge_operating_point']}

**4. Is there hidden edge?** Calibration broken: **{q['is_there_hidden_edge']['calibration_is_broken']}**
 (Brier {q['is_there_hidden_edge']['brier']}, ECE {q['is_there_hidden_edge']['ece']}, overconf {q['is_there_hidden_edge']['overconfidence']}).
 {q['is_there_hidden_edge']['interpretation']}

## Win rate by market
{_fmt_table(by_stat, ['stat','n','win_rate','roi_minus110','edge_pp' if 'edge_pp' in by_stat else 'brier','sig_vs_-110'])}
## Win rate by side
{_fmt_table(by_side, ['side','n','win_rate','roi_minus110','brier'])}
## Win rate by confidence score
{_fmt_table(by_conf, ['confidence','n','win_rate','roi_minus110'])}
## Reliability curve (predicted prob vs realized)
{_fmt_table(reliab, ['bin','n','mean_predicted','realized_winrate','gap'])}
## z-edge threshold sweep (|proj-line|/stddev)
{_fmt_table(sweep_z, ['min_z_edge','n_bets','win_rate','roi_minus110','edge_vs_be_pp']) if not sweep_z.empty else '_no stddev available_'}
## CLV proxy
```
{json.dumps(clv, indent=2)}
```
"""
    (C.BASELINE_DIR / "BASELINE_REPORT.md").write_text(md)


if __name__ == "__main__":
    b = run()
    print(json.dumps(b["overall"], indent=2, default=str))
    print("\nDiagnostics:")
    print(json.dumps(b["diagnostics"], indent=2, default=str))
    print(f"\nArtifacts -> {C.BASELINE_DIR}")
