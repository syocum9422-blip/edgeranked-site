"""Phase 5.4 — production integration for the conserved WNBA V2 simulator.

This module makes the Phase 5.3 learned conserved simulator the daily V2
projection engine. It is intentionally narrow: no serving, promotion, selection,
or challenger-model logic lives here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.diagnostics import phase53_validation
from wnba_v2.engines.simulation.calibrate import compute_calibration
from wnba_v2.engines.simulation.conserved_engine import player_samples, simulate_game
from wnba_v2.engines.simulation.learned_calibration import CALIBRATION_PATH, load_config
from wnba_v2.engines.simulation.backtest import N_SIMS, build_spines
from wnba_v2.engines.simulation.sim_inputs import fix_play_prob, norm_name

OUT = C.OUTPUTS / "phase54"
TODAY_FEATURES = C.PROD_ROOT / "data" / "processed" / "wnba_today_features.csv"
PRODUCTION_PROJECTIONS = C.PROD_ROOT / "Projections_app_view.csv"
WIDE_PRODUCTION_PROJECTIONS = C.PROD_ROOT / "projections.csv"
STAT_OUTPUTS = ["points", "rebounds", "assists", "threes_made", "steals", "blocks", "pa", "pr", "pra"]
STAT_LABELS = {
    "points": ("PTS", "Points"),
    "rebounds": ("REB", "Rebounds"),
    "assists": ("AST", "Assists"),
    "threes_made": ("FG3M", "3PM"),
    "steals": ("STL", "Steals"),
    "blocks": ("BLK", "Blocks"),
    "pa": ("PA", "Pts+Asts"),
    "pr": ("PR", "Pts+Rebs"),
    "pra": ("PRA", "Pts+Rebs+Asts"),
}
PROD_STAT_ALIASES = {"PTS": "points", "REB": "rebounds", "AST": "assists", "FG3M": "threes_made", "STL": "steals", "BLK": "blocks", "PA": "pa", "PR": "pr", "PRA": "pra"}


class Phase54FailClosed(RuntimeError):
    """Raised when the daily conserved V2 run should fail closed."""


def _require_accepted_calibration():
    if not CALIBRATION_PATH.exists():
        raise Phase54FailClosed(f"missing Phase 5.3 learned calibration: {CALIBRATION_PATH}")
    payload = json.loads(CALIBRATION_PATH.read_text())
    if not payload.get("accepted"):
        raise Phase54FailClosed(f"Phase 5.3 calibration is not accepted: {CALIBRATION_PATH}")
    checks = payload.get("acceptance_checks", {}) or {}
    if checks.get("all_pass") is not True:
        raise Phase54FailClosed(f"Phase 5.3 acceptance gates are not all pass: {CALIBRATION_PATH}")
    cfg = load_config(CALIBRATION_PATH, n_sims=N_SIMS)
    if cfg is None:
        raise Phase54FailClosed(f"unable to load Phase 5.3 calibration: {CALIBRATION_PATH}")
    return payload, cfg


def _run_realism_gates() -> dict:
    summary = phase53_validation.run()
    if not summary.get("accepted"):
        raise Phase54FailClosed("Phase 5.3 realism validation failed; daily V2 projections were not accepted")
    checks = summary.get("acceptance_checks", {}) or {}
    if checks.get("all_pass") is not True:
        raise Phase54FailClosed("Phase 5.3 realism gates did not all pass; daily V2 projections were not accepted")
    return summary


def _first_numeric(df: pd.DataFrame, cols: list[str], default: float) -> pd.Series:
    out = pd.Series(default, index=df.index, dtype=float)
    for col in cols:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce")
            out = vals.combine_first(out)
    return out.astype(float)


def _today_spine() -> pd.DataFrame:
    if not TODAY_FEATURES.exists():
        raise Phase54FailClosed(f"missing today's feature slate: {TODAY_FEATURES}")
    today = pd.read_csv(TODAY_FEATURES)
    if today.empty:
        raise Phase54FailClosed(f"today's feature slate is empty: {TODAY_FEATURES}")

    prod_wide = pd.read_csv(WIDE_PRODUCTION_PROJECTIONS) if WIDE_PRODUCTION_PROJECTIONS.exists() else pd.DataFrame()
    if not prod_wide.empty:
        key_cols = [c for c in ["PLAYER_KEY", "GAME_DATE", "PRED_MIN", "MIN_PROJ"] if c in prod_wide.columns]
        if {"PLAYER_KEY", "GAME_DATE"}.issubset(key_cols):
            prod_minutes = prod_wide[key_cols].rename(columns={"PLAYER_KEY": "player_key", "GAME_DATE": "game_date"})
            today["game_date"] = pd.to_datetime(today["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            prod_minutes["game_date"] = pd.to_datetime(prod_minutes["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            today = today.merge(prod_minutes.drop_duplicates(["player_key", "game_date"]), on=["player_key", "game_date"], how="left")

    spine = pd.DataFrame({
        "player_id": today.get("player_key", today.get("player_name")).astype(str),
        "player_name": today["player_name"].astype(str),
        "date": pd.to_datetime(today["game_date"], errors="coerce").dt.date.astype(str),
        "team": today["team"].astype(str),
        "opponent": today["opponent"].astype(str),
        "game_id": today.get("game_id", pd.Series(index=today.index, dtype=object)).fillna(
            today["game_date"].astype(str) + "_" + today["team"].astype(str) + "_" + today["opponent"].astype(str)
        ),
        "season": _first_numeric(today, ["season"], datetime.now(timezone.utc).year),
        "usage_share_pred": _first_numeric(today, ["usage_proxy_last_10", "usage_proxy_last_5", "usage_proxy"], 0.10).clip(0.005, 0.45),
        "n_regulars_out": 0.0,
        "star_out": 0.0,
        "min_mean": _first_numeric(today, ["PRED_MIN", "MIN_PROJ", "minutes_rolling_mean_5", "minutes_rolling_mean_10", "season_avg_minutes", "minutes"], 10.0),
        "min_std": _first_numeric(today, ["minutes_rolling_std_10", "minutes_rolling_std_5", "player_minutes_std_10"], 5.0),
        "play_prob": 0.95,
        "starter": (_first_numeric(today, ["PRED_MIN", "MIN_PROJ", "minutes_rolling_mean_5", "season_avg_minutes", "minutes"], 0.0) >= 22.0).astype(int),
        "team_poss_lag": _first_numeric(today, ["pace_last_10"], 78.0),
        "reb_pool_lag": (_first_numeric(today, ["team_rebounds_last_10"], 34.0) + _first_numeric(today, ["opponent_rebounds_allowed_last_10"], 34.0)),
        "tmfg_pool_lag": (_first_numeric(today, ["team_points_last_10"], 80.0) / 2.1).clip(20.0, 45.0),
        "target_team_points": _first_numeric(today, ["team_points_last_10"], 80.0).clip(55.0, 110.0),
        "target_team_threes": _first_numeric(today, ["team_threes_made_last_10"], 7.0).clip(2.0, 16.0),
        "target_team_steals": _first_numeric(today, ["team_steals_last_10"], 6.0).clip(1.0, 14.0),
        "target_team_blocks": _first_numeric(today, ["team_blocks_last_10"], 4.0).clip(0.5, 10.0),
        "points_mean": _first_numeric(today, ["rate_points_last_10", "season_avg_points"], 0.20).clip(0.0, 1.50),
        "points_std": _first_numeric(today, ["player_points_std_10"], 4.0),
        "rebounds_mean": _first_numeric(today, ["rate_rebounds_last_10", "season_avg_rebounds"], 0.10).clip(0.0, 1.00),
        "rebounds_std": _first_numeric(today, ["player_rebounds_std_10"], 2.5),
        "assists_mean": _first_numeric(today, ["rate_assists_last_10", "season_avg_assists"], 0.06).clip(0.0, 0.80),
        "assists_std": _first_numeric(today, ["player_assists_std_10"], 2.0),
        "fg3_pct_mean": 0.34,
        "fg3_pct_std": 0.08,
        "steals_mean": _first_numeric(today, ["rate_steals_last_10", "season_avg_steals"], 0.015).clip(0.0, 0.08),
        "steals_std": _first_numeric(today, ["player_steals_std_10"], 0.8),
        "blocks_mean": _first_numeric(today, ["rate_blocks_last_10", "season_avg_blocks"], 0.010).clip(0.0, 0.08),
        "blocks_std": _first_numeric(today, ["player_blocks_std_10"], 0.8),
    })
    threes_rate = _first_numeric(today, ["rate_threes_made_last_10", "season_avg_threes_made"], 0.03)
    spine["fg3a_mean"] = (threes_rate / spine["fg3_pct_mean"].clip(0.10, 0.90)).clip(0.0, 0.35)
    spine["fg3a_std"] = _first_numeric(today, ["player_threes_made_std_10"], 0.8)
    spine["typ_min"] = spine["min_mean"].clip(lower=5.0)
    spine["min_std"] = spine["min_std"].fillna(5.0).clip(2.0, 12.0)
    spine = fix_play_prob(spine)
    spine["name_key"] = spine["player_name"].map(norm_name)
    required = ["date", "game_id", "team", "player_name", "min_mean", "team_poss_lag", "points_mean"]
    return spine.dropna(subset=required).reset_index(drop=True)


def _mean_calibration() -> dict:
    train_spine, _ = build_spines(2026)
    rng = np.random.default_rng(C.RANDOM_SEED)
    return compute_calibration(train_spine, rng)


def _usage_probs(rows: pd.DataFrame) -> np.ndarray:
    weights = rows["usage_share_pred"].fillna(0.08).clip(0.005, 0.45).to_numpy(float)
    total = weights.sum()
    if total <= 0:
        return np.full(len(rows), 1.0 / max(len(rows), 1))
    return weights / total


def _scale_column(spine: pd.DataFrame, idx: pd.Index, col: str, scale: float) -> None:
    spine.loc[idx, col] = pd.to_numeric(spine.loc[idx, col], errors="coerce").fillna(0.0) * float(np.clip(scale, 0.03, 4.0))


def _normalize_daily_rates(spine: pd.DataFrame, cfg, calib: dict) -> pd.DataFrame:
    out = spine.copy()
    for (_, _), rows in out.groupby(["game_id", "team"]):
        idx = rows.index
        probs = _usage_probs(rows)
        poss = float(rows["team_poss_lag"].dropna().mean())
        usage_total = max(poss * float(cfg.usage_total_per_possession), 1.0)

        points_expected = usage_total * float(np.sum(probs * rows["points_mean"].to_numpy(float))) * float(calib.get("points", 1.0))
        points_target = float(rows["target_team_points"].dropna().mean())
        if points_expected > 0 and np.isfinite(points_target):
            _scale_column(out, idx, "points_mean", points_target / points_expected)

        threes_expected = (
            usage_total
            * float(np.sum(probs * rows["fg3a_mean"].to_numpy(float) * rows["fg3_pct_mean"].to_numpy(float)))
            * float(calib.get("threes_made", 1.0))
            * float(cfg.threes_mean_scale)
        )
        threes_target = float(rows["target_team_threes"].dropna().mean())
        if threes_expected > 0 and np.isfinite(threes_target):
            _scale_column(out, idx, "fg3a_mean", threes_target / threes_expected)

        court = rows["min_mean"].to_numpy(float) / 40.0
        steals_expected = (
            float(np.sum(rows["steals_mean"].to_numpy(float) * poss * court))
            * float(calib.get("steals", 1.0))
            * float(cfg.steals_mean_scale)
        )
        steals_target = float(rows["target_team_steals"].dropna().mean())
        if steals_expected > 0 and np.isfinite(steals_target):
            _scale_column(out, idx, "steals_mean", steals_target / steals_expected)

        blocks_expected = (
            float(np.sum(rows["blocks_mean"].to_numpy(float) * poss * court))
            * float(calib.get("blocks", 1.0))
            * float(cfg.blocks_mean_scale)
        )
        blocks_target = float(rows["target_team_blocks"].dropna().mean())
        if blocks_expected > 0 and np.isfinite(blocks_target):
            _scale_column(out, idx, "blocks_mean", blocks_target / blocks_expected)
    return out


def _projection_record(row: pd.Series, samples: dict[str, np.ndarray]) -> dict:
    rec = {
        "GAME_DATE": row["date"],
        "PLAYER_KEY": row["name_key"],
        "PLAYER_NAME": row["player_name"],
        "TEAM": row["team"],
        "OPPONENT": row.get("opponent"),
        "GAME_ID": row["game_id"],
        "SIM_RUNS": N_SIMS,
        "MIN_PROJ": float(row["min_mean"]),
    }
    for stat in STAT_OUTPUTS:
        values = np.asarray(samples[stat], dtype=float)
        p10, p50, p90 = np.percentile(values, [10, 50, 90])
        prefix = STAT_LABELS[stat][0]
        rec[f"{prefix}_PROJ"] = round(float(values.mean()), 2)
        rec[f"SIM_{prefix}_P10"] = round(float(p10), 2)
        rec[f"SIM_{prefix}_P50"] = round(float(p50), 2)
        rec[f"SIM_{prefix}_P90"] = round(float(p90), 2)
        rec[f"SIM_{prefix}_STD"] = round(float(values.std(ddof=1)), 2)
    return rec


def _app_rows(row: pd.Series, samples: dict[str, np.ndarray]) -> list[dict]:
    out = []
    for stat in STAT_OUTPUTS:
        values = np.asarray(samples[stat], dtype=float)
        p10, p50, p90 = np.percentile(values, [10, 50, 90])
        code, label = STAT_LABELS[stat]
        out.append({
            "GAME_DATE": row["date"],
            "PLAYER_KEY": row["name_key"],
            "PLAYER": row["player_name"],
            "TEAM": row["team"],
            "OPPONENT": row.get("opponent"),
            "MATCHUP": f"{row['team']} vs {row.get('opponent', '')}",
            "STAT": code,
            "STAT_LABEL": label,
            "PROJECTION": round(float(values.mean()), 2),
            "MEDIAN": round(float(p50), 2),
            "FLOOR": round(float(p10), 2),
            "CEILING": round(float(p90), 2),
            "STDDEV": round(float(values.std(ddof=1)), 2),
            "MIN": round(float(row["min_mean"]), 2),
            "SIM_RUNS": N_SIMS,
        })
    return out


def _latent_record(game_id, team: str, rows_team: pd.DataFrame, result: dict) -> dict:
    latents = result["latents"]
    minutes = np.asarray(latents["minutes"], dtype=float)
    starter = rows_team["starter"].fillna(0).to_numpy(float) >= 0.5
    return {
        "game_id": game_id,
        "team": team,
        "n_players": int(len(rows_team)),
        "possessions_mean": float(np.mean(latents["possessions"])),
        "possessions_std": float(np.std(latents["possessions"], ddof=1)),
        "blowout_mean": float(np.mean(latents["blowout"])),
        "team_minutes_min": float(minutes.sum(axis=1).min()),
        "team_minutes_max": float(minutes.sum(axis=1).max()),
        "starter_minutes_mean": float(minutes[:, starter].sum(axis=1).mean()) if starter.any() else 0.0,
        "bench_minutes_mean": float(minutes[:, ~starter].sum(axis=1).mean()) if (~starter).any() else 0.0,
        "team_points_mean": float(np.mean(latents["team_points"])),
        "team_rebounds_mean": float(np.mean(latents["team_rebounds"])),
        "team_assists_mean": float(np.mean(latents["team_assists"])),
    }


def _compare_to_production(app: pd.DataFrame) -> pd.DataFrame:
    if not PRODUCTION_PROJECTIONS.exists():
        return pd.DataFrame(columns=["error"])
    prod = pd.read_csv(PRODUCTION_PROJECTIONS)
    if prod.empty:
        return pd.DataFrame(columns=["error"])
    prod = prod.copy()
    prod["stat_key"] = prod["STAT"].map(PROD_STAT_ALIASES).fillna(prod["STAT"].astype(str).str.lower())
    prod["join_player"] = prod.get("PLAYER_KEY", prod.get("PLAYER", "")).map(norm_name)
    prod["GAME_DATE"] = pd.to_datetime(prod["GAME_DATE"], errors="coerce").dt.strftime("%Y-%m-%d")

    v2 = app.copy()
    v2["stat_key"] = v2["STAT"].map(PROD_STAT_ALIASES).fillna(v2["STAT"].astype(str).str.lower())
    v2["join_player"] = v2.get("PLAYER_KEY", v2.get("PLAYER", "")).map(norm_name)
    v2["GAME_DATE"] = pd.to_datetime(v2["GAME_DATE"], errors="coerce").dt.strftime("%Y-%m-%d")

    keys = ["GAME_DATE", "join_player", "TEAM", "stat_key"]
    comp = v2.merge(
        prod[keys + ["PROJECTION", "MEDIAN", "FLOOR", "CEILING", "STDDEV"]],
        on=keys,
        how="left",
        suffixes=("_v2", "_production"),
    )
    comp["projection_delta_v2_minus_production"] = comp["PROJECTION_v2"] - comp["PROJECTION_production"]
    return comp


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    calibration_payload, cfg = _require_accepted_calibration()
    realism = _run_realism_gates()
    spine = _today_spine()
    if spine.empty:
        raise Phase54FailClosed("Phase 5.4 today spine is empty after validation")

    rng = np.random.default_rng(C.RANDOM_SEED)
    calib = _mean_calibration()
    spine = _normalize_daily_rates(spine, cfg, calib)
    wide_rows: list[dict] = []
    app_rows: list[dict] = []
    latent_rows: list[dict] = []
    for game_id, game_rows in spine.groupby("game_id"):
        result = simulate_game(game_rows, N_SIMS, rng, calib=calib, cfg=cfg)
        for team, rows_team in game_rows.groupby("team"):
            if team not in result:
                continue
            rows_team = rows_team.reset_index(drop=True)
            team_result = result[team]
            latent_rows.append(_latent_record(game_id, team, rows_team, team_result))
            for i, (_, row) in enumerate(rows_team.iterrows()):
                samples = player_samples(team_result, i)
                wide_rows.append(_projection_record(row, samples))
                app_rows.extend(_app_rows(row, samples))

    wide = pd.DataFrame(wide_rows)
    app = pd.DataFrame(app_rows)
    latent = pd.DataFrame(latent_rows)
    comparison = _compare_to_production(app)

    wide.to_csv(OUT / "v2_conserved_projections.csv", index=False)
    app.to_csv(OUT / "v2_conserved_app_view.csv", index=False)
    latent.to_csv(OUT / "v2_conserved_latent_diagnostics.csv", index=False)
    comparison.to_csv(OUT / "v2_vs_current_production_today.csv", index=False)

    matched = int(comparison["PROJECTION_production"].notna().sum()) if "PROJECTION_production" in comparison else 0
    status = {
        "phase": "5.4",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "accepted_calibration_path": str(CALIBRATION_PATH),
        "calibration_phase": calibration_payload.get("phase"),
        "realism_gates_passed": True,
        "realism_summary_path": str(C.OUTPUTS / "phase53" / "phase53_validation_summary.json"),
        "players": int(wide["PLAYER_KEY"].nunique()) if not wide.empty else 0,
        "app_rows": int(len(app)),
        "production_comparison_rows": int(len(comparison)),
        "production_comparison_matched_rows": matched,
        "outputs": {
            "projections": str(OUT / "v2_conserved_projections.csv"),
            "app_view": str(OUT / "v2_conserved_app_view.csv"),
            "latent_diagnostics": str(OUT / "v2_conserved_latent_diagnostics.csv"),
            "production_comparison": str(OUT / "v2_vs_current_production_today.csv"),
        },
        "realism_scores": realism.get("scores", {}),
    }
    (OUT / "phase54_daily_status.json").write_text(json.dumps(status, indent=2, default=str))
    return status


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
