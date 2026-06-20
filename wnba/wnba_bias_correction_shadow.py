from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from wnba_model_config import PROCESSED_DIR
from wnba_model_utils import setup_logging


ROOT = Path(__file__).resolve().parent
LEARNING_DIR = ROOT / "learning"
REPORTS_DIR = LEARNING_DIR / "reports"
LEDGER_PATH = LEARNING_DIR / "graded_predictions_ledger.csv"
MARKET_VALIDATION_PATH = PROCESSED_DIR / "wnba_market_validation_report.csv"
BIAS_TABLE_PATH = PROCESSED_DIR / "wnba_bias_correction_market_bias.csv"
COMPARISON_PATH = PROCESSED_DIR / "wnba_bias_correction_comparison.csv"
SCORED_ROWS_PATH = PROCESSED_DIR / "wnba_bias_correction_scored_rows.csv"
PROMOTION_PATH = PROCESSED_DIR / "wnba_bias_correction_promotion_recommendation.json"
REPORT_PATH = REPORTS_DIR / "wnba_bias_correction_shadow_report.md"

MIN_MARKET_PRIOR_SAMPLE = 20
MIN_PLAYER_PRIOR_SAMPLE = 8
MIN_CONTEXT_PRIOR_SAMPLE = 12
MIN_PROMOTION_SAMPLE = 250
MIN_PROMOTION_MARKETS = 3
MIN_MAE_GAIN = 0.05
MIN_RMSE_GAIN = 0.05
MAX_MARKET_CORRECTION = 4.0
MAX_PLAYER_CORRECTION = 2.5
MAX_CONTEXT_CORRECTION = 1.5
MAX_TOTAL_CORRECTION = 5.0
EPS = 1e-6


def enabled() -> bool:
    return os.environ.get("WNBA_ENABLE_BIAS_CORRECTION_SHADOW", "").strip().lower() in {"1", "true", "yes", "on"}


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
    required = ["date", "player", "team", "opponent", "market", "side", "projection", "sportsbook_line", "actual_result", "result"]
    missing = [column for column in required if column not in ledger.columns]
    if missing:
        raise ValueError(f"graded prediction ledger missing columns: {missing}")
    ledger["date"] = pd.to_datetime(ledger["date"], errors="coerce")
    for column in ["projection", "sportsbook_line", "actual_result", "predicted_hit_rate"]:
        if column not in ledger.columns:
            ledger[column] = np.nan
        ledger[column] = pd.to_numeric(ledger[column], errors="coerce")
    ledger["actual_minus_projection"] = ledger["actual_result"] - ledger["projection"]
    ledger["baseline_error"] = ledger["projection"] - ledger["actual_result"]
    ledger["baseline_absolute_error"] = ledger["baseline_error"].abs()
    ledger["baseline_squared_error"] = ledger["baseline_error"] ** 2
    ledger["market"] = ledger["market"].astype(str).str.lower().str.strip()
    ledger["player"] = ledger["player"].astype(str).str.strip()
    ledger["team"] = ledger["team"].astype(str).str.upper().str.strip()
    ledger["opponent"] = ledger["opponent"].astype(str).str.upper().str.strip()
    ledger["side"] = ledger["side"].astype(str).str.lower().str.strip()
    ledger["result"] = ledger["result"].astype(str).str.lower().str.strip()
    return ledger.dropna(subset=["date", "projection", "actual_result", "sportsbook_line", "market"])


def clip(value: float, limit: float) -> float:
    if pd.isna(value):
        return 0.0
    return float(np.clip(value, -limit, limit))


def directional_result(side: str, line: float, actual: float) -> str:
    if pd.isna(line) or pd.isna(actual):
        return ""
    if actual == line:
        return "push"
    if side == "over":
        return "win" if actual > line else "loss"
    return "win" if actual < line else "loss"


