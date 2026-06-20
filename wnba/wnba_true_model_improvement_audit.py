from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from wnba_model_config import PROCESSED_DIR
from wnba_model_utils import feature_columns, setup_logging


ROOT = Path(__file__).resolve().parent
LEARNING_DIR = ROOT / "learning"
REPORTS_DIR = LEARNING_DIR / "reports"
LEDGER_PATH = LEARNING_DIR / "graded_predictions_ledger.csv"
PROJECTION_ERRORS_PATH = LEARNING_DIR / "errors" / "projection_errors.csv"
MINUTES_ERRORS_PATH = LEARNING_DIR / "errors" / "minutes_errors.csv"
MODEL_REPORT_PATH = PROCESSED_DIR / "wnba_model_report.csv"
TRAINING_DATASET_PATH = PROCESSED_DIR / "wnba_training_dataset.csv"

AUDIT_FINDINGS_PATH = PROCESSED_DIR / "wnba_true_model_audit_findings.csv"
CHALLENGER_COMPARISON_PATH = PROCESSED_DIR / "wnba_true_model_challenger_comparison.csv"
MARKET_COMPARISON_PATH = PROCESSED_DIR / "wnba_true_model_market_performance.csv"
SCORED_ROWS_PATH = PROCESSED_DIR / "wnba_true_model_challenger_scored_rows.csv"
PROMOTION_PATH = PROCESSED_DIR / "wnba_true_model_promotion_recommendation.json"
SUMMARY_PATH = REPORTS_DIR / "wnba_true_model_improvement_audit.md"

MIN_MARKET_PRIOR_SAMPLE = 25
MIN_PLAYER_MARKET_PRIOR_SAMPLE = 8
MIN_TEAM_CONTEXT_PRIOR_SAMPLE = 16
MIN_PLAYER_MINUTES_PRIOR_SAMPLE = 5
MIN_PROMOTION_SAMPLE = 250
MIN_PROMOTION_MARKETS = 3
MIN_MAE_GAIN = 0.05
MIN_RMSE_GAIN = 0.05
MIN_WIN_RATE_LOSS = -0.005
COMBO_MARKETS = {"pra", "pa", "pr", "ra", "sb"}


