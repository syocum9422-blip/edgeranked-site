"""Phase 5.2 conserved simulator validation.

Compares Phase 5.1 independent player simulation against Phase 5.2 conserved
team/game simulation on simulator-realism gates only.

Run: python -m wnba_v2.diagnostics.phase52_validation
"""
from __future__ import annotations

import json
from itertools import combinations

import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.engines.efficiency.rates import build_rate_frame
from wnba_v2.engines.simulation.backtest import EVAL_SEASON, build_spines
from wnba_v2.engines.simulation.conserved_engine import ConservedSimConfig, simulate_game
from wnba_v2.engines.simulation.engine import COMBOS, simulate_player

OUT = C.OUTPUTS / "phase52"
N_SIMS = 1000
BASE_STATS = ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]
ALL_STATS = BASE_STATS + ["pa", "pr", "ra", "pra"]
STAT_MAP = {"points": "points", "rebounds": "reb", "assists": "ast", "threes_made": "fg3m", "steals": "stl", "blocks": "blk"}
PAIR_STATS = [("points", "rebounds"), ("points", "assists"), ("rebounds", "assists")]


def _load_calibration() -> dict:
    path = C.OUTPUTS / "simulation" / "promotion_gate.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text()).get("phase5_1_calibration", {}) or {}


def _actual_value(row: pd.Series, stat: str) -> float:
    if stat in COMBOS:
        return float(sum(row[STAT_MAP[p]] for p in COMBOS[stat]))
    return float(row[STAT_MAP[stat]])


