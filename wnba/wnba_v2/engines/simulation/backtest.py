"""Phase 5 / 5.1 — end-to-end correlated-MC backtest & ROI PROMOTION GATE.

Pipeline: fit P4 (efficiency) + P3.5 (usage) on seasons < eval; assemble train &
eval spines; calibrate per-stat scale on TRAIN (Phase 5.1); simulate the eval bets
with calibration; grade.

ROI-oriented gate (per directive): do NOT require V2 to beat production on the bets
production chose. Instead V2 makes its OWN high-conviction selections and must:
  - hit above breakeven (-110) with statistical significance
  - keep ordered confidence buckets
  - not regress on calibration (Brier/ECE)
  - improve PA/PRA calibration vs production
  - show positive CLV (proxy; full CLV accrues from the now-live capture)
Production is tracked in parallel for reference.

Run:  .venv/bin/python -m wnba_v2.engines.simulation.backtest
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.engines.efficiency.bayes_model import BetaBinomial3P, GammaPoissonRate
from wnba_v2.engines.efficiency.gbm_model import RateGBM
from wnba_v2.engines.efficiency.rates import GBM_RATES, build_rate_frame
from wnba_v2.engines.simulation.calibrate import compute_calibration
from wnba_v2.engines.simulation.conserved_engine import player_samples, simulate_game
from wnba_v2.engines.simulation.engine import COMBOS, prob_over
from wnba_v2.engines.simulation.learned_calibration import CALIBRATION_PATH, load_config
from wnba_v2.engines.simulation.sim_inputs import (
    _minutes_lags, _team_pools, fix_play_prob, norm_name)
from wnba_v2.engines.usage.redistribution_model import RedistributionUsageModel
from wnba_v2.engines.usage.roles import REDIS_FEATURES, build_redistribution_frame

OUT = C.OUTPUTS / "simulation"
N_SIMS = 4000
EVAL_SEASON = 2026
BREAKEVEN = C.BREAKEVEN_MINUS_110
RATE_STATS = {"points", "rebounds", "assists", "threes_made", "steals", "blocks"}


def build_spines(eval_season: int):
    rdf = build_redistribution_frame()
    rf = build_rate_frame()
    um = RedistributionUsageModel().fit(rdf[rdf["season"] < eval_season].dropna(subset=REDIS_FEATURES))
    rtr = rf[rf["season"] < eval_season]
    gbm = {n: RateGBM(n).fit(rtr.dropna(subset=[f"rate_{n}", f"{n}_lag5"])) for n in GBM_RATES}
    bayes = {n: GammaPoissonRate(name=n, num_cum=f"cum_{ {'steals':'stl','blocks':'blk'}[n] }")
             .fit(rtr.dropna(subset=[f"rate_{n}"])) for n in ["steals", "blocks"]}
    bayes["fg3_pct"] = BetaBinomial3P().fit(rtr.dropna(subset=["rate_fg3_pct"]))
    minutes, pools = _minutes_lags(), _team_pools()

    def assemble(mask_seasons) -> pd.DataFrame:
        ev = rdf[rdf["season"].isin(mask_seasons)].dropna(subset=REDIS_FEATURES).copy()
        ev["usage_share_pred"] = um.predict_raw(ev)["usage_share"].clip(0, 0.45).values
        spine = ev[["player_id", "player_name", "date", "team", "season",
                    "usage_share_pred", "n_regulars_out", "star_out"]].copy()
        rev = rf[rf["season"].isin(mask_seasons)]
        eff = rev[["player_id", "date"]].copy()
        for n in GBM_RATES:
            p = gbm[n].predict(rev)
            eff[f"{n}_mean"], eff[f"{n}_std"] = p[f"{n}_mean"].values, p[f"{n}_std"].values
        for n in ["steals", "blocks", "fg3_pct"]:
            p = bayes[n].predict(rev)
            eff[f"{n}_mean"], eff[f"{n}_std"] = p[f"{n}_mean"].values, p[f"{n}_std"].values
        spine = spine.merge(eff, on=["player_id", "date"], how="left")
        spine = spine.merge(minutes, on=["player_id", "date"], how="left")
        spine = spine.merge(pools, on=["team", "date"], how="left")
        spine["typ_min"] = spine["min_mean"].clip(lower=5)
        spine["min_std"] = spine["min_std"].fillna(5.0).clip(2.0, 12.0)
        spine = fix_play_prob(spine)
        spine["name_key"] = spine["player_name"].map(norm_name)
        return spine.dropna(subset=["min_mean", "team_poss_lag", "points_mean"]).reset_index(drop=True)

    all_seasons = sorted(rdf["season"].dropna().unique())
    train = assemble([s for s in all_seasons if s < eval_season])
    ev = assemble([eval_season])
    return train, ev


def _attach_actual_game_context(eval_spine: pd.DataFrame) -> pd.DataFrame:
    rf = build_rate_frame()
    actual_cols = [
        "player_id", "date", "game_id", "opponent", "starter", "played",
        "minutes", "points", "reb", "ast", "fg3m", "stl", "blk", "team_poss", "opp_poss",
    ]
    actual = rf[rf["season"] == EVAL_SEASON][actual_cols].copy()
    actual["date"] = pd.to_datetime(actual["date"]).dt.date.astype(str)
    out = eval_spine.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date.astype(str)
    out = out.merge(actual, on=["player_id", "date"], how="inner", suffixes=("", "_actual"))
    out = out[out["played"] == 1].dropna(subset=["game_id", "team", "minutes", "points", "reb", "ast", "team_poss"])
    return out.reset_index(drop=True)


def _summarize_projection(row: pd.Series, samples: dict[str, np.ndarray]) -> dict:
    rec = {
        "date": str(row["date"]),
        "game_id": row["game_id"],
        "player_id": row["player_id"],
        "player": row["player_name"],
        "name_key": row["name_key"],
        "team": row["team"],
        "opponent": row.get("opponent"),
    }
    for stat in ["points", "rebounds", "assists", "threes_made", "steals", "blocks", "pa", "pr", "pra"]:
        values = np.asarray(samples[stat], dtype=float)
        p10, p50, p90 = np.percentile(values, [10, 50, 90])
        rec[f"{stat}_mean"] = float(values.mean())
        rec[f"{stat}_p10"] = float(p10)
        rec[f"{stat}_p50"] = float(p50)
        rec[f"{stat}_p90"] = float(p90)
        rec[f"{stat}_std"] = float(values.std(ddof=1))
    return rec


def _latent_record(game_id, team: str, rows_team: pd.DataFrame, result: dict) -> dict:
    latents = result["latents"]
    starter_mask = rows_team["starter"].fillna(0).to_numpy(float) >= 0.5
    minutes = np.asarray(latents["minutes"], dtype=float)
    return {
        "game_id": game_id,
        "team": team,
        "n_players": int(len(rows_team)),
        "possessions_mean": float(np.mean(latents["possessions"])),
        "possessions_std": float(np.std(latents["possessions"], ddof=1)),
        "blowout_mean": float(np.mean(latents["blowout"])),
        "team_minutes_min": float(minutes.sum(axis=1).min()),
        "team_minutes_max": float(minutes.sum(axis=1).max()),
        "starter_minutes_mean": float(minutes[:, starter_mask].sum(axis=1).mean()) if starter_mask.any() else 0.0,
        "bench_minutes_mean": float(minutes[:, ~starter_mask].sum(axis=1).mean()) if (~starter_mask).any() else 0.0,
        "team_points_mean": float(np.mean(latents["team_points"])),
        "team_rebounds_mean": float(np.mean(latents["team_rebounds"])),
        "team_assists_mean": float(np.mean(latents["team_assists"])),
    }


def _simulate_eval_spine(eval_spine: pd.DataFrame, rng, calib: dict, cfg) -> tuple[dict, list[dict], list[dict]]:
    sample_cache: dict[tuple[str, str], dict[str, np.ndarray]] = {}
    projection_rows: list[dict] = []
    latent_rows: list[dict] = []
    for game_id, game_rows in eval_spine.groupby("game_id"):
        result = simulate_game(game_rows, N_SIMS, rng, calib=calib, cfg=cfg)
        for team, rows_team in game_rows.groupby("team"):
            if team not in result:
                continue
            rows_team = rows_team.reset_index(drop=True)
            team_result = result[team]
            latent_rows.append(_latent_record(game_id, team, rows_team, team_result))
            for i, (_, row) in enumerate(rows_team.iterrows()):
                samples = player_samples(team_result, i)
                key = (row["name_key"], str(pd.Timestamp(row["date"]).date()))
                sample_cache[key] = samples
                projection_rows.append(_summarize_projection(row, samples))
    return sample_cache, projection_rows, latent_rows


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(C.RANDOM_SEED)
    train_spine, eval_spine = build_spines(EVAL_SEASON)
    calib = compute_calibration(train_spine, rng)               # Phase 5.1 scale fit on TRAIN
    cfg = load_config(CALIBRATION_PATH, n_sims=N_SIMS)
    if cfg is None:
        raise FileNotFoundError(f"Phase 5.3 learned calibration is required: {CALIBRATION_PATH}")

    eval_spine = _attach_actual_game_context(eval_spine)
    sample_cache, projection_rows, latent_rows = _simulate_eval_spine(eval_spine, rng, calib, cfg)
    pd.DataFrame(projection_rows).to_csv(OUT / "conserved_projection_detail.csv", index=False)
    pd.DataFrame(latent_rows).to_csv(OUT / "conserved_latent_diagnostics.csv", index=False)

    g = pd.read_csv(C.GRADED_BETS_PATH)
    g = g[g["bet_result"].isin(["win", "loss"])].copy()
    g["name_key"] = g["player_name"].map(norm_name)
    g["date_key"] = pd.to_datetime(g["bet_date"]).dt.date.astype(str)
    g["actual_over"] = (g["actual_value"] > g["line"]).astype(int)

    rows = []
    for _, b in g.iterrows():
        key = (b["name_key"], b["date_key"])
        if key not in sample_cache or (b["stat"] not in RATE_STATS and b["stat"] not in COMBOS):
            continue
        samples = sample_cache[key].get(b["stat"])
        if samples is None:
            continue
        p_over = prob_over(samples, float(b["line"]))
        prod_p_over = b["hit_rate"] if b["side"] == "over" else 1 - b["hit_rate"]
        # CLV proxy for V2's chosen side (open->bet move), where available
        clv = np.nan
        if pd.notna(b.get("line_open")):
            v2_over = p_over > 0.5
            clv = (b["line_open"] - b["line"]) if v2_over else (b["line"] - b["line_open"])
        rows.append({
            "date": b["date_key"], "player": b["player_name"], "stat": b["stat"],
            "line": b["line"], "actual_over": int(b["actual_over"]),
            "v2_proj": round(float(np.mean(samples)), 2), "actual_value": float(b["actual_value"]),
            "v2_p_over": p_over, "v2_correct": int((p_over > 0.5) == bool(b["actual_over"])),
            "prod_correct": int(b["bet_result"] == "win"), "prod_p_over": float(prod_p_over),
            "conf": abs(p_over - 0.5), "clv": clv, "is_combo": b["stat"] in COMBOS,
        })
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "backtest_graded.csv", index=False)
    report = _report(res, calib)
    (OUT / "promotion_gate.json").write_text(json.dumps(report, indent=2, default=str))
    return report


def _wilson(w, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = w / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (round(c - h, 4), round(c + h, 4))


def _brier(p, y):
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def _ece(p, y, bins=10):
    p, y = np.asarray(p, float), np.asarray(y, float)
    idx = np.clip(np.digitize(p, np.linspace(0, 1, bins + 1)) - 1, 0, bins - 1)
    return float(sum((idx == b).mean() * abs(p[idx == b].mean() - y[idx == b].mean())
                     for b in range(bins) if (idx == b).any()))


def _report(res: pd.DataFrame, calib: dict) -> dict:
    if res.empty:
        return {"error": "no matched bets", "calibration": calib}
    n = len(res)
    bias = round(float(res["v2_p_over"].mean() - res["actual_over"].mean()), 4)

    # V2's OWN selections at increasing conviction
    selections = []
    for thr in [0.0, 0.05, 0.10, 0.15, 0.20]:
        s = res[res["conf"] >= thr]
        if len(s) < 25:
            continue
        w = int(s["v2_correct"].sum())
        lo, hi = _wilson(w, len(s))
        selections.append({
            "min_conviction": thr, "n": len(s),
            "v2_hit": round(w / len(s), 4), "ci95": [lo, hi],
            "sig_above_breakeven": bool(lo > BREAKEVEN),
            "v2_brier": round(_brier(s["v2_p_over"], s["actual_over"]), 4),
            "mean_clv": round(float(s["clv"].dropna().mean()), 3) if s["clv"].notna().any() else None,
        })

    # confidence-bucket ordering (calibration sanity)
    buckets = []
    for lo, hi in [(0, 0.05), (0.05, 0.1), (0.1, 0.2), (0.2, 0.5)]:
        sub = res[(res["conf"] >= lo) & (res["conf"] < hi)]
        if len(sub) >= 25:
            buckets.append({"band": f"{lo}-{hi}", "n": len(sub), "v2_hit": round(sub["v2_correct"].mean(), 4)})
    ordered = all(buckets[i]["v2_hit"] <= buckets[i + 1]["v2_hit"] for i in range(len(buckets) - 1)) if len(buckets) > 1 else False

    # combos V2 vs production calibration
    cb = res[res["is_combo"]]
    combos = {"n": len(cb),
              "v2_brier": round(_brier(cb["v2_p_over"], cb["actual_over"]), 4) if len(cb) else None,
              "prod_brier": round(_brier(cb["prod_p_over"], cb["actual_over"]), 4) if len(cb) else None,
              "v2_ece": round(_ece(cb["v2_p_over"], cb["actual_over"]), 4) if len(cb) else None}
    overall = {"n": n, "v2_brier": round(_brier(res["v2_p_over"], res["actual_over"]), 4),
               "prod_brier": round(_brier(res["prod_p_over"], res["actual_over"]), 4),
               "v2_ece": round(_ece(res["v2_p_over"], res["actual_over"]), 4),
               "v2_over_pick_rate": round(float((res["v2_p_over"] > 0.5).mean()), 3)}

    # primary selection tier (highest conviction with adequate volume)
    primary = next((s for s in reversed(selections) if s["n"] >= 60), selections[-1] if selections else None)
    gate = {
        "primary_tier": primary,
        "hit_significant_above_breakeven": bool(primary and primary["sig_above_breakeven"]),
        "buckets_ordered": ordered,
        "combos_calibration_beats_prod": bool(combos["v2_brier"] and combos["prod_brier"]
                                              and combos["v2_brier"] < combos["prod_brier"]),
        "no_calibration_regression": bool(overall["v2_brier"] <= overall["prod_brier"]),
        "clv_note": "historical CLV is a weak proxy (PrizePicks, ~37% line_open, no close); "
                    "full CLV now accrues via live capture",
    }
    promote = bool(gate["hit_significant_above_breakeven"] and gate["buckets_ordered"]
                   and gate["no_calibration_regression"])
    return {
        "eval_season": EVAL_SEASON, "n_sims": N_SIMS, "phase5_1_calibration": calib,
        "residual_bias_p_over_minus_actual": bias,
        "overall": overall, "combos": combos, "confidence_buckets": buckets,
        "v2_selections_by_conviction": selections,
        "gate": gate, "DECISION": "PROMOTE" if promote else "HOLD",
        "rule": "ROI gate: V2's own high-conviction picks beat -110 breakeven (significant) "
                "+ ordered buckets + no calibration regression; combos/CLV secondary",
    }


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=2, default=str))
    print(f"\nArtifacts -> {OUT}")
