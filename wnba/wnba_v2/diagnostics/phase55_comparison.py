"""Phase 5.5 — compare conserved V2 replacement vs old V2 and production.

This is reporting/evaluation only. The conserved simulator remains the V2 path;
the old independent simulator is replayed solely as a historical benchmark.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.engines.simulation.backtest import EVAL_SEASON, N_SIMS, build_spines
from wnba_v2.engines.simulation.calibrate import compute_calibration
from wnba_v2.engines.simulation.engine import COMBOS, prob_over, simulate_player
from wnba_v2.engines.simulation.sim_inputs import norm_name

OUT = C.OUTPUTS / "phase55"
OLD_INDEPENDENT = OUT / "old_independent_backtest_graded.csv"
NEW_CONSERVED = C.OUTPUTS / "simulation" / "backtest_graded.csv"
TODAY_COMPARISON = C.OUTPUTS / "phase54" / "v2_vs_current_production_today.csv"
REALISM_SUMMARY = C.OUTPUTS / "phase53" / "phase53_validation_summary.json"
SUMMARY_JSON = OUT / "phase55_summary.json"
SUMMARY_MD = OUT / "PHASE55_COMPARISON_REPORT.md"
BASE_STATS = {"points", "rebounds", "assists", "threes_made", "steals", "blocks"}
COMBO_STATS = {"pa", "pr", "ra", "pra"}
CONVICTION_BANDS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.50)]


def _brier(p, y) -> float:
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    return float(np.mean((p - y) ** 2)) if len(p) else float("nan")


def _ece(p, y, bins: int = 10) -> float:
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(p) == 0:
        return float("nan")
    idx = np.clip(np.digitize(p, np.linspace(0, 1, bins + 1)) - 1, 0, bins - 1)
    return float(sum((idx == b).mean() * abs(p[idx == b].mean() - y[idx == b].mean()) for b in range(bins) if (idx == b).any()))


def _metric_row(label: str, df: pd.DataFrame, *, production: bool = False, market: str | None = None) -> dict:
    if market is not None:
        df = df[df["stat"] == market]
    if df.empty:
        return {"engine": label, "market": market or "ALL", "n": 0}
    correct = df["prod_correct"] if production else df["v2_correct"]
    p_over = df["prod_p_over"] if production else df["v2_p_over"]
    return {
        "engine": label,
        "market": market or "ALL",
        "n": int(len(df)),
        "hit_rate": round(float(correct.mean()), 4),
        "brier": round(_brier(p_over, df["actual_over"]), 4),
        "ece": round(_ece(p_over, df["actual_over"]), 4),
        "combo_brier": round(_brier(p_over[df["is_combo"]], df.loc[df["is_combo"], "actual_over"]), 4) if df["is_combo"].any() else None,
        "over_pick_rate": round(float((p_over > 0.5).mean()), 4),
        "mean_projection": round(float(df["v2_proj"].mean()), 4) if not production else None,
    }


def _market_metrics(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    markets = sorted(set(old["stat"].dropna()) | set(new["stat"].dropna()))
    rows = []
    for market in markets:
        rows.extend([
            _metric_row("old_v2_independent", old, market=market),
            _metric_row("new_v2_conserved", new, market=market),
            _metric_row("production", new, production=True, market=market),
        ])
    return pd.DataFrame(rows)


def _overall_metrics(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([
        _metric_row("old_v2_independent", old),
        _metric_row("new_v2_conserved", new),
        _metric_row("production", new, production=True),
    ])


def _conviction_buckets(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, df in [("old_v2_independent", old), ("new_v2_conserved", new)]:
        for lo, hi in CONVICTION_BANDS:
            s = df[(df["conf"] >= lo) & (df["conf"] < hi)]
            if s.empty:
                rows.append({"engine": label, "band": f"{lo:.2f}-{hi:.2f}", "n": 0})
                continue
            rows.append({
                "engine": label,
                "band": f"{lo:.2f}-{hi:.2f}",
                "n": int(len(s)),
                "hit_rate": round(float(s["v2_correct"].mean()), 4),
                "brier": round(_brier(s["v2_p_over"], s["actual_over"]), 4),
                "ece": round(_ece(s["v2_p_over"], s["actual_over"]), 4),
            })
    return pd.DataFrame(rows)


def _today_market_changes() -> pd.DataFrame:
    if not TODAY_COMPARISON.exists():
        return pd.DataFrame()
    today = pd.read_csv(TODAY_COMPARISON)
    if today.empty:
        return pd.DataFrame()
    rows = []
    for stat, s in today.groupby("STAT"):
        delta = pd.to_numeric(s["projection_delta_v2_minus_production"], errors="coerce")
        rows.append({
            "stat": stat,
            "n": int(len(s)),
            "mean_v2": round(float(s["PROJECTION_v2"].mean()), 4),
            "mean_production": round(float(s["PROJECTION_production"].mean()), 4),
            "mean_delta_v2_minus_production": round(float(delta.mean()), 4),
            "mean_abs_delta": round(float(delta.abs().mean()), 4),
            "max_abs_delta": round(float(delta.abs().max()), 4),
        })
    out = pd.DataFrame(rows).sort_values("mean_abs_delta", ascending=False)
    out.to_csv(OUT / "today_market_changes.csv", index=False)
    today.sort_values("projection_delta_v2_minus_production", key=lambda s: s.abs(), ascending=False).to_csv(OUT / "today_projection_changes_ranked.csv", index=False)
    return out


def _generate_old_independent() -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    if OLD_INDEPENDENT.exists():
        return pd.read_csv(OLD_INDEPENDENT)
    rng = np.random.default_rng(C.RANDOM_SEED)
    train_spine, eval_spine = build_spines(EVAL_SEASON)
    calib = compute_calibration(train_spine, rng)
    idx = {(r["name_key"], str(pd.Timestamp(r["date"]).date())): r for _, r in eval_spine.iterrows()}

    g = pd.read_csv(C.GRADED_BETS_PATH)
    g = g[g["bet_result"].isin(["win", "loss"])].copy()
    g["name_key"] = g["player_name"].map(norm_name)
    g["date_key"] = pd.to_datetime(g["bet_date"]).dt.date.astype(str)
    g["actual_over"] = (g["actual_value"] > g["line"]).astype(int)

    cache, rows = {}, []
    allowed = BASE_STATS | set(COMBOS)
    for _, b in g.iterrows():
        key = (b["name_key"], b["date_key"])
        row = idx.get(key)
        if row is None or b["stat"] not in allowed:
            continue
        if key not in cache:
            cache[key] = simulate_player(row, N_SIMS, rng, calib=calib)
        samples = cache[key].get(b["stat"])
        if samples is None:
            continue
        p_over = prob_over(samples, float(b["line"]))
        prod_p_over = b["hit_rate"] if b["side"] == "over" else 1 - b["hit_rate"]
        rows.append({
            "date": b["date_key"], "player": b["player_name"], "stat": b["stat"],
            "line": b["line"], "actual_over": int(b["actual_over"]),
            "v2_proj": round(float(np.mean(samples)), 2), "actual_value": float(b["actual_value"]),
            "v2_p_over": p_over, "v2_correct": int((p_over > 0.5) == bool(b["actual_over"])),
            "prod_correct": int(b["bet_result"] == "win"), "prod_p_over": float(prod_p_over),
            "conf": abs(p_over - 0.5), "clv": np.nan, "is_combo": b["stat"] in COMBOS,
        })
    out = pd.DataFrame(rows)
    out.to_csv(OLD_INDEPENDENT, index=False)
    return out


def _points_ra_summary(market: pd.DataFrame) -> dict:
    out = {}
    for market_name in ["points", "ra"]:
        s = market[market["market"] == market_name].copy()
        if s.empty:
            out[market_name] = {"available": False}
            continue
        pivot = s.set_index("engine")
        out[market_name] = {
            "available": True,
            "old_hit": pivot.at["old_v2_independent", "hit_rate"] if "old_v2_independent" in pivot.index else None,
            "new_hit": pivot.at["new_v2_conserved", "hit_rate"] if "new_v2_conserved" in pivot.index else None,
            "production_hit": pivot.at["production", "hit_rate"] if "production" in pivot.index else None,
            "old_brier": pivot.at["old_v2_independent", "brier"] if "old_v2_independent" in pivot.index else None,
            "new_brier": pivot.at["new_v2_conserved", "brier"] if "new_v2_conserved" in pivot.index else None,
            "production_brier": pivot.at["production", "brier"] if "production" in pivot.index else None,
            "improved_vs_old_hit": bool(pivot.at["new_v2_conserved", "hit_rate"] >= pivot.at["old_v2_independent", "hit_rate"]),
            "improved_vs_old_brier": bool(pivot.at["new_v2_conserved", "brier"] <= pivot.at["old_v2_independent", "brier"]),
        }
    return out


def _load_realism() -> dict:
    if not REALISM_SUMMARY.exists():
        return {"available": False}
    payload = json.loads(REALISM_SUMMARY.read_text())
    return {
        "available": True,
        "accepted": bool(payload.get("accepted")),
        "acceptance_checks": payload.get("acceptance_checks", {}),
        "scores": payload.get("scores", {}),
    }


def _recommendation(overall: pd.DataFrame, market: pd.DataFrame, realism: dict) -> str:
    pivot = overall.set_index("engine")
    new = pivot.loc["new_v2_conserved"]
    prod = pivot.loc["production"]
    old = pivot.loc["old_v2_independent"]
    combos_new = new.get("combo_brier")
    combos_prod = prod.get("combo_brier")
    realism_ok = bool(realism.get("accepted") and realism.get("acceptance_checks", {}).get("all_pass"))
    if realism_ok and new["brier"] <= prod["brier"] and combos_new <= combos_prod and new["hit_rate"] >= old["hit_rate"]:
        return "Emergency serving, if used, should use conserved V2 only. Do not serve the old independent simulator."
    if realism_ok and new["brier"] <= prod["brier"] and combos_new <= combos_prod:
        return "Use conserved V2 only for emergency serving experiments, with hit-rate monitoring as the primary residual risk."
    return "Do not use the old independent simulator. Conserved V2 is the only V2 simulator path, but emergency serving should wait for the listed gaps to clear."


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    old = _generate_old_independent()
    if not NEW_CONSERVED.exists():
        raise FileNotFoundError(f"missing conserved backtest: {NEW_CONSERVED}")
    new = pd.read_csv(NEW_CONSERVED)

    overall = _overall_metrics(old, new)
    market = _market_metrics(old, new)
    buckets = _conviction_buckets(old, new)
    today = _today_market_changes()
    realism = _load_realism()
    points_ra = _points_ra_summary(market)
    recommendation = _recommendation(overall, market, realism)

    overall.to_csv(OUT / "historical_overall_comparison.csv", index=False)
    market.to_csv(OUT / "historical_market_comparison.csv", index=False)
    buckets.to_csv(OUT / "historical_conviction_buckets.csv", index=False)

    summary = {
        "phase": "5.5",
        "generated": datetime.now(timezone.utc).isoformat(),
        "historical_rows": {"old_v2_independent": int(len(old)), "new_v2_conserved": int(len(new))},
        "overall": overall.to_dict("records"),
        "markets_changed_most_today": today.head(10).to_dict("records") if not today.empty else [],
        "points_ra_weakness": points_ra,
        "conviction_buckets": buckets.to_dict("records"),
        "realism": realism,
        "recommendation": recommendation,
        "artifacts": {
            "old_independent_replay": str(OLD_INDEPENDENT),
            "historical_overall": str(OUT / "historical_overall_comparison.csv"),
            "historical_market": str(OUT / "historical_market_comparison.csv"),
            "historical_conviction_buckets": str(OUT / "historical_conviction_buckets.csv"),
            "today_market_changes": str(OUT / "today_market_changes.csv"),
            "today_projection_changes_ranked": str(OUT / "today_projection_changes_ranked.csv"),
            "report": str(SUMMARY_MD),
        },
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, default=str))
    _write_report(summary, overall, market, buckets, today)
    return summary


def _fmt(x):
    if x is None or pd.isna(x):
        return "NA"
    return f"{float(x):.4f}"


def _write_report(summary: dict, overall: pd.DataFrame, market: pd.DataFrame, buckets: pd.DataFrame, today: pd.DataFrame) -> None:
    overall_lines = [f"| {r.engine} | {int(r.n)} | {_fmt(r.hit_rate)} | {_fmt(r.brier)} | {_fmt(r.ece)} | {_fmt(r.combo_brier)} |" for r in overall.itertuples()]
    market_pivot = market.pivot(index="market", columns="engine", values=["hit_rate", "brier"]).reset_index()
    market_lines = []
    for _, r in market_pivot.iterrows():
        market_name = r[("market", "")]
        market_lines.append(
            f"| {market_name} | {_fmt(r.get(('hit_rate','old_v2_independent')))} | {_fmt(r.get(('hit_rate','new_v2_conserved')))} | {_fmt(r.get(('hit_rate','production')))} | {_fmt(r.get(('brier','old_v2_independent')))} | {_fmt(r.get(('brier','new_v2_conserved')))} | {_fmt(r.get(('brier','production')))} |"
        )
    today_lines = []
    if not today.empty:
        for r in today.head(10).itertuples():
            today_lines.append(f"| {r.stat} | {r.n} | {_fmt(r.mean_v2)} | {_fmt(r.mean_production)} | {_fmt(r.mean_delta_v2_minus_production)} | {_fmt(r.mean_abs_delta)} |")
    bucket_lines = [f"| {r.engine} | {r.band} | {int(r.n)} | {_fmt(getattr(r, 'hit_rate', np.nan))} | {_fmt(getattr(r, 'brier', np.nan))} | {_fmt(getattr(r, 'ece', np.nan))} |" for r in buckets.itertuples()]
    checks = summary["realism"].get("acceptance_checks", {}) if summary.get("realism") else {}
    check_lines = "\n".join(f"- {k}: {v}" for k, v in checks.items())
    md = f"""# WNBA V2 Phase 5.5 Conserved Simulator Comparison

Generated: {summary['generated']}

## Overall Historical Tracker

| Engine | n | Hit Rate | Brier | ECE | Combo Brier |
|---|---:|---:|---:|---:|---:|
{chr(10).join(overall_lines)}

## Markets Changed Most On Today's Board

| Stat | n | Conserved V2 Mean | Production Mean | Mean Delta | Mean Abs Delta |
|---|---:|---:|---:|---:|---:|
{chr(10).join(today_lines)}

## Historical Market Comparison

| Market | Old V2 Hit | New V2 Hit | Production Hit | Old V2 Brier | New V2 Brier | Production Brier |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(market_lines)}

## Conviction Buckets

| Engine | Band | n | Hit Rate | Brier | ECE |
|---|---|---:|---:|---:|---:|
{chr(10).join(bucket_lines)}

## Points / RA Weakness

```json
{json.dumps(summary['points_ra_weakness'], indent=2, default=str)}
```

## Realism Gates

Accepted: {summary['realism'].get('accepted')}

{check_lines}

## Recommendation

{summary['recommendation']}
"""
    SUMMARY_MD.write_text(md)


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
