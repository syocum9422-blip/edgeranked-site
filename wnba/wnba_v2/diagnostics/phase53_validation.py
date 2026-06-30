"""Phase 5.3 learned simulator calibration validation.

Fits Phase 5.3 parameters on walk-forward training seasons and validates the
learned config out-of-sample against the tuned Phase 5.2 conserved simulator.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.engines.efficiency.rates import build_rate_frame
from wnba_v2.engines.simulation.backtest import EVAL_SEASON, build_spines
from wnba_v2.engines.simulation.conserved_engine import ConservedSimConfig, simulate_game
from wnba_v2.engines.simulation.engine import COMBOS
from wnba_v2.engines.simulation.learned_calibration import CALIBRATION_PATH, fit

OUT = C.OUTPUTS / "phase53"
N_SIMS = 1000
BASE_STATS = ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]
ALL_STATS = BASE_STATS + ["pa", "pr", "ra", "pra"]
STAT_MAP = {"points": "points", "rebounds": "reb", "assists": "ast", "threes_made": "fg3m", "steals": "stl", "blocks": "blk"}
PAIR_STATS = [("points", "rebounds"), ("points", "assists"), ("rebounds", "assists")]


def _load_mean_calibration() -> dict:
    path = C.OUTPUTS / "simulation" / "promotion_gate.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text()).get("phase5_1_calibration", {}) or {}


def _actual_value(row: pd.Series, stat: str) -> float:
    if stat in COMBOS:
        return float(sum(row[STAT_MAP[p]] for p in COMBOS[stat]))
    return float(row[STAT_MAP[stat]])


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


def _summarize_player(records: list[dict], label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    detail = pd.DataFrame(records)
    rows = []
    for stat, s in detail.groupby("stat"):
        actual_var = float(s["actual_value"].var(ddof=1))
        sim_var = float(s["sim_var"].mean())
        rows.append({
            "engine": label, "stat": stat, "n": int(len(s)),
            "mean_error": float(s["mean_error"].mean()), "mae": float(s["abs_error"].mean()),
            "actual_variance": actual_var, "mean_sim_variance": sim_var,
            "variance_ratio_sim_to_actual": sim_var / actual_var if actual_var > 0 else np.nan,
            "p10_error": abs(float(s["actual_le_p10"].mean()) - 0.10),
            "p50_error": abs(float(s["actual_le_p50"].mean()) - 0.50),
            "p90_error": abs(float(s["actual_le_p90"].mean()) - 0.90),
            "central_80_coverage": float(s["inside_p10_p90"].mean()),
            "coverage_error": abs(float(s["inside_p10_p90"].mean()) - 0.80),
            "upper_tail_rate": float(s["actual_ge_p90"].mean()),
            "pred_zero_rate": float(s["pred_zero_rate"].mean()),
            "actual_zero_rate": float(s["actual_zero"].mean()),
            "zero_rate_abs_error": abs(float(s["pred_zero_rate"].mean()) - float(s["actual_zero"].mean())),
        })
    return detail, pd.DataFrame(rows)


def _team_record(game_id, team, rows_team: pd.DataFrame, result: dict, actual_team: pd.Series) -> dict:
    latents, samples = result["latents"], result["stats"]
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
            f"{metric}_coverage_error": abs(float(p10 <= actual <= p90) - 0.80),
            f"{metric}_inside_p10_p90": float(p10 <= actual <= p90),
            f"{metric}_actual_ge_p90": float(actual >= p90),
        })
    return rec


def _summarize_team(records: list[dict], label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    detail = pd.DataFrame(records)
    rows = []
    for metric in ["points", "reb", "ast", "possessions", "starter_minutes", "bench_minutes"]:
        actual = detail[f"{metric}_actual"]
        mean = detail[f"{metric}_sim_mean"]
        var = detail[f"{metric}_sim_var"]
        actual_var = float(actual.var(ddof=1))
        rows.append({
            "engine": label, "metric": metric, "n_team_games": int(len(detail)),
            "mean_error": float((mean - actual).mean()), "mae": float((mean - actual).abs().mean()),
            "actual_variance": actual_var, "mean_sim_variance": float(var.mean()),
            "variance_ratio_sim_to_actual": float(var.mean() / actual_var) if actual_var > 0 else np.nan,
            "variance_ratio_error": abs(float(var.mean() / actual_var) - 1.0) if actual_var > 0 else np.nan,
            "central_80_coverage": float(detail[f"{metric}_inside_p10_p90"].mean()),
            "upper_tail_rate": float(detail[f"{metric}_actual_ge_p90"].mean()),
        })
    return detail, pd.DataFrame(rows)


def _corr_summary(records: list[dict], rows: pd.DataFrame, label: str) -> pd.DataFrame:
    actual_cols = {"points": "points", "rebounds": "reb", "assists": "ast"}
    cdf = pd.DataFrame(records)
    out = []
    for a, b in PAIR_STATS:
        pair = f"{a}/{b}"
        actual = float(rows[actual_cols[a]].corr(rows[actual_cols[b]]))
        sim = float(cdf[cdf["pair"] == pair]["sim_corr"].mean())
        out.append({"engine": label, "pair": pair, "actual_corr": actual, "sim_corr": sim, "abs_error": abs(sim - actual)})
    return pd.DataFrame(out)


def _eval_config(label: str, cfg: ConservedSimConfig, rows: pd.DataFrame, team_actual: pd.DataFrame, calib: dict, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    player_records, team_records, corr_records = [], [], []
    for game_id, game_rows in rows.groupby("game_id"):
        result = simulate_game(game_rows, N_SIMS, rng, calib=calib, cfg=cfg)
        for team, team_rows in game_rows.groupby("team"):
            actual_team_rows = team_actual[(team_actual["game_id"] == game_id) & (team_actual["team"] == team)]
            if actual_team_rows.empty or team not in result:
                continue
            team_rows = team_rows.reset_index(drop=True)
            team_result = result[team]
            team_records.append(_team_record(game_id, team, team_rows, team_result, actual_team_rows.iloc[0]))
            for i, (_, row) in enumerate(team_rows.iterrows()):
                samples = {stat: values[:, i] for stat, values in team_result["stats"].items()}
                _add_player_records(player_records, row, samples, label)
                for a, b in PAIR_STATS:
                    sa, sb = np.asarray(samples[a]), np.asarray(samples[b])
                    corr = float(np.corrcoef(sa, sb)[0, 1]) if sa.std() > 0 and sb.std() > 0 else np.nan
                    corr_records.append({"pair": f"{a}/{b}", "sim_corr": corr})
    player_detail, stat = _summarize_player(player_records, label)
    team_detail, game = _summarize_team(team_records, label)
    corr = _corr_summary(corr_records, rows, label)
    return {"player_detail": player_detail, "stat": stat, "team_detail": team_detail, "game": game, "corr": corr}


def _aggregate_scores(stat: pd.DataFrame, corr: pd.DataFrame, game: pd.DataFrame) -> dict:
    low = ["threes_made", "steals", "blocks"]
    combos = ["pa", "pr", "pra"]
    core = ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]
    team = ["points", "reb", "ast"]
    return {
        "zero_rate_error": float(stat[stat.stat.isin(low)]["zero_rate_abs_error"].mean()),
        "variance_ratio_error": float(stat[stat.stat.isin(core)]["variance_ratio_sim_to_actual"].sub(1).abs().mean()),
        "quantile_coverage_error": float(stat[stat.stat.isin(core)][["p10_error", "p50_error", "p90_error"]].mean().mean()),
        "pra_corr_error": float(corr["abs_error"].mean()),
        "team_total_variance_error": float(game[game.metric.isin(team)]["variance_ratio_error"].mean()),
        "combo_coverage_error": float(stat[stat.stat.isin(combos)]["coverage_error"].mean()),
        "core_mean_abs_error": float(stat[stat.stat.isin(core)]["mean_error"].abs().mean()),
        "combo_mean_abs_error": float(stat[stat.stat.isin(combos)]["mean_error"].abs().mean()),
    }


def _accept(base: dict, learned: dict) -> dict:
    realism_keys = [
        "zero_rate_error",
        "variance_ratio_error",
        "quantile_coverage_error",
        "pra_corr_error",
        "team_total_variance_error",
        "combo_coverage_error",
    ]
    base_composite = sum(base[k] for k in realism_keys)
    learned_composite = sum(learned[k] for k in realism_keys)
    checks = {
        "composite_realism_improved": learned_composite < base_composite,
        "zero_rate_error_improved": learned["zero_rate_error"] < base["zero_rate_error"],
        "variance_ratio_error_improved": learned["variance_ratio_error"] < base["variance_ratio_error"],
        "quantile_coverage_no_material_regression": learned["quantile_coverage_error"] <= base["quantile_coverage_error"] + 0.002,
        "pra_corr_no_material_regression": learned["pra_corr_error"] <= base["pra_corr_error"] + 0.002,
        "team_total_variance_error_improved": learned["team_total_variance_error"] < base["team_total_variance_error"],
        "combo_coverage_no_material_regression": learned["combo_coverage_error"] <= base["combo_coverage_error"] + 0.001,
        "core_means_not_broken": learned["core_mean_abs_error"] <= max(base["core_mean_abs_error"] * 1.10, base["core_mean_abs_error"] + 0.05),
        "combo_means_not_broken": learned["combo_mean_abs_error"] <= max(base["combo_mean_abs_error"] * 1.10, base["combo_mean_abs_error"] + 0.10),
    }
    checks["base_composite_realism_error"] = base_composite
    checks["learned_composite_realism_error"] = learned_composite
    checks["all_pass"] = all(v for k, v in checks.items() if isinstance(v, bool))
    return checks


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    candidate = fit(EVAL_SEASON)
    learned_cfg = ConservedSimConfig.from_mapping(candidate["parameters"], n_sims=N_SIMS)
    base_cfg = ConservedSimConfig(n_sims=N_SIMS)
    calib = _load_mean_calibration()

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

    base = _eval_config("phase5_2", base_cfg, rows, team_actual, calib, C.RANDOM_SEED)
    learned = _eval_config("phase5_3", learned_cfg, rows, team_actual, calib, C.RANDOM_SEED)

    stat = pd.concat([base["stat"], learned["stat"]], ignore_index=True)
    corr = pd.concat([base["corr"], learned["corr"]], ignore_index=True)
    game = pd.concat([base["game"], learned["game"]], ignore_index=True)
    stat.to_csv(OUT / "phase53_stat_comparison.csv", index=False)
    corr.to_csv(OUT / "phase53_correlation_comparison.csv", index=False)
    game.to_csv(OUT / "phase53_game_comparison.csv", index=False)
    base["player_detail"].to_csv(OUT / "phase52_player_detail.csv", index=False)
    learned["player_detail"].to_csv(OUT / "phase53_player_detail.csv", index=False)
    base["team_detail"].to_csv(OUT / "phase52_team_detail.csv", index=False)
    learned["team_detail"].to_csv(OUT / "phase53_team_detail.csv", index=False)

    base_scores = _aggregate_scores(base["stat"], base["corr"], base["game"])
    learned_scores = _aggregate_scores(learned["stat"], learned["corr"], learned["game"])
    checks = _accept(base_scores, learned_scores)
    accepted = bool(checks["all_pass"])
    if accepted:
        payload = {**candidate, "accepted": True, "validation_scores": {"phase5_2": base_scores, "phase5_3": learned_scores}, "acceptance_checks": checks}
        CALIBRATION_PATH.write_text(json.dumps(payload, indent=2, default=str))
    else:
        payload = {**candidate, "accepted": False, "validation_scores": {"phase5_2": base_scores, "phase5_3": learned_scores}, "acceptance_checks": checks}
        (OUT / "phase53_rejected_calibration.json").write_text(json.dumps(payload, indent=2, default=str))

    summary = {
        "eval_season": EVAL_SEASON, "n_sims": N_SIMS, "player_rows": int(len(rows)),
        "team_games": int(len(learned["team_detail"])), "accepted": accepted,
        "acceptance_checks": checks, "scores": {"phase5_2": base_scores, "phase5_3": learned_scores},
        "calibration_path": str(CALIBRATION_PATH) if accepted else None,
        "artifacts": {
            "stat": str(OUT / "phase53_stat_comparison.csv"),
            "correlation": str(OUT / "phase53_correlation_comparison.csv"),
            "game": str(OUT / "phase53_game_comparison.csv"),
            "report": str(OUT / "PHASE53_LEARNED_CALIBRATION_REPORT.md"),
        },
    }
    (OUT / "phase53_validation_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    _write_report(summary, stat, corr, game, candidate)
    return summary


def _fmt(x):
    if pd.isna(x):
        return "NA"
    return f"{float(x):.4f}"


def _write_report(summary: dict, stat: pd.DataFrame, corr: pd.DataFrame, game: pd.DataFrame, candidate: dict) -> None:
    checks = "\n".join(f"- {k}: {v}" for k, v in summary["acceptance_checks"].items())
    scores = "\n".join(f"- {k}: phase5_2={_fmt(summary['scores']['phase5_2'][k])}, phase5_3={_fmt(summary['scores']['phase5_3'][k])}" for k in summary["scores"]["phase5_2"])
    params = json.dumps(candidate["parameters"], indent=2)
    stat_lines = []
    for stat_name in sorted(stat.stat.unique()):
        b = stat[(stat.engine == "phase5_2") & (stat.stat == stat_name)].iloc[0]
        l = stat[(stat.engine == "phase5_3") & (stat.stat == stat_name)].iloc[0]
        stat_lines.append(f"| {stat_name} | {_fmt(b.mean_error)} | {_fmt(l.mean_error)} | {_fmt(b.variance_ratio_sim_to_actual)} | {_fmt(l.variance_ratio_sim_to_actual)} | {_fmt(b.coverage_error)} | {_fmt(l.coverage_error)} | {_fmt(b.zero_rate_abs_error)} | {_fmt(l.zero_rate_abs_error)} |")
    corr_lines = []
    for pair in sorted(corr.pair.unique()):
        b = corr[(corr.engine == "phase5_2") & (corr.pair == pair)].iloc[0]
        l = corr[(corr.engine == "phase5_3") & (corr.pair == pair)].iloc[0]
        corr_lines.append(f"| {pair} | {_fmt(b.actual_corr)} | {_fmt(b.sim_corr)} | {_fmt(l.sim_corr)} | {_fmt(b.abs_error)} | {_fmt(l.abs_error)} |")
    game_lines = []
    for metric in sorted(game.metric.unique()):
        b = game[(game.engine == "phase5_2") & (game.metric == metric)].iloc[0]
        l = game[(game.engine == "phase5_3") & (game.metric == metric)].iloc[0]
        game_lines.append(f"| {metric} | {_fmt(b.mean_error)} | {_fmt(l.mean_error)} | {_fmt(b.variance_ratio_error)} | {_fmt(l.variance_ratio_error)} | {_fmt(b.central_80_coverage)} | {_fmt(l.central_80_coverage)} |")
    md = f"""# WNBA V2 Phase 5.3 Learned Simulator Calibration

Scope: simulator realism only. Phase 5.3 keeps the Phase 5.2 conserved architecture and learns parameters from seasons before {summary['eval_season']}.

Rows: {summary['player_rows']} player rows, {summary['team_games']} team-games, {summary['n_sims']} draws.

Accepted: **{summary['accepted']}**

## Acceptance Checks

{checks}

## Aggregate Scores

{scores}

## Learned Parameters

```json
{params}
```

## Stat Comparison

| Stat | Mean Err 5.2 | Mean Err 5.3 | Var Ratio 5.2 | Var Ratio 5.3 | Coverage Err 5.2 | Coverage Err 5.3 | Zero Err 5.2 | Zero Err 5.3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(stat_lines)}

## Correlation Comparison

| Pair | Actual | Sim 5.2 | Sim 5.3 | Abs Err 5.2 | Abs Err 5.3 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(corr_lines)}

## Game Comparison

| Metric | Mean Err 5.2 | Mean Err 5.3 | Var Err 5.2 | Var Err 5.3 | Central80 5.2 | Central80 5.3 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(game_lines)}
"""
    (OUT / "PHASE53_LEARNED_CALIBRATION_REPORT.md").write_text(md)


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
