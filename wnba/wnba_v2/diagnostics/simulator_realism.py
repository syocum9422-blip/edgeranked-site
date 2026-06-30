"""Phase 5 simulator realism diagnostics.

This audits the simulator as a generative model against real WNBA outcomes. It is
not a betting/promotion report: no recommendation filtering, serving, or gate logic.

Run: python -m wnba_v2.diagnostics.simulator_realism
"""
from __future__ import annotations

import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.engines.efficiency.rates import build_rate_frame
from wnba_v2.engines.simulation.backtest import EVAL_SEASON, build_spines
from wnba_v2.engines.simulation.engine import COMBOS, STATS, simulate_player
from wnba_v2.engines.usage.roles import build_redistribution_frame

OUT = C.OUTPUTS / "realism"
N_SIMS = 1000
PAIR_STATS = [("points", "rebounds"), ("points", "assists"), ("rebounds", "assists")]
STAT_MAP = {
    "points": "points",
    "rebounds": "reb",
    "assists": "ast",
    "threes_made": "fg3m",
    "steals": "stl",
    "blocks": "blk",
}
ALL_STATS = ["points", "rebounds", "assists", "threes_made", "steals", "blocks", "pa", "pr", "ra", "pra"]
TEAM_STATS = ["points", "reb", "ast"]


def _load_calibration() -> dict:
    path = C.OUTPUTS / "simulation" / "promotion_gate.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text())
    return payload.get("phase5_1_calibration", {}) or {}


def _actual_column(stat: str) -> str:
    return STAT_MAP.get(stat, stat)


def _actual_value(row: pd.Series, stat: str) -> float:
    if stat in COMBOS:
        return float(sum(row[_actual_column(part)] for part in COMBOS[stat]))
    return float(row[_actual_column(stat)])


def _minutes_samples(row: pd.Series, n_sims: int, rng: np.random.Generator) -> np.ndarray:
    plays = rng.random(n_sims) < float(row["play_prob"])
    std = max(float(row.get("min_std", 5.0)), 1e-4)
    return np.clip(rng.normal(float(row["min_mean"]), std, n_sims), 0.0, None) * plays


def _pace_samples(row: pd.Series, n_sims: int, rng: np.random.Generator) -> np.ndarray:
    return np.clip(rng.normal(float(row["team_poss_lag"]), 4.7, n_sims), 0.0, None)


def _coverage_label(stat_rows: pd.DataFrame) -> str:
    central = float(stat_rows["inside_p10_p90"].mean())
    lower = float(stat_rows["actual_le_p10"].mean())
    upper = float(stat_rows["actual_ge_p90"].mean())
    zero_err = abs(float(stat_rows["pred_zero_rate"].mean()) - float(stat_rows["actual_zero"].mean()))
    mean_err = float(stat_rows["mean_error"].mean())
    var_ratio = float(stat_rows["sim_var"].mean() / stat_rows["actual_value"].var(ddof=1)) if stat_rows["actual_value"].var(ddof=1) > 0 else np.nan
    flags = []
    if mean_err > 0.75:
        flags.append("means high")
    if mean_err < -0.75:
        flags.append("means low")
    if central < 0.72:
        flags.append("variance too narrow")
    if central > 0.88:
        flags.append("variance too wide")
    if lower > 0.14:
        flags.append("too many high simulations / real outcomes below p10")
    if upper > 0.14:
        flags.append("upper tail under-modeled")
    if zero_err > 0.05:
        flags.append("zero inflation wrong")
    if pd.notna(var_ratio) and var_ratio < 0.65:
        flags.append("aggregate variance low")
    if pd.notna(var_ratio) and var_ratio > 1.35:
        flags.append("aggregate variance high")
    return "; ".join(flags) if flags else "acceptable"


def _pairwise_teammate_corr(frame: pd.DataFrame, value_col: str, min_games: int = 5) -> float | None:
    rows = []
    keys = ["game_id", "team"]
    for _, team_game in frame.dropna(subset=[value_col]).groupby(keys):
        vals = team_game[["player_id", value_col]].copy()
        for a, b in combinations(vals.itertuples(index=False), 2):
            rows.append({"pair": tuple(sorted((a.player_id, b.player_id))), "a": a[1], "b": b[1]})
    if not rows:
        return None
    pairs = pd.DataFrame(rows)
    cors = []
    for _, s in pairs.groupby("pair"):
        if len(s) >= min_games and s["a"].std(ddof=1) > 0 and s["b"].std(ddof=1) > 0:
            cors.append(float(s["a"].corr(s["b"])))
    return float(np.nanmean(cors)) if cors else None