def _summarize_player_draws(records: list[dict], label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    detail = pd.DataFrame(records)
    stat_rows = []
    for stat, s in detail.groupby("stat"):
        actual_var = float(s["actual_value"].var(ddof=1))
        sim_var = float(s["sim_var"].mean())
        stat_rows.append({
            "engine": label, "stat": stat, "n": int(len(s)),
            "mean_error": float(s["mean_error"].mean()), "mae": float(s["abs_error"].mean()),
            "actual_variance": actual_var, "mean_sim_variance": sim_var,
            "variance_ratio_sim_to_actual": sim_var / actual_var if actual_var > 0 else np.nan,
            "p10_coverage_actual_le": float(s["actual_le_p10"].mean()),
            "p50_coverage_actual_le": float(s["actual_le_p50"].mean()),
            "p90_coverage_actual_le": float(s["actual_le_p90"].mean()),
            "central_80_coverage": float(s["inside_p10_p90"].mean()),
            "upper_tail_rate": float(s["actual_ge_p90"].mean()),
            "pred_zero_rate": float(s["pred_zero_rate"].mean()),
            "actual_zero_rate": float(s["actual_zero"].mean()),
            "zero_rate_abs_error": abs(float(s["pred_zero_rate"].mean()) - float(s["actual_zero"].mean())),
        })
    return detail, pd.DataFrame(stat_rows)


def _add_player_records(records: list[dict], row: pd.Series, samples: dict[str, np.ndarray], label: str) -> None:
    for stat in ALL_STATS:
        sample = np.asarray(samples[stat], dtype=float)
        actual = _actual_value(row, stat)
        p10, p50, p90 = np.percentile(sample, [10, 50, 90])
        records.append({
            "engine": label, "date": row["date"], "game_id": row["game_id"], "team": row["team"],
            "player_id": row["player_id"], "player": row["player_name"], "stat": stat,
            "actual_value": actual, "sim_mean": float(sample.mean()), "sim_var": float(sample.var(ddof=1)),
            "p10": float(p10), "p50": float(p50), "p90": float(p90),
            "mean_error": float(sample.mean() - actual), "abs_error": abs(float(sample.mean() - actual)),
            "pred_zero_rate": float(np.mean(np.isclose(sample, 0))), "actual_zero": float(actual == 0),
            "actual_le_p10": float(actual <= p10), "actual_le_p50": float(actual <= p50),
            "actual_le_p90": float(actual <= p90), "actual_ge_p90": float(actual >= p90),
            "inside_p10_p90": float(p10 <= actual <= p90),
        })


def _corr_records(rows: pd.DataFrame, sim_corrs: list[dict], label: str) -> pd.DataFrame:
    out = []
    actual_cols = {"points": "points", "rebounds": "reb", "assists": "ast"}
    cdf = pd.DataFrame(sim_corrs)
    for a, b in PAIR_STATS:
        pair = f"{a}/{b}"
        actual = float(rows[actual_cols[a]].corr(rows[actual_cols[b]]))
        sim = float(cdf[cdf["pair"] == pair]["sim_corr"].mean()) if not cdf.empty else np.nan
        out.append({"engine": label, "pair": pair, "actual_corr": actual, "sim_corr": sim, "abs_error": abs(sim - actual)})
    return pd.DataFrame(out)


def _team_summary(team_records: list[dict], label: str) -> pd.DataFrame:
    detail = pd.DataFrame(team_records)
    out = []
    for metric in ["points", "reb", "ast", "possessions", "starter_minutes", "bench_minutes"]:
        actual = detail[f"{metric}_actual"]
        mean = detail[f"{metric}_sim_mean"]
        var = detail[f"{metric}_sim_var"]
        actual_var = float(actual.var(ddof=1))
        out.append({
            "engine": label, "metric": metric, "n_team_games": int(len(detail)),
            "mean_error": float((mean - actual).mean()), "mae": float((mean - actual).abs().mean()),
            "actual_variance": actual_var, "mean_sim_variance": float(var.mean()),
            "variance_ratio_sim_to_actual": float(var.mean() / actual_var) if actual_var > 0 else np.nan,
            "central_80_coverage": float(detail[f"{metric}_inside_p10_p90"].mean()),
            "upper_tail_rate": float(detail[f"{metric}_actual_ge_p90"].mean()),
        })
    return pd.DataFrame(out), detail


def _team_record(game_id, team, rows_team: pd.DataFrame, samples: dict[str, np.ndarray], latents: dict, actual_team: pd.Series) -> dict:
    rec = {"game_id": game_id, "team": team}
    stats = {
        "points": samples["points"].sum(axis=1),
        "reb": samples["rebounds"].sum(axis=1),
        "ast": samples["assists"].sum(axis=1),
        "possessions": latents["possessions"],
        "starter_minutes": latents["minutes"][:, rows_team["starter"].fillna(0).to_numpy(float) >= 0.5].sum(axis=1),
        "bench_minutes": latents["minutes"][:, rows_team["starter"].fillna(0).to_numpy(float) < 0.5].sum(axis=1),
    }
    actuals = {
        "points": float(actual_team["points"]), "reb": float(actual_team["reb"]), "ast": float(actual_team["ast"]),
        "possessions": float(actual_team["possessions"]),
        "starter_minutes": float(rows_team[rows_team["starter"] == 1]["minutes"].sum()),
        "bench_minutes": float(rows_team[rows_team["starter"] != 1]["minutes"].sum()),
    }
    for metric, sample in stats.items():
        p10, p50, p90 = np.percentile(sample, [10, 50, 90])
        actual = actuals[metric]
        rec.update({
            f"{metric}_actual": actual, f"{metric}_sim_mean": float(sample.mean()),
            f"{metric}_sim_var": float(sample.var(ddof=1)), f"{metric}_mean_error": float(sample.mean() - actual),
            f"{metric}_inside_p10_p90": float(p10 <= actual <= p90),
            f"{metric}_actual_ge_p90": float(actual >= p90),
        })
    return rec


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    rng_old = np.random.default_rng(C.RANDOM_SEED)
    rng_new = np.random.default_rng(C.RANDOM_SEED)
    calib = _load_calibration()
    _, eval_spine = build_spines(EVAL_SEASON)
    rf = build_rate_frame()
    actual_cols = ["player_id", "date", "game_id", "opponent", "starter", "played", "minutes", "points", "reb", "ast", "fg3m", "stl", "blk", "team_poss", "opp_poss"]
    actual = rf[rf["season"] == EVAL_SEASON][actual_cols].copy()
    actual["date"] = pd.to_datetime(actual["date"]).dt.date.astype(str)
    eval_spine = eval_spine.copy()
    eval_spine["date"] = pd.to_datetime(eval_spine["date"]).dt.date.astype(str)
    rows = eval_spine.merge(actual, on=["player_id", "date"], how="inner", suffixes=("", "_actual"))
    rows = rows[rows["played"] == 1].dropna(subset=["minutes", "points", "reb", "ast", "team_poss"]).reset_index(drop=True)

    team_actual = pd.read_csv(C.V2_ROOT / "data" / "team_games" / "team_game_logs.csv")
    team_actual = team_actual[team_actual["season"] == EVAL_SEASON].copy()

    old_records, new_records, old_corrs, new_corrs = [], [], [], []
    old_team_records, new_team_records = [], []
    cfg = ConservedSimConfig(n_sims=N_SIMS)

    for game_id, game_rows in rows.groupby("game_id"):
        conserved = simulate_game(game_rows, N_SIMS, rng_new, calib=calib, cfg=cfg)
        for team, team_rows in game_rows.groupby("team"):
            actual_team_rows = team_actual[(team_actual["game_id"] == game_id) & (team_actual["team"] == team)]
            if actual_team_rows.empty or team not in conserved:
                continue
            team_res = conserved[team]
            team_rows = team_rows.reset_index(drop=True)
            new_team_records.append(_team_record(game_id, team, team_rows, team_res["stats"], team_res["latents"], actual_team_rows.iloc[0]))

            old_team_stats = {s: [] for s in BASE_STATS}
            old_minutes = []
            old_poss = []
            for i, (_, row) in enumerate(team_rows.iterrows()):
                old = simulate_player(row, N_SIMS, rng_old, calib=calib)
                for stat in BASE_STATS:
                    old_team_stats[stat].append(old[stat])
                # approximate old latents the same way old diagnostics did
                plays = rng_old.random(N_SIMS) < float(row["play_prob"])
                mins = np.clip(rng_old.normal(float(row["min_mean"]), max(float(row["min_std"]), 1e-4), N_SIMS), 0, None) * plays
                old_minutes.append(mins)
                old_poss.append(np.clip(rng_old.normal(float(row["team_poss_lag"]), 4.7, N_SIMS), 0, None))
                _add_player_records(old_records, row, old, "phase5_1")
                new_samples = {stat: vals[:, i] for stat, vals in team_res["stats"].items()}
                _add_player_records(new_records, row, new_samples, "phase5_2")
                for a, b in PAIR_STATS:
                    oa, ob = np.asarray(old[a]), np.asarray(old[b])
                    na, nb = np.asarray(new_samples[a]), np.asarray(new_samples[b])
                    old_corrs.append({"pair": f"{a}/{b}", "sim_corr": float(np.corrcoef(oa, ob)[0, 1]) if oa.std() > 0 and ob.std() > 0 else np.nan})
                    new_corrs.append({"pair": f"{a}/{b}", "sim_corr": float(np.corrcoef(na, nb)[0, 1]) if na.std() > 0 and nb.std() > 0 else np.nan})

            old_samples = {
                "points": np.vstack(old_team_stats["points"]).T,
                "rebounds": np.vstack(old_team_stats["rebounds"]).T,
                "assists": np.vstack(old_team_stats["assists"]).T,
            }
            old_latents = {
                "minutes": np.vstack(old_minutes).T,
                "possessions": np.mean(np.vstack(old_poss), axis=0),
            }
            old_team_records.append(_team_record(game_id, team, team_rows, old_samples, old_latents, actual_team_rows.iloc[0]))

    old_detail, old_stat = _summarize_player_draws(old_records, "phase5_1")
    new_detail, new_stat = _summarize_player_draws(new_records, "phase5_2")
    stat = pd.concat([old_stat, new_stat], ignore_index=True)
    corr = pd.concat([_corr_records(rows, old_corrs, "phase5_1"), _corr_records(rows, new_corrs, "phase5_2")], ignore_index=True)
    old_game, old_team_detail = _team_summary(old_team_records, "phase5_1")
    new_game, new_team_detail = _team_summary(new_team_records, "phase5_2")
    game = pd.concat([old_game, new_game], ignore_index=True)

    old_detail.to_csv(OUT / "phase51_player_detail.csv", index=False)
    new_detail.to_csv(OUT / "phase52_player_detail.csv", index=False)
    stat.to_csv(OUT / "stat_realism_comparison.csv", index=False)
    corr.to_csv(OUT / "correlation_realism_comparison.csv", index=False)
    game.to_csv(OUT / "game_realism_comparison.csv", index=False)
    old_team_detail.to_csv(OUT / "phase51_team_detail.csv", index=False)
    new_team_detail.to_csv(OUT / "phase52_team_detail.csv", index=False)

    gates = _gates(stat, corr, game)
    summary = {
        "eval_season": EVAL_SEASON, "n_sims": N_SIMS, "player_rows": int(len(rows)),
        "team_games": int(len(new_team_detail)), "gates": gates,
        "artifacts": {
            "stat": str(OUT / "stat_realism_comparison.csv"),
            "correlation": str(OUT / "correlation_realism_comparison.csv"),
            "game": str(OUT / "game_realism_comparison.csv"),
            "report": str(OUT / "PHASE52_REALISM_REPORT.md"),
        },
    }
    (OUT / "phase52_validation_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    _write_report(summary, stat, corr, game)
    return summary


def _val(df, engine, key_col, key, metric):
    row = df[(df["engine"] == engine) & (df[key_col] == key)]
    return float(row.iloc[0][metric]) if not row.empty else np.nan


def _gates(stat: pd.DataFrame, corr: pd.DataFrame, game: pd.DataFrame) -> dict:
    gates = {}
    gates["starter_minutes_error_materially_reduced"] = abs(_val(game, "phase5_2", "metric", "starter_minutes", "mean_error")) < abs(_val(game, "phase5_1", "metric", "starter_minutes", "mean_error")) * 0.75
    low_stats = ["threes_made", "steals", "blocks"]
    old_zero = stat[(stat.engine == "phase5_1") & (stat.stat.isin(low_stats))]["zero_rate_abs_error"].mean()
    new_zero = stat[(stat.engine == "phase5_2") & (stat.stat.isin(low_stats))]["zero_rate_abs_error"].mean()
    gates["zero_rates_closer_to_actual"] = bool(new_zero < old_zero)
    old_corr = corr[corr.engine == "phase5_1"]["abs_error"].mean()
    new_corr = corr[corr.engine == "phase5_2"]["abs_error"].mean()
    gates["pra_correlations_closer_to_actual"] = bool(new_corr < old_corr)
    old_team_var = game[(game.engine == "phase5_1") & (game.metric.isin(["points", "reb", "ast"]))]["variance_ratio_sim_to_actual"].sub(1).abs().mean()
    new_team_var = game[(game.engine == "phase5_2") & (game.metric.isin(["points", "reb", "ast"]))]["variance_ratio_sim_to_actual"].sub(1).abs().mean()
    gates["team_total_variance_reduced"] = bool(new_team_var < old_team_var)
    tail_stats = ["blocks", "threes_made"]
    old_tail = stat[(stat.engine == "phase5_1") & (stat.stat.isin(tail_stats))]["upper_tail_rate"].sub(0.10).abs().mean()
    new_tail = stat[(stat.engine == "phase5_2") & (stat.stat.isin(tail_stats))]["upper_tail_rate"].sub(0.10).abs().mean()
    gates["block_three_upper_tails_improved"] = bool(new_tail < old_tail)
    combo_stats = ["pa", "pr", "pra"]
    old_cov = stat[(stat.engine == "phase5_1") & (stat.stat.isin(combo_stats))]["central_80_coverage"].sub(0.80).abs().mean()
    new_cov = stat[(stat.engine == "phase5_2") & (stat.stat.isin(combo_stats))]["central_80_coverage"].sub(0.80).abs().mean()
    gates["pa_pr_pra_coverage_improved"] = bool(new_cov < old_cov)
    gates["all_pass"] = all(gates.values())
    gates["metrics"] = {
        "zero_abs_error_old": float(old_zero), "zero_abs_error_new": float(new_zero),
        "corr_abs_error_old": float(old_corr), "corr_abs_error_new": float(new_corr),
        "team_var_abs_error_old": float(old_team_var), "team_var_abs_error_new": float(new_team_var),
        "block_three_tail_abs_error_old": float(old_tail), "block_three_tail_abs_error_new": float(new_tail),
        "combo_coverage_abs_error_old": float(old_cov), "combo_coverage_abs_error_new": float(new_cov),
    }
    return gates


def _fmt(x):
    if pd.isna(x):
        return "NA"
    return f"{float(x):.3f}"


def _write_report(summary: dict, stat: pd.DataFrame, corr: pd.DataFrame, game: pd.DataFrame) -> None:
    def pivot_lines(df, key_col, metrics):
        lines = []
        for key in sorted(df[key_col].unique()):
            old = df[(df.engine == "phase5_1") & (df[key_col] == key)].iloc[0]
            new = df[(df.engine == "phase5_2") & (df[key_col] == key)].iloc[0]
            vals = []
            for m in metrics:
                vals.extend([_fmt(old[m]), _fmt(new[m])])
            lines.append(f"| {key} | " + " | ".join(vals) + " |")
        return "\n".join(lines)

    stat_lines = pivot_lines(stat, "stat", ["mean_error", "variance_ratio_sim_to_actual", "central_80_coverage", "pred_zero_rate", "actual_zero_rate", "upper_tail_rate"])
    corr_lines = pivot_lines(corr, "pair", ["actual_corr", "sim_corr", "abs_error"])
    game_lines = pivot_lines(game, "metric", ["mean_error", "variance_ratio_sim_to_actual", "central_80_coverage", "upper_tail_rate"])
    gates = summary["gates"]
    gate_lines = "\n".join(f"- {k}: {v}" for k, v in gates.items() if k != "metrics")
    metric_lines = "\n".join(f"- {k}: {_fmt(v)}" for k, v in gates["metrics"].items())
    md = f"""# WNBA V2 Phase 5.2 Conserved Simulator Validation

Scope: simulator realism only. No deployment, serving, selection, or promotion analysis.

Rows: {summary['player_rows']} player rows, {summary['team_games']} team-games, {summary['n_sims']} draws.

## Validation Gates

{gate_lines}

## Gate Metrics

{metric_lines}

## Stat Realism Comparison

Each metric is shown as Phase 5.1 / Phase 5.2.

| Stat | Mean Err Old | Mean Err New | Var Ratio Old | Var Ratio New | Central80 Old | Central80 New | Pred Zero Old | Pred Zero New | Actual Zero Old | Actual Zero New | Upper Tail Old | Upper Tail New |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{stat_lines}

## Correlation Realism Comparison

| Pair | Actual Old | Actual New | Sim Old | Sim New | Abs Err Old | Abs Err New |
|---|---:|---:|---:|---:|---:|---:|
{corr_lines}

## Game Realism Comparison

| Metric | Mean Err Old | Mean Err New | Var Ratio Old | Var Ratio New | Central80 Old | Central80 New | Upper Tail Old | Upper Tail New |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{game_lines}

## Remaining Simulator Issues

- Phase 5.2 conserves team minutes and team stat totals, but its team point/rebound/assist total variances now depend heavily on the team-total residual SD constants and need final calibration on a training split.
- Starter and bench minutes are constrained to 200 total minutes, but game-state behavior is still generated from an unconditional margin latent. It should eventually use a score/margin process instead of a one-shot margin draw.
- Low-count stat zero inflation and overdispersion are now explicit, but parameters are heuristic and should be fit by player role/minute band.
- Shared PRA latent improves the architecture, but loadings should be estimated from residual covariance rather than fixed constants.
"""
    (OUT / "PHASE52_REALISM_REPORT.md").write_text(md)


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