def enabled() -> bool:
    return os.environ.get("WNBA_ENABLE_TRUE_MODEL_IMPROVEMENT_AUDIT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def lower_cols(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    if frame.columns.duplicated().any():
        frame = frame.loc[:, ~frame.columns.duplicated()].copy()
    return frame


def normalize_ledger(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    ledger = lower_cols(frame)
    required = ["date", "player", "team", "opponent", "market", "projection", "sportsbook_line", "actual_result", "result"]
    missing = [column for column in required if column not in ledger.columns]
    if missing:
        raise ValueError(f"graded_predictions_ledger.csv missing required columns: {missing}")
    ledger["date"] = pd.to_datetime(ledger["date"], errors="coerce")
    for column in [
        "projection",
        "sportsbook_line",
        "actual_result",
        "minutes_projected",
        "minutes_played",
        "predicted_hit_rate",
        "confidence_score",
    ]:
        if column not in ledger.columns:
            ledger[column] = np.nan
        ledger[column] = pd.to_numeric(ledger[column], errors="coerce")
    for column in ["market", "side", "result"]:
        if column not in ledger.columns:
            ledger[column] = ""
        ledger[column] = ledger[column].astype(str).str.lower().str.strip()
    ledger["player"] = ledger["player"].astype(str).str.strip()
    ledger["team"] = ledger["team"].astype(str).str.upper().str.strip()
    ledger["opponent"] = ledger["opponent"].astype(str).str.upper().str.strip()
    ledger["actual_minus_projection"] = ledger["actual_result"] - ledger["projection"]
    ledger["baseline_absolute_error"] = (ledger["projection"] - ledger["actual_result"]).abs()
    ledger["baseline_squared_error"] = (ledger["projection"] - ledger["actual_result"]) ** 2
    ledger["minutes_error_actual_minus_projected"] = ledger["minutes_played"] - ledger["minutes_projected"]
    return ledger.dropna(subset=["date", "projection", "sportsbook_line", "actual_result", "market"]).copy()


def clip(value: float, limit: float) -> float:
    if pd.isna(value):
        return 0.0
    return float(np.clip(value, -limit, limit))


def shrink(mean: float, count: int, floor: int) -> float:
    if count <= 0:
        return 0.0
    return float(mean) * min(1.0, count / max(floor * 2.0, 1.0))


def projected_side(projection: float, line: float) -> str:
    if pd.isna(projection) or pd.isna(line):
        return ""
    return "over" if projection >= line else "under"


def directional_result(side: str, line: float, actual: float) -> str:
    if pd.isna(line) or pd.isna(actual):
        return ""
    if actual == line:
        return "push"
    if side == "over":
        return "win" if actual > line else "loss"
    if side == "under":
        return "win" if actual < line else "loss"
    return ""


def build_prior_lookup(
    train: pd.DataFrame,
    group_cols: list[str],
    value_col: str,
    min_sample: int,
    limit: float,
) -> dict[tuple, tuple[float, int]]:
    if train.empty or value_col not in train.columns:
        return {}
    grouped = (
        train.dropna(subset=[value_col])
        .groupby(group_cols, dropna=False)[value_col]
        .agg(["mean", "count"])
        .reset_index()
    )
    lookup: dict[tuple, tuple[float, int]] = {}
    for _, row in grouped.iterrows():
        count = int(row["count"])
        if count < min_sample:
            continue
        key = tuple(row[column] for column in group_cols)
        lookup[key] = (clip(shrink(float(row["mean"]), count, min_sample), limit), count)
    return lookup


def minutes_projection(row: pd.Series, minutes_lookup: dict[tuple, tuple[float, int]]) -> tuple[float, float, int]:
    bias, sample = minutes_lookup.get((row["player"],), (0.0, 0))
    bias = clip(bias, 3.0)
    projected_minutes = float(row.get("minutes_projected", np.nan))
    if pd.isna(projected_minutes) or projected_minutes <= 0:
        return float(row["projection"]), 0.0, 0
    adjusted_minutes = max(1.0, projected_minutes + bias)
    scale = float(np.clip(adjusted_minutes / projected_minutes, 0.85, 1.15))
    return float(row["projection"]) * scale, bias, sample


def usage_projection(
    row: pd.Series,
    player_market_lookup: dict[tuple, tuple[float, int]],
    team_context_lookup: dict[tuple, tuple[float, int]],
) -> tuple[float, float, float, int, int]:
    player_bias, player_sample = player_market_lookup.get((row["player"], row["market"]), (0.0, 0))
    context_bias, context_sample = team_context_lookup.get((row["team"], row["opponent"], row["market"]), (0.0, 0))
    correction = clip((0.75 * player_bias) + (0.25 * context_bias), 3.0)
    return float(row["projection"]) + correction, correction, context_bias, player_sample, context_sample


def market_projection(row: pd.Series, market_lookup: dict[tuple, tuple[float, int]]) -> tuple[float, float, int]:
    market_bias, sample = market_lookup.get((row["market"],), (0.0, 0))
    correction = clip(0.65 * market_bias, 4.0)
    return float(row["projection"]) + correction, correction, sample


def combo_projection(
    row: pd.Series,
    market_lookup: dict[tuple, tuple[float, int]],
    player_market_lookup: dict[tuple, tuple[float, int]],
) -> tuple[float, float, int]:
    if row["market"] not in COMBO_MARKETS:
        return float(row["projection"]), 0.0, 0
    market_bias, market_sample = market_lookup.get((row["market"],), (0.0, 0))
    player_bias, player_sample = player_market_lookup.get((row["player"], row["market"]), (0.0, 0))
    correction = clip((0.85 * market_bias) + (0.15 * player_bias), 5.0)
    return float(row["projection"]) + correction, correction, max(market_sample, player_sample)


def score_one(projection: float, row: pd.Series) -> dict:
    side = projected_side(projection, float(row["sportsbook_line"]))
    result = directional_result(side, float(row["sportsbook_line"]), float(row["actual_result"]))
    error = projection - float(row["actual_result"])
    return {
        "projection": projection,
        "projected_side": side,
        "result": result,
        "absolute_error": abs(error),
        "squared_error": error**2,
    }


def score_challengers(ledger: pd.DataFrame) -> pd.DataFrame:
    scored_rows: list[dict] = []
    sort_cols = ["date", "prediction_id" if "prediction_id" in ledger.columns else "player"]
    ledger = ledger.sort_values(sort_cols).reset_index(drop=True)
    for current_date, day in ledger.groupby("date", sort=True):
        train = ledger[ledger["date"] < current_date].copy()
        market_lookup = build_prior_lookup(train, ["market"], "actual_minus_projection", MIN_MARKET_PRIOR_SAMPLE, 5.0)
        player_market_lookup = build_prior_lookup(
            train,
            ["player", "market"],
            "actual_minus_projection",
            MIN_PLAYER_MARKET_PRIOR_SAMPLE,
            3.0,
        )
        team_context_lookup = build_prior_lookup(
            train,
            ["team", "opponent", "market"],
            "actual_minus_projection",
            MIN_TEAM_CONTEXT_PRIOR_SAMPLE,
            2.0,
        )
        minutes_lookup = build_prior_lookup(
            train,
            ["player"],
            "minutes_error_actual_minus_projected",
            MIN_PLAYER_MINUTES_PRIOR_SAMPLE,
            3.0,
        )
        for _, row in day.iterrows():
            base_projection = float(row["projection"])
            baseline_side = projected_side(base_projection, float(row["sportsbook_line"]))
            baseline_result = directional_result(
                baseline_side,
                float(row["sportsbook_line"]),
                float(row["actual_result"]),
            )
            minutes_proj, minutes_bias, minutes_sample = minutes_projection(row, minutes_lookup)
            usage_proj, usage_correction, context_bias, player_sample, context_sample = usage_projection(
                row,
                player_market_lookup,
                team_context_lookup,
            )
            market_proj, market_correction, market_sample = market_projection(row, market_lookup)
            combo_proj, combo_correction, combo_sample = combo_projection(row, market_lookup, player_market_lookup)

            scored = row.to_dict()
            scored.update(
                {
                    "baseline_projected_side": baseline_side,
                    "baseline_projection_result": baseline_result,
                    "minutes_bias": minutes_bias,
                    "minutes_bias_sample": minutes_sample,
                    "usage_correction": usage_correction,
                    "usage_player_sample": player_sample,
                    "usage_context_bias": context_bias,
                    "usage_context_sample": context_sample,
                    "market_correction": market_correction,
                    "market_correction_sample": market_sample,
                    "combo_correction": combo_correction,
                    "combo_correction_sample": combo_sample,
                }
            )
            for challenger, projection in {
                "minutes_challenger": minutes_proj,
                "usage_redistribution_challenger": usage_proj,
                "market_specific_stat_challenger": market_proj,
                "combo_market_challenger": combo_proj,
            }.items():
                result = score_one(projection, row)
                scored[f"{challenger}_projection"] = result["projection"]
                scored[f"{challenger}_projected_side"] = result["projected_side"]
                scored[f"{challenger}_result"] = result["result"]
                scored[f"{challenger}_absolute_error"] = result["absolute_error"]
                scored[f"{challenger}_squared_error"] = result["squared_error"]
            scored_rows.append(scored)
    return pd.DataFrame(scored_rows)


def win_rate(frame: pd.DataFrame, column: str) -> float:
    decisions = frame[frame[column].isin(["win", "loss"])]
    if decisions.empty:
        return np.nan
    return float((decisions[column] == "win").mean())


def calibration_error(frame: pd.DataFrame, result_col: str) -> float:
    predicted = pd.to_numeric(frame.get("predicted_hit_rate"), errors="coerce").mean()
    actual = win_rate(frame, result_col)
    if pd.isna(predicted) or pd.isna(actual):
        return np.nan
    return float(abs(predicted - actual))


def summarize_challenger(scored: pd.DataFrame, challenger: str, market: str | None = None) -> dict:
    frame = scored if market is None else scored[scored["market"] == market]
    baseline_mae = float(frame["baseline_absolute_error"].mean())
    baseline_rmse = float(math.sqrt(frame["baseline_squared_error"].mean()))
    challenger_mae = float(frame[f"{challenger}_absolute_error"].mean())
    challenger_rmse = float(math.sqrt(frame[f"{challenger}_squared_error"].mean()))
    baseline_result_col = "baseline_projection_result"
    challenger_result_col = f"{challenger}_result"
    return {
        "challenger": challenger,
        "market": market or "all",
        "sample_size": int(len(frame)),
        "baseline_mae": baseline_mae,
        "challenger_mae": challenger_mae,
        "mae_delta": challenger_mae - baseline_mae,
        "baseline_rmse": baseline_rmse,
        "challenger_rmse": challenger_rmse,
        "rmse_delta": challenger_rmse - baseline_rmse,
        "baseline_win_rate": win_rate(frame, baseline_result_col),
        "challenger_win_rate": win_rate(frame, challenger_result_col),
        "win_rate_delta": win_rate(frame, challenger_result_col) - win_rate(frame, baseline_result_col),
        "baseline_calibration_error": calibration_error(frame, baseline_result_col),
        "challenger_calibration_error": calibration_error(frame, challenger_result_col),
        "calibration_error_delta": calibration_error(frame, challenger_result_col) - calibration_error(frame, baseline_result_col),
    }


def build_comparisons(scored: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    challengers = [
        "minutes_challenger",
        "usage_redistribution_challenger",
        "market_specific_stat_challenger",
        "combo_market_challenger",
    ]
    overall = pd.DataFrame([summarize_challenger(scored, challenger) for challenger in challengers])
    market_rows: list[dict] = []
    for challenger in challengers:
        for market in sorted(scored["market"].dropna().unique()):
            market_rows.append(summarize_challenger(scored, challenger, market))
    market = pd.DataFrame(market_rows)
    return overall, market


def stat_error_summary() -> pd.DataFrame:
    errors = lower_cols(read_csv(PROJECTION_ERRORS_PATH)) if PROJECTION_ERRORS_PATH.exists() else pd.DataFrame()
    if errors.empty or "stat" not in errors.columns:
        return pd.DataFrame()
    for column in ["absolute_error", "squared_error", "error"]:
        if column in errors.columns:
            errors[column] = pd.to_numeric(errors[column], errors="coerce")
    return (
        errors.groupby("stat", dropna=False)
        .agg(
            sample_size=("stat", "size"),
            mean_error_actual_minus_projection=("error", "mean"),
            mae=("absolute_error", "mean"),
            rmse=("squared_error", lambda s: math.sqrt(float(pd.to_numeric(s, errors="coerce").mean()))),
        )
        .reset_index()
    )


def minutes_error_summary() -> dict:
    errors = lower_cols(read_csv(MINUTES_ERRORS_PATH)) if MINUTES_ERRORS_PATH.exists() else pd.DataFrame()
    if errors.empty:
        return {}
    for column in ["error", "absolute_error", "squared_error"]:
        if column in errors.columns:
            errors[column] = pd.to_numeric(errors[column], errors="coerce")
    return {
        "sample_size": int(len(errors)),
        "mean_error_actual_minus_projected": float(errors["error"].mean()) if "error" in errors.columns else np.nan,
        "mae": float(errors["absolute_error"].mean()) if "absolute_error" in errors.columns else np.nan,
        "rmse": float(math.sqrt(errors["squared_error"].mean())) if "squared_error" in errors.columns else np.nan,
    }


def build_audit_findings() -> pd.DataFrame:
    features = set(feature_columns())
    training = lower_cols(read_csv(TRAINING_DATASET_PATH)) if TRAINING_DATASET_PATH.exists() else pd.DataFrame()
    training_cols = set(training.columns)
    rows = [
        {
            "audit_item": "minutes_projection_creation",
            "status": "implemented",
            "evidence": "train_wnba_minutes_model.py trains target=minutes; simulate_wnba_today.build_projection_rows predicts projected_minutes and clips 8-40.",
            "risk": "Live projected_minutes is applied mainly in simulation after stat models have already predicted totals.",
        },
        {
            "audit_item": "usage_rate_creation",
            "status": "implemented_proxy",
            "evidence": "build_wnba_dataset.add_usage_features creates usage_proxy = points + 1.2*assists + 0.7*rebounds + 0.6*3PM per minute, then rolling 5/10.",
            "risk": "Usage is a manual proxy, not possession-level usage, and redistribution weights are heuristic.",
        },
        {
            "audit_item": "points_rebounds_assists_creation",
            "status": "implemented",
            "evidence": "train_wnba_models.py trains learned stat models; simulate_wnba_today.build_projection_rows predicts points/rebounds/assists/etc.",
            "risk": "Monte Carlo later blends model-implied per-minute rate with last-10 historical rate at fixed 65/35 weight.",
        },
        {
            "audit_item": "combo_market_creation",
            "status": "implemented",
            "evidence": "simulate_wnba_today.COMBO_STATS creates PRA/PR/PA/RA/SB by summing simulated base stat samples.",
            "risk": "Combo market calibration inherits correlated base-stat errors and line-side thresholds are not learned in projection generation.",
        },
        {
            "audit_item": "injury_and_lineup_redistribution",
            "status": "partial",
            "evidence": "build_absences_from_status and apply_absence_redistribution redistribute minutes/stat uplifts from status-driven absences.",
            "risk": "Starting lineup changes are inferred through status/recent minutes, not an explicit starter or role-change model.",
        },
        {
            "audit_item": "recent_form_weighting",
            "status": "heuristic_plus_learned",
            "evidence": "Feature set includes rolling 3/5/10, EWMs, season averages, and minutes_trend_3_over_10; simulation uses fixed 65/35 model-rate/history-rate blend.",
            "risk": "Recent form weight is not market-specific or learned from graded outcomes.",
        },
        {
            "audit_item": "opponent_defensive_allowance_by_position",
            "status": "available_not_in_feature_list",
            "evidence": "Training dataset includes pos_*_allowed_last_10, but feature_columns excludes those columns.",
            "risk": "Opponent position allowance exists in data but does not currently feed the learned models.",
        },
        {
            "audit_item": "pace_and_possession_environment",
            "status": "implemented",
            "evidence": "pace_last_10 is in feature_columns and simulation applies game_state pace when WNBA_P7_GAME_STATE is enabled.",
            "risk": "Pace context is team-level rolling and simulated multiplicatively; no learned market-specific possession elasticity.",
        },
        {
            "audit_item": "player_role_change_detection",
            "status": "partial",
            "evidence": "minutes_trend_3_over_10, rolling minutes, status-based absence redistribution, and player variance features capture some role change.",
            "risk": "No explicit role-state classifier for starter, bench, returning-from-injury, or rotation promotion.",
        },
        {
            "audit_item": "learned_vs_manual_weights",
            "status": "mixed",
            "evidence": "Ridge/tree ensembles learn stat and minute projections; confidence labels, redistributions, caps, and simulation blends are manual.",
            "risk": "Manual post-model rules can improve realism while still failing to optimize market-level win rate.",
        },
    ]
    if {"pos_points_allowed_last_10", "pos_rebounds_allowed_last_10", "pos_assists_allowed_last_10"}.issubset(training_cols):
        rows[6]["status"] = "created_but_not_used"
    if {"pos_points_allowed_last_10", "pos_rebounds_allowed_last_10", "pos_assists_allowed_last_10"} & features:
        rows[6]["status"] = "implemented"
        rows[6]["risk"] = "Included in model features; monitor feature importance and calibration by position."
    return pd.DataFrame(rows)


def promotion_recommendation(overall: pd.DataFrame, market: pd.DataFrame) -> dict:
    candidates = []
    for _, row in overall.iterrows():
        challenger = row["challenger"]
        markets = market[market["challenger"] == challenger]
        improved_markets = markets[
            (markets["sample_size"] >= 25)
            & (markets["mae_delta"] <= -MIN_MAE_GAIN)
            & (markets["rmse_delta"] <= 0.0)
            & (markets["win_rate_delta"] >= MIN_WIN_RATE_LOSS)
        ]
        qualifies = (
            int(row["sample_size"]) >= MIN_PROMOTION_SAMPLE
            and float(row["mae_delta"]) <= -MIN_MAE_GAIN
            and float(row["rmse_delta"]) <= -MIN_RMSE_GAIN
            and float(row["win_rate_delta"]) >= MIN_WIN_RATE_LOSS
            and len(improved_markets) >= MIN_PROMOTION_MARKETS
        )
        candidates.append(
            {
                "challenger": challenger,
                "qualifies_for_future_promotion": bool(qualifies),
                "sample_size": int(row["sample_size"]),
                "mae_delta": float(row["mae_delta"]),
                "rmse_delta": float(row["rmse_delta"]),
                "win_rate_delta": float(row["win_rate_delta"]),
                "improved_market_count": int(len(improved_markets)),
                "improved_markets": sorted(improved_markets["market"].astype(str).tolist()),
            }
        )
    qualified = [item for item in candidates if item["qualifies_for_future_promotion"]]
    best = None
    if qualified:
        best = sorted(qualified, key=lambda item: (item["mae_delta"], item["rmse_delta"], -item["win_rate_delta"]))[0]
    return {
        "created_at_utc": utc_now(),
        "decision": "recommend_future_shadow_canary" if best else "do_not_promote",
        "recommended_challenger": best["challenger"] if best else None,
        "reason": (
            "A challenger met MAE, RMSE, win-rate, sample-size, and market-breadth gates."
            if best
            else "No challenger cleared all promotion gates without unacceptable market-side risk."
        ),
        "gates": {
            "min_sample": MIN_PROMOTION_SAMPLE,
            "min_improved_markets": MIN_PROMOTION_MARKETS,
            "required_mae_delta_at_most": -MIN_MAE_GAIN,
            "required_rmse_delta_at_most": -MIN_RMSE_GAIN,
            "allowed_win_rate_delta_floor": MIN_WIN_RATE_LOSS,
        },
        "candidates": candidates,
    }


def pct(value: float) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.1%}"


def write_summary(
    findings: pd.DataFrame,
    overall: pd.DataFrame,
    market: pd.DataFrame,
    recommendation: dict,
) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stat_errors = stat_error_summary()
    minutes_errors = minutes_error_summary()
    model_report = lower_cols(read_csv(MODEL_REPORT_PATH)) if MODEL_REPORT_PATH.exists() else pd.DataFrame()

    lines = [
        "# WNBA Phase 7 True Model Improvement Audit",
        "",
        f"Generated: {utc_now()}",
        "",
        "This is a shadow-only audit. It does not write production projections, public boards, grading ledgers, or challenger publish outputs.",
        "",
        "## Projection Pipeline Findings",
    ]
    for _, row in findings.iterrows():
        lines.append(f"- **{row['audit_item']}**: {row['status']}. {row['evidence']} Risk: {row['risk']}")

    if minutes_errors:
        lines.extend(
            [
                "",
                "## Minutes Error Snapshot",
                (
                    f"- Sample {minutes_errors.get('sample_size', 0)}; "
                    f"mean actual-projected {minutes_errors.get('mean_error_actual_minus_projected', np.nan):.3f}; "
                    f"MAE {minutes_errors.get('mae', np.nan):.3f}; RMSE {minutes_errors.get('rmse', np.nan):.3f}."
                ),
            ]
        )
    if not stat_errors.empty:
        lines.extend(["", "## Base Stat Error Snapshot"])
        for _, row in stat_errors.sort_values("mae", ascending=False).iterrows():
            lines.append(
                f"- {row['stat']}: n={int(row['sample_size'])}, mean actual-projected={row['mean_error_actual_minus_projection']:.3f}, MAE={row['mae']:.3f}, RMSE={row['rmse']:.3f}"
            )
    if not model_report.empty:
        lines.extend(["", "## Model Validation Snapshot"])
        for _, row in model_report.sort_values("mae", ascending=False).iterrows():
            lines.append(
                f"- {row['target']}: valid_rows={int(row['valid_rows'])}, MAE={row['mae']:.3f}, RMSE={row['rmse']:.3f}, R2={row['r2']:.3f}"
            )

    lines.extend(["", "## Challenger Overall Results"])
    for _, row in overall.sort_values("mae_delta").iterrows():
        lines.append(
            f"- {row['challenger']}: MAE {row['baseline_mae']:.3f} -> {row['challenger_mae']:.3f} "
            f"({row['mae_delta']:+.3f}); RMSE {row['rmse_delta']:+.3f}; "
            f"win rate {pct(row['baseline_win_rate'])} -> {pct(row['challenger_win_rate'])} "
            f"({row['win_rate_delta']:+.1%}); calibration error delta {row['calibration_error_delta']:+.3f}."
        )

    lines.extend(["", "## Best/Worst Market-Level Challenger Moves"])
    best = market.sort_values("mae_delta").head(8)
    worst = market.sort_values("mae_delta", ascending=False).head(8)
    lines.append("Best MAE deltas:")
    for _, row in best.iterrows():
        lines.append(f"- {row['challenger']} / {row['market']}: MAE delta {row['mae_delta']:+.3f}, win-rate delta {row['win_rate_delta']:+.1%}, n={int(row['sample_size'])}")
    lines.append("Worst MAE deltas:")
    for _, row in worst.iterrows():
        lines.append(f"- {row['challenger']} / {row['market']}: MAE delta {row['mae_delta']:+.3f}, win-rate delta {row['win_rate_delta']:+.1%}, n={int(row['sample_size'])}")

    lines.extend(
        [
            "",
            "## Promotion Recommendation",
            f"- Decision: **{recommendation['decision']}**",
            f"- Recommended challenger: {recommendation.get('recommended_challenger') or 'none'}",
            f"- Reason: {recommendation['reason']}",
            "",
            "## Production Safety",
            "- Default behavior remains OFF unless WNBA_ENABLE_TRUE_MODEL_IMPROVEMENT_AUDIT=1 is set.",
            "- The audit reads historical artifacts and writes only Phase 7 audit outputs.",
            "- It does not import or call publish, grading, or simulation entry points.",
        ]
    )
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    logger = setup_logging("wnba_true_model_improvement_audit")
    if not enabled():
        logger.info("WNBA_ENABLE_TRUE_MODEL_IMPROVEMENT_AUDIT is off; no reports generated.")
        return

    ledger = normalize_ledger(read_csv(LEDGER_PATH))
    if ledger.empty:
        raise RuntimeError(f"No graded prediction ledger rows found at {LEDGER_PATH}")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    findings = build_audit_findings()
    scored = score_challengers(ledger)
    overall, market = build_comparisons(scored)
    recommendation = promotion_recommendation(overall, market)

    findings.to_csv(AUDIT_FINDINGS_PATH, index=False)
    scored.to_csv(SCORED_ROWS_PATH, index=False)
    overall.to_csv(CHALLENGER_COMPARISON_PATH, index=False)
    market.to_csv(MARKET_COMPARISON_PATH, index=False)
    PROMOTION_PATH.write_text(json.dumps(recommendation, indent=2) + "\n", encoding="utf-8")
    write_summary(findings, overall, market, recommendation)

    logger.info("Wrote Phase 7 true model improvement audit: %s", SUMMARY_PATH)


if __name__ == "__main__":
    main()