def run(n_sims: int = N_SIMS) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(C.RANDOM_SEED)
    calib = _load_calibration()
    _, eval_spine = build_spines(EVAL_SEASON)
    rf = build_rate_frame()
    actual_cols = [
        "player_id", "date", "game_id", "opponent", "starter", "played", "minutes",
        "points", "reb", "ast", "fg3m", "stl", "blk", "team_poss", "opp_poss",
    ]
    actual = rf[rf["season"] == EVAL_SEASON][actual_cols].copy()
    actual["date"] = pd.to_datetime(actual["date"]).dt.date.astype(str)
    eval_spine["date"] = pd.to_datetime(eval_spine["date"]).dt.date.astype(str)
    rows = eval_spine.merge(actual, on=["player_id", "date"], how="inner", suffixes=("", "_actual"))
    rows = rows[rows["played"] == 1].dropna(subset=["minutes", "points", "reb", "ast", "team_poss"]).reset_index(drop=True)

    row_summaries = []
    corr_rows = []
    team_accum: dict[tuple, dict[str, np.ndarray | float | int]] = {}

    for _, row in rows.iterrows():
        sims = simulate_player(row, n_sims, rng, calib=calib)
        minutes = _minutes_samples(row, n_sims, rng)
        pace = _pace_samples(row, n_sims, rng)
        team_key = (row["game_id"], row["team"])
        if team_key not in team_accum:
            team_accum[team_key] = {
                "points": np.zeros(n_sims), "reb": np.zeros(n_sims), "ast": np.zeros(n_sims),
                "starter_minutes": np.zeros(n_sims), "bench_minutes": np.zeros(n_sims),
                "possessions": pace.copy(), "n_players": 0,
            }
        team_accum[team_key]["points"] += sims["points"]
        team_accum[team_key]["reb"] += sims["rebounds"]
        team_accum[team_key]["ast"] += sims["assists"]
        if int(row.get("starter", 0)) == 1:
            team_accum[team_key]["starter_minutes"] += minutes
        else:
            team_accum[team_key]["bench_minutes"] += minutes
        team_accum[team_key]["n_players"] += 1

        for stat in ALL_STATS:
            sample = np.asarray(sims[stat], dtype=float)
            actual_value = _actual_value(row, stat)
            p10, p50, p90 = np.percentile(sample, [10, 50, 90])
            row_summaries.append({
                "date": row["date"], "game_id": row["game_id"], "team": row["team"],
                "player_id": row["player_id"], "player": row["player_name"], "stat": stat,
                "actual_value": actual_value, "sim_mean": float(sample.mean()), "sim_var": float(sample.var(ddof=1)),
                "p10": float(p10), "p50": float(p50), "p90": float(p90),
                "mean_error": float(sample.mean() - actual_value),
                "abs_error": abs(float(sample.mean() - actual_value)),
                "pred_zero_rate": float(np.mean(np.isclose(sample, 0))),
                "actual_zero": float(actual_value == 0),
                "actual_le_p10": float(actual_value <= p10),
                "actual_le_p50": float(actual_value <= p50),
                "actual_le_p90": float(actual_value <= p90),
                "actual_ge_p90": float(actual_value >= p90),
                "inside_p10_p90": float(p10 <= actual_value <= p90),
            })
        for a, b in PAIR_STATS:
            sa, sb = np.asarray(sims[a], dtype=float), np.asarray(sims[b], dtype=float)
            corr = float(np.corrcoef(sa, sb)[0, 1]) if sa.std() > 0 and sb.std() > 0 else np.nan
            corr_rows.append({"game_id": row["game_id"], "team": row["team"], "player": row["player_name"], "pair": f"{a}/{b}", "sim_corr": corr})

    detail = pd.DataFrame(row_summaries)
    detail.to_csv(OUT / "per_player_stat_realism_detail.csv", index=False)

    stat_rows = []
    for stat, s in detail.groupby("stat"):
        actual_var = float(s["actual_value"].var(ddof=1))
        pred_var = float(s["sim_var"].mean())
        stat_rows.append({
            "stat": stat, "n": int(len(s)),
            "mean_error": float(s["mean_error"].mean()),
            "mae": float(s["abs_error"].mean()),
            "actual_variance": actual_var,
            "mean_sim_variance": pred_var,
            "variance_ratio_sim_to_actual": pred_var / actual_var if actual_var > 0 else np.nan,
            "p10_coverage_actual_le": float(s["actual_le_p10"].mean()),
            "p50_coverage_actual_le": float(s["actual_le_p50"].mean()),
            "p90_coverage_actual_le": float(s["actual_le_p90"].mean()),
            "central_80_coverage": float(s["inside_p10_p90"].mean()),
            "actual_upper_tail_ge_p90": float(s["actual_ge_p90"].mean()),
            "pred_zero_rate": float(s["pred_zero_rate"].mean()),
            "actual_zero_rate": float(s["actual_zero"].mean()),
            "diagnosis": _coverage_label(s),
        })
    stat_summary = pd.DataFrame(stat_rows).sort_values("stat")
    stat_summary.to_csv(OUT / "stat_realism_summary.csv", index=False)

    player_summary = detail.groupby(["player_id", "player", "stat"]).agg(
        n=("actual_value", "size"), mean_error=("mean_error", "mean"), mae=("abs_error", "mean"),
        central_80_coverage=("inside_p10_p90", "mean"), pred_zero_rate=("pred_zero_rate", "mean"),
        actual_zero_rate=("actual_zero", "mean"), upper_tail_rate=("actual_ge_p90", "mean"),
    ).reset_index()
    player_summary = player_summary[player_summary["n"] >= 5].sort_values(["mae", "n"], ascending=[False, False])
    player_summary.to_csv(OUT / "per_player_stat_realism.csv", index=False)

    # Correlation realism: within-player stat correlations, teammate share correlations, and team conservation.
    actual_pair_rows = []
    actual_cols_for_corr = {"points": "points", "rebounds": "reb", "assists": "ast"}
    for a, b in PAIR_STATS:
        ac, bc = actual_cols_for_corr[a], actual_cols_for_corr[b]
        actual_corr = float(rows[ac].corr(rows[bc]))
        sim_corr = float(pd.DataFrame(corr_rows).query("pair == @a + '/' + @b")["sim_corr"].mean())
        actual_pair_rows.append({"pair": f"{a}/{b}", "actual_corr": actual_corr, "mean_sim_within_player_corr": sim_corr, "corr_error": sim_corr - actual_corr})

    rdf = build_redistribution_frame()
    rdf26 = rdf[(rdf["season"] == EVAL_SEASON) & (rdf["played"] == 1)].copy()
    teammate_usage_actual = _pairwise_teammate_corr(rdf26, "usage_share")
    teammate_reb_actual = _pairwise_teammate_corr(rdf26, "reb_share")
    corr_summary = pd.DataFrame(actual_pair_rows + [
        {"pair": "teammate_usage_share", "actual_corr": teammate_usage_actual, "mean_sim_within_player_corr": 0.0, "corr_error": None if teammate_usage_actual is None else -teammate_usage_actual},
        {"pair": "teammate_rebound_share", "actual_corr": teammate_reb_actual, "mean_sim_within_player_corr": 0.0, "corr_error": None if teammate_reb_actual is None else -teammate_reb_actual},
    ])
    corr_summary.to_csv(OUT / "correlation_realism.csv", index=False)

    team_actual = pd.read_csv(C.V2_ROOT / "data" / "team_games" / "team_game_logs.csv")
    team_actual = team_actual[team_actual["season"] == EVAL_SEASON].copy()
    team_rows = []
    for (game_id, team), accum in team_accum.items():
        a = team_actual[(team_actual["game_id"] == game_id) & (team_actual["team"] == team)]
        if a.empty:
            continue
        ar = a.iloc[0]
        row = {"game_id": game_id, "team": team, "n_players_simulated": int(accum["n_players"])}
        for stat in ["points", "reb", "ast", "possessions", "starter_minutes", "bench_minutes"]:
            sample = np.asarray(accum[stat], dtype=float)
            if stat == "starter_minutes":
                actual_value = float(rows[(rows["game_id"] == game_id) & (rows["team"] == team) & (rows["starter"] == 1)]["minutes"].sum())
            elif stat == "bench_minutes":
                actual_value = float(rows[(rows["game_id"] == game_id) & (rows["team"] == team) & (rows["starter"] != 1)]["minutes"].sum())
            else:
                actual_value = float(ar[stat])
            p10, p50, p90 = np.percentile(sample, [10, 50, 90])
            row.update({
                f"{stat}_actual": actual_value, f"{stat}_sim_mean": float(sample.mean()),
                f"{stat}_mean_error": float(sample.mean() - actual_value), f"{stat}_sim_var": float(sample.var(ddof=1)),
                f"{stat}_inside_p10_p90": float(p10 <= actual_value <= p90),
                f"{stat}_actual_le_p10": float(actual_value <= p10), f"{stat}_actual_ge_p90": float(actual_value >= p90),
            })
        row["abs_margin"] = abs(float(ar["points"] - ar["opp_points"]))
        team_rows.append(row)
    team_detail = pd.DataFrame(team_rows)
    team_detail.to_csv(OUT / "team_game_realism_detail.csv", index=False)

    game_rows = []
    for stat in ["points", "reb", "ast", "possessions", "starter_minutes", "bench_minutes"]:
        actual = team_detail[f"{stat}_actual"]
        sim_mean = team_detail[f"{stat}_sim_mean"]
        sim_var = team_detail[f"{stat}_sim_var"]
        actual_var = float(actual.var(ddof=1))
        game_rows.append({
            "metric": stat, "n_team_games": int(len(team_detail)),
            "mean_error": float((sim_mean - actual).mean()), "mae": float((sim_mean - actual).abs().mean()),
            "actual_variance": actual_var, "mean_sim_variance": float(sim_var.mean()),
            "variance_ratio_sim_to_actual": float(sim_var.mean() / actual_var) if actual_var > 0 else np.nan,
            "central_80_coverage": float(team_detail[f"{stat}_inside_p10_p90"].mean()),
            "lower_tail_rate": float(team_detail[f"{stat}_actual_le_p10"].mean()),
            "upper_tail_rate": float(team_detail[f"{stat}_actual_ge_p90"].mean()),
        })
    game_summary = pd.DataFrame(game_rows)
    if not team_detail.empty:
        game_summary["actual_abs_margin_corr"] = None
        for stat in ["starter_minutes", "bench_minutes"]:
            mask = game_summary["metric"] == stat
            game_summary.loc[mask, "actual_abs_margin_corr"] = float(team_detail["abs_margin"].corr(team_detail[f"{stat}_actual"]))
            game_summary.loc[mask, "sim_abs_margin_corr"] = float(team_detail["abs_margin"].corr(team_detail[f"{stat}_sim_mean"]))
    game_summary.to_csv(OUT / "game_realism_summary.csv", index=False)

    summary = {
        "eval_season": EVAL_SEASON,
        "n_sims": n_sims,
        "player_games_simulated": int(rows[["player_id", "date"]].drop_duplicates().shape[0]),
        "team_games_simulated": int(len(team_detail)),
        "calibration": calib,
        "stat_summary": stat_summary.to_dict("records"),
        "correlation_summary": corr_summary.to_dict("records"),
        "game_summary": game_summary.to_dict("records"),
        "artifacts": {
            "detail": str(OUT / "per_player_stat_realism_detail.csv"),
            "stat_summary": str(OUT / "stat_realism_summary.csv"),
            "player_summary": str(OUT / "per_player_stat_realism.csv"),
            "correlation_summary": str(OUT / "correlation_realism.csv"),
            "team_detail": str(OUT / "team_game_realism_detail.csv"),
            "game_summary": str(OUT / "game_realism_summary.csv"),
            "report": str(OUT / "SIMULATOR_REALISM_REPORT.md"),
        },
    }
    (OUT / "simulator_realism_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    _write_report(summary, stat_summary, corr_summary, game_summary)
    return summary


def _fmt(x, nd=3):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "NA"
    return f"{float(x):.{nd}f}"


def _write_report(summary: dict, stat_summary: pd.DataFrame, corr_summary: pd.DataFrame, game_summary: pd.DataFrame) -> None:
    stat_table = "\n".join(
        f"| {r.stat} | {int(r.n)} | {_fmt(r.mean_error)} | {_fmt(r.variance_ratio_sim_to_actual)} | {_fmt(r.central_80_coverage)} | {_fmt(r.pred_zero_rate)} | {_fmt(r.actual_zero_rate)} | {_fmt(r.actual_upper_tail_ge_p90)} | {r.diagnosis} |"
        for r in stat_summary.itertuples(index=False)
    )
    corr_table = "\n".join(
        f"| {r.pair} | {_fmt(r.actual_corr)} | {_fmt(r.mean_sim_within_player_corr)} | {_fmt(r.corr_error)} |"
        for r in corr_summary.itertuples(index=False)
    )
    game_table = "\n".join(
        f"| {r.metric} | {_fmt(r.mean_error)} | {_fmt(r.variance_ratio_sim_to_actual)} | {_fmt(r.central_80_coverage)} | {_fmt(r.lower_tail_rate)} | {_fmt(r.upper_tail_rate)} | {_fmt(getattr(r, 'actual_abs_margin_corr', np.nan))} | {_fmt(getattr(r, 'sim_abs_margin_corr', np.nan))} |"
        for r in game_summary.itertuples(index=False)
    )
    fixes = [
        "Return latent minutes, pace, usage, and efficiency draws from the simulator so diagnostics can be first-class artifacts rather than regenerated side calculations.",
        "Replace independent player-level minutes draws with a team rotation allocator that conserves 200 regulation minutes and redistributes starter/bench minutes jointly.",
        "Add game-state conditioning to minutes: large-margin games should compress starter minutes and expand bench minutes; current sim means are mostly independent of final margin.",
        "Model team possessions once per game and pass the shared possession vector to every player on both teams; Phase 5 backtest currently calls `simulate_player` independently.",
        "Conserve team opportunities: usage, rebounds, assists, shot attempts, and made field goals should be allocated from team totals instead of sampled independently per player.",
        "Re-estimate stat-specific residual variance after Phase 5.1 mean calibration; multiplicative mean calibration fixes scale but can leave variance/tail coverage wrong.",
        "Use count distributions for assists/rebounds/points components where discreteness and overdispersion matter; current continuous truncated-normal rates make several stat and combo distributions too smooth.",
        "Fit explicit zero-inflation/low-count components for threes, steals, and blocks using player role/minutes context.",
        "Add a copula or shared latent player-performance factor calibrated to real points/rebounds/assists correlations; current shared minutes/usage is not enough by itself.",
        "Validate combo distributions from joint samples with p10/p50/p90 and tail coverage, not only Brier against lines.",
    ]
    md = f"""# WNBA V2 Phase 5 Simulator Realism Report

Scope: simulator realism only. This report compares generated Phase 5 distributions to actual {summary['eval_season']} WNBA outcomes. It does not evaluate promotion, serving, or selection filters.

Simulated player-games: {summary['player_games_simulated']}  
Simulated team-games: {summary['team_games_simulated']}  
Monte Carlo draws per player-game: {summary['n_sims']}

## Stat Distribution Realism

Targets: p10 coverage near 0.10, p50 near 0.50, p90 near 0.90, central p10-p90 coverage near 0.80, upper-tail rate near 0.10, variance ratio near 1.00.

| Stat | N | Mean Error | Var Ratio | Central 80 Cov | Pred Zero | Actual Zero | Upper Tail | Diagnosis |
|---|---:|---:|---:|---:|---:|---:|---:|---|
{stat_table}

## Correlation Realism

| Pair | Actual Corr | Sim Corr | Error |
|---|---:|---:|---:|
{corr_table}

## Game Realism

| Metric | Mean Error | Var Ratio | Central 80 Cov | Lower Tail | Upper Tail | Actual Margin Corr | Sim Margin Corr |
|---|---:|---:|---:|---:|---:|---:|---:|
{game_table}

## What Is Unrealistic

- Independent player simulations break team-level conservation: team points/rebounds/assists are sums of independently generated player outcomes, not allocations from a coherent team total.
- Phase 5 backtest does not wire shared game pace across teammates/opponents, even though `simulate_player` accepts `shared_pace`.
- Minutes are independently drawn by player and are not constrained to 200 regulation team minutes.
- Blowout effects are not a generative input, so starter compression and bench expansion are structurally under-modeled.
- Usage shares are independently jittered and clipped, so teammate usage competition is not conserved.
- Rebound and assist opportunities are sampled from lagged pools but not conserved across teammates.
- Mean calibration is multiplicative by stat; it can improve average scale while leaving variance, zero rates, and tails unrealistic.
- Combo distributions inherit within-player shared minutes/usage, but team/opponent context and stat-specific residual covariance are still too weak.

## Exact Fixes Required

""" + "\n".join(f"{i+1}. {fix}" for i, fix in enumerate(fixes)) + "\n"
    (OUT / "SIMULATOR_REALISM_REPORT.md").write_text(md)


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "player_games_simulated": result["player_games_simulated"],
        "team_games_simulated": result["team_games_simulated"],
        "artifacts": result["artifacts"],
    }, indent=2))