def projected_side(projection: float, line: float) -> str:
    if pd.isna(projection) or pd.isna(line):
        return ""
    return "over" if projection >= line else "under"


def build_prior_lookup(train: pd.DataFrame, group_cols: list[str], min_sample: int, limit: float) -> dict[tuple, tuple[float, int]]:
    if train.empty:
        return {}
    grouped = (
        train.dropna(subset=["actual_minus_projection"])
        .groupby(group_cols, dropna=False)["actual_minus_projection"]
        .agg(["mean", "count"])
        .reset_index()
    )
    lookup: dict[tuple, tuple[float, int]] = {}
    for _, row in grouped.iterrows():
        count = int(row["count"])
        if count < min_sample:
            continue
        key = tuple(row[column] for column in group_cols)
        lookup[key] = (clip(float(row["mean"]), limit), count)
    return lookup


def correction_for_row(row: pd.Series, market_lookup: dict, player_lookup: dict, team_opp_lookup: dict) -> dict:
    market_key = (row["market"],)
    player_key = (row["player"], row["market"])
    context_key = (row["team"], row["opponent"], row["market"])
    market_bias, market_n = market_lookup.get(market_key, (0.0, 0))
    player_bias, player_n = player_lookup.get(player_key, (0.0, 0))
    context_bias, context_n = team_opp_lookup.get(context_key, (0.0, 0))
    total = clip((0.70 * market_bias) + (0.20 * player_bias) + (0.10 * context_bias), MAX_TOTAL_CORRECTION)
    return {
        "market_bias": market_bias,
        "market_bias_sample": market_n,
        "player_bias": player_bias,
        "player_bias_sample": player_n,
        "team_opponent_bias": context_bias,
        "team_opponent_bias_sample": context_n,
        "total_correction": total,
    }


def score_shadow_rows(ledger: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ledger = ledger.sort_values(["date", "prediction_id" if "prediction_id" in ledger.columns else "player"]).reset_index(drop=True)
    for current_date, day in ledger.groupby("date", sort=True):
        train = ledger[ledger["date"] < current_date].copy()
        market_lookup = build_prior_lookup(train, ["market"], MIN_MARKET_PRIOR_SAMPLE, MAX_MARKET_CORRECTION)
        player_lookup = build_prior_lookup(train, ["player", "market"], MIN_PLAYER_PRIOR_SAMPLE, MAX_PLAYER_CORRECTION)
        team_opp_lookup = build_prior_lookup(train, ["team", "opponent", "market"], MIN_CONTEXT_PRIOR_SAMPLE, MAX_CONTEXT_CORRECTION)
        for _, row in day.iterrows():
            correction = correction_for_row(row, market_lookup, player_lookup, team_opp_lookup)
            shadow_projection = float(row["projection"]) + correction["total_correction"]
            shadow_error = shadow_projection - float(row["actual_result"])
            shadow_side = projected_side(shadow_projection, float(row["sportsbook_line"]))
            baseline_projected_side = projected_side(float(row["projection"]), float(row["sportsbook_line"]))
            shadow_result = directional_result(shadow_side, float(row["sportsbook_line"]), float(row["actual_result"]))
            baseline_result = directional_result(baseline_projected_side, float(row["sportsbook_line"]), float(row["actual_result"]))
            item = row.to_dict()
            item.update(correction)
            item.update(
                {
                    "baseline_projected_side": baseline_projected_side,
                    "baseline_projection_result": baseline_result,
                    "shadow_projection": shadow_projection,
                    "shadow_projected_side": shadow_side,
                    "shadow_projection_result": shadow_result,
                    "shadow_error": shadow_error,
                    "shadow_absolute_error": abs(shadow_error),
                    "shadow_squared_error": shadow_error**2,
                }
            )
            rows.append(item)
    return pd.DataFrame(rows)


def win_rate(frame: pd.DataFrame, column: str) -> float:
    decisions = frame[frame[column].isin(["win", "loss"])]
    if decisions.empty:
        return np.nan
    return float((decisions[column] == "win").mean())


def calibration(frame: pd.DataFrame, result_col: str) -> float:
    predicted = pd.to_numeric(frame.get("predicted_hit_rate"), errors="coerce").mean()
    actual = win_rate(frame, result_col)
    if pd.isna(predicted) or pd.isna(actual):
        return np.nan
    return float(actual - predicted)


def summarize_comparison(scored: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for market, group in scored.groupby("market", dropna=False):
        baseline_mae = float(group["baseline_absolute_error"].mean())
        shadow_mae = float(group["shadow_absolute_error"].mean())
        baseline_rmse = float(math.sqrt(group["baseline_squared_error"].mean()))
        shadow_rmse = float(math.sqrt(group["shadow_squared_error"].mean()))
        rows.append(
            {
                "market": market,
                "sample_size": int(len(group)),
                "baseline_mae": baseline_mae,
                "shadow_mae": shadow_mae,
                "mae_delta": shadow_mae - baseline_mae,
                "baseline_rmse": baseline_rmse,
                "shadow_rmse": shadow_rmse,
                "rmse_delta": shadow_rmse - baseline_rmse,
                "baseline_win_rate": win_rate(group, "result"),
                "shadow_win_rate": win_rate(group, "shadow_projection_result"),
                "win_rate_delta": win_rate(group, "shadow_projection_result") - win_rate(group, "result"),
                "baseline_calibration": calibration(group, "result"),
                "shadow_calibration": calibration(group, "shadow_projection_result"),
                "avg_total_correction": float(group["total_correction"].mean()),
            }
        )
    return pd.DataFrame(rows).sort_values(["mae_delta", "sample_size"], ascending=[True, False]).reset_index(drop=True)


def market_bias_table(scored: pd.DataFrame, market_validation: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for market, group in scored.groupby("market", dropna=False):
        rows.append(
            {
                "market": market,
                "sample_size": int(len(group)),
                "actual_minus_projection_bias": float(group["actual_minus_projection"].mean()),
                "median_actual_minus_projection": float(group["actual_minus_projection"].median()),
                "rolling_shadow_correction_avg": float(group["total_correction"].mean()),
                "latest_market_bias_applied_avg": float(group["market_bias"].tail(min(len(group), 50)).mean()),
            }
        )
    out = pd.DataFrame(rows)
    if not market_validation.empty and "market" in market_validation.columns:
        mv = market_validation.copy()
        mv["market"] = mv["market"].astype(str).str.lower().str.strip()
        keep = [column for column in ["market", "win_pct", "rolling_30_day_accuracy", "signed_projection_bias"] if column in mv.columns]
        out = out.merge(mv[keep], on="market", how="left")
    return out.sort_values("actual_minus_projection_bias", ascending=False).reset_index(drop=True)


def promotion_recommendation(comparison: pd.DataFrame) -> dict:
    enough = comparison[comparison["sample_size"] >= MIN_MARKET_PRIOR_SAMPLE].copy()
    meaningful = enough[
        (enough["sample_size"] >= MIN_MARKET_PRIOR_SAMPLE)
        & (enough["mae_delta"] <= -MIN_MAE_GAIN)
        & (enough["rmse_delta"] <= -MIN_RMSE_GAIN)
    ]
    total_sample = int(enough["sample_size"].sum()) if not enough.empty else 0
    weighted_mae_delta = (
        float(np.average(enough["mae_delta"], weights=enough["sample_size"])) if total_sample else np.nan
    )
    weighted_rmse_delta = (
        float(np.average(enough["rmse_delta"], weights=enough["sample_size"])) if total_sample else np.nan
    )
    promote = bool(
        total_sample >= MIN_PROMOTION_SAMPLE
        and len(meaningful) >= MIN_PROMOTION_MARKETS
        and pd.notna(weighted_mae_delta)
        and weighted_mae_delta <= -MIN_MAE_GAIN
        and pd.notna(weighted_rmse_delta)
        and weighted_rmse_delta <= -MIN_RMSE_GAIN
    )
    return {
        "generated_at_utc": utc_now(),
        "promote": False,
        "recommendation": "do_not_promote",
        "reason": (
            "shadow_bias_correction_improved_required_metrics_but_is_advisory_only"
            if promote
            else "insufficient_statistically_meaningful_market_improvement"
        ),
        "criteria": {
            "minimum_total_sample": MIN_PROMOTION_SAMPLE,
            "minimum_improved_markets": MIN_PROMOTION_MARKETS,
            "minimum_mae_gain": MIN_MAE_GAIN,
            "minimum_rmse_gain": MIN_RMSE_GAIN,
            "production_outputs_changed": False,
            "feature_flag_required": True,
        },
        "observed": {
            "total_sample": total_sample,
            "improved_markets": int(len(meaningful)),
            "weighted_mae_delta": None if pd.isna(weighted_mae_delta) else round(weighted_mae_delta, 6),
            "weighted_rmse_delta": None if pd.isna(weighted_rmse_delta) else round(weighted_rmse_delta, 6),
        },
    }


def table(frame: pd.DataFrame, columns: list[str], n: int = 12) -> str:
    if frame.empty:
        return "No rows available."
    return frame[columns].head(n).to_string(index=False)


def write_report(bias: pd.DataFrame, comparison: pd.DataFrame, recommendation: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    strongest = comparison.sort_values(["mae_delta", "rmse_delta"], ascending=[True, True])
    weakest = comparison.sort_values(["mae_delta", "rmse_delta"], ascending=[False, False])
    lines = [
        "# WNBA Bias Correction Shadow Report",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Market Bias",
        table(bias, ["market", "sample_size", "actual_minus_projection_bias", "rolling_shadow_correction_avg", "signed_projection_bias"], 12),
        "",
        "## Before/After by Market",
        table(comparison, ["market", "sample_size", "baseline_mae", "shadow_mae", "mae_delta", "baseline_win_rate", "shadow_win_rate", "win_rate_delta"], 12),
        "",
        "## Strongest Corrected Markets",
        table(strongest, ["market", "sample_size", "mae_delta", "rmse_delta", "win_rate_delta", "avg_total_correction"], 8),
        "",
        "## Weakest Corrected Markets",
        table(weakest, ["market", "sample_size", "mae_delta", "rmse_delta", "win_rate_delta", "avg_total_correction"], 8),
        "",
        "## Promotion Recommendation",
        json.dumps(recommendation, indent=2, sort_keys=True),
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    logger = setup_logging("wnba_bias_correction_shadow")
    if not enabled():
        logger.info("WNBA bias correction shadow skipped; set WNBA_ENABLE_BIAS_CORRECTION_SHADOW=1 to run.")
        return 0
    ledger = normalize_ledger(read_csv(LEDGER_PATH))
    if ledger.empty:
        raise FileNotFoundError(f"No graded prediction ledger rows found at {LEDGER_PATH}")
    market_validation = read_csv(MARKET_VALIDATION_PATH)
    scored = score_shadow_rows(ledger)
    bias = market_bias_table(scored, market_validation)
    comparison = summarize_comparison(scored)
    recommendation = promotion_recommendation(comparison)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    scored.to_csv(SCORED_ROWS_PATH, index=False)
    bias.to_csv(BIAS_TABLE_PATH, index=False)
    comparison.to_csv(COMPARISON_PATH, index=False)
    PROMOTION_PATH.write_text(json.dumps(recommendation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report(bias, comparison, recommendation)
    logger.info(
        "WNBA bias correction shadow complete | rows=%s | markets=%s | recommendation=%s",
        len(scored),
        len(comparison),
        recommendation["recommendation"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
