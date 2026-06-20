from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from wnba_model_config import DATASET_PATH, PROCESSED_DIR, STAT_TARGETS
from wnba_model_utils import (
    build_regression_pipeline,
    clean_feature_frame,
    feature_columns,
    setup_logging,
)


ROOT = Path(__file__).resolve().parent
LEARNING_DIR = ROOT / "learning"
REPORTS_DIR = LEARNING_DIR / "reports"
LEDGER_PATH = LEARNING_DIR / "graded_predictions_ledger.csv"
SHADOW_MODEL_DIR = ROOT / "data" / "models" / "shadow_feature_upgrade"

EXCLUDED_FEATURES_PATH = PROCESSED_DIR / "wnba_feature_upgrade_excluded_features.csv"
VALIDATION_REPORT_PATH = PROCESSED_DIR / "wnba_feature_upgrade_validation_report.csv"
LINE_REPORT_PATH = PROCESSED_DIR / "wnba_feature_upgrade_line_performance.csv"
SCORED_LINES_PATH = PROCESSED_DIR / "wnba_feature_upgrade_scored_lines.csv"
PROMOTION_PATH = PROCESSED_DIR / "wnba_feature_upgrade_promotion_recommendation.json"
SUMMARY_PATH = REPORTS_DIR / "wnba_feature_upgrade_shadow_report.md"

POSITIONAL_ALLOWANCE_FEATURES = [
    "pos_points_allowed_last_10",
    "pos_rebounds_allowed_last_10",
    "pos_assists_allowed_last_10",
    "pos_threes_made_allowed_last_10",
    "pos_steals_allowed_last_10",
    "pos_blocks_allowed_last_10",
]
MATCHUP_CANDIDATES = [
    "opp_points_last_10",
    *POSITIONAL_ALLOWANCE_FEATURES,
]
TARGET_TO_MARKET = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "threes_made": "threes_made",
    "steals": "steals",
    "blocks": "blocks",
}
MIN_LINE_SAMPLE = 25
MIN_PROMOTION_TARGETS = 2
MIN_MAE_GAIN = 0.01
MAX_WIN_RATE_LOSS = -0.005


def enabled() -> bool:
    return os.environ.get("WNBA_ENABLE_FEATURE_UPGRADE_SHADOW", "").strip().lower() in {
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


def normalize_ledger(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    ledger = frame.copy()
    ledger.columns = [str(column).strip().lower() for column in ledger.columns]
    required = ["date", "player_key", "market", "sportsbook_line", "actual_result"]
    missing = [column for column in required if column not in ledger.columns]
    if missing:
        return pd.DataFrame()
    ledger["date"] = pd.to_datetime(ledger["date"], errors="coerce").dt.normalize()
    ledger["player_key"] = ledger["player_key"].astype(str).str.strip()
    ledger["market"] = ledger["market"].astype(str).str.lower().str.strip()
    for column in ["sportsbook_line", "actual_result"]:
        ledger[column] = pd.to_numeric(ledger[column], errors="coerce")
    return ledger.dropna(subset=["date", "player_key", "market", "sportsbook_line", "actual_result"]).copy()


def excluded_feature_rows(dataset: pd.DataFrame, base_features: list[str]) -> pd.DataFrame:
    feature_set = set(base_features)
    rows = []
    for column in dataset.columns:
        lower = column.lower()
        is_matchup = any(token in lower for token in ["allowed", "opp_", "opponent", "pace", "rating", "position"])
        if not is_matchup or column in feature_set:
            continue
        useful = column in MATCHUP_CANDIDATES
        reason = "selected_for_shadow_upgrade" if useful else "excluded_from_upgrade"
        if column == "position":
            reason = "already_categorical_context_or_not_numeric"
        rows.append(
            {
                "feature": column,
                "selected_for_upgrade": bool(useful),
                "reason": reason,
                "non_null_rate": float(dataset[column].notna().mean()),
                "dtype": str(dataset[column].dtype),
            }
        )
    return pd.DataFrame(rows).sort_values(["selected_for_upgrade", "feature"], ascending=[False, True])


def split_train_valid(model_data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    split_date = model_data["game_date"].quantile(0.8)
    train_df = model_data[model_data["game_date"] <= split_date].copy()
    valid_df = model_data[model_data["game_date"] > split_date].copy()
    if valid_df.empty:
        valid_df = train_df.tail(max(1, len(train_df) // 5)).copy()
        train_df = train_df.iloc[:-len(valid_df)].copy()
    if train_df.empty or valid_df.empty:
        raise ValueError("Unable to create train/validation split.")
    return train_df, valid_df


def train_one(
    dataset: pd.DataFrame,
    target: str,
    features: list[str],
) -> tuple[dict, pd.DataFrame]:
    model_data = dataset.dropna(subset=[target]).copy()
    train_df, valid_df = split_train_valid(model_data)

    x_train = clean_feature_frame(train_df, features)
    y_train = train_df[target]
    x_valid = clean_feature_frame(valid_df, features)
    y_valid = valid_df[target]

    ridge_model, tree_model, _, _ = build_regression_pipeline(x_train)
    ridge_model.fit(x_train, y_train)
    tree_model.fit(x_train, y_train)

    ridge_pred = np.clip(ridge_model.predict(x_valid), 0, None)
    tree_pred = np.clip(tree_model.predict(x_valid), 0, None)
    pred = np.clip((ridge_pred + tree_pred) / 2.0, 0, None)
    metrics = {
        "target": target,
        "train_rows": int(len(train_df)),
        "valid_rows": int(len(valid_df)),
        "mae": float(mean_absolute_error(y_valid, pred)),
        "rmse": float(math.sqrt(mean_squared_error(y_valid, pred))),
        "r2": float(r2_score(y_valid, pred)),
        "ridge_mae": float(mean_absolute_error(y_valid, ridge_pred)),
        "tree_mae": float(mean_absolute_error(y_valid, tree_pred)),
    }
    bundle = {
        "ridge_model": ridge_model,
        "tree_model": tree_model,
        "feature_list": features,
        "metrics": metrics,
        "shadow": True,
        "created_at_utc": utc_now(),
    }
    pred_frame = valid_df[
        ["game_date", "player_key", "player_name", "team", "opponent", "position", target]
    ].copy()
    pred_frame["target"] = target
    pred_frame["actual"] = y_valid.to_numpy()
    pred_frame["prediction"] = pred
    pred_frame["squared_error"] = (pred_frame["prediction"] - pred_frame["actual"]) ** 2
    pred_frame["absolute_error"] = (pred_frame["prediction"] - pred_frame["actual"]).abs()
    return bundle, pred_frame


def train_shadow_models(
    dataset: pd.DataFrame,
    base_features: list[str],
    upgraded_features: list[str],
    logger,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    prediction_frames = []
    SHADOW_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for target in STAT_TARGETS:
        baseline_bundle, baseline_pred = train_one(dataset, target, base_features)
        upgraded_bundle, upgraded_pred = train_one(dataset, target, upgraded_features)

        joblib.dump(
            baseline_bundle,
            SHADOW_MODEL_DIR / f"wnba_{target}_baseline_feature_shadow.joblib",
        )
        joblib.dump(
            upgraded_bundle,
            SHADOW_MODEL_DIR / f"wnba_{target}_upgraded_feature_shadow.joblib",
        )

        base_metrics = baseline_bundle["metrics"]
        upgraded_metrics = upgraded_bundle["metrics"]
        rows.append(
            {
                "target": target,
                "train_rows": base_metrics["train_rows"],
                "valid_rows": base_metrics["valid_rows"],
                "baseline_mae": base_metrics["mae"],
                "upgraded_mae": upgraded_metrics["mae"],
                "mae_delta": upgraded_metrics["mae"] - base_metrics["mae"],
                "baseline_rmse": base_metrics["rmse"],
                "upgraded_rmse": upgraded_metrics["rmse"],
                "rmse_delta": upgraded_metrics["rmse"] - base_metrics["rmse"],
                "baseline_r2": base_metrics["r2"],
                "upgraded_r2": upgraded_metrics["r2"],
                "r2_delta": upgraded_metrics["r2"] - base_metrics["r2"],
                "features_added": ",".join([feature for feature in upgraded_features if feature not in base_features]),
            }
        )
        joined = baseline_pred.rename(
            columns={
                "prediction": "baseline_prediction",
                "absolute_error": "baseline_absolute_error",
                "squared_error": "baseline_squared_error",
            }
        ).merge(
            upgraded_pred[
                [
                    "game_date",
                    "player_key",
                    "target",
                    "prediction",
                    "absolute_error",
                    "squared_error",
                ]
            ].rename(
                columns={
                    "prediction": "upgraded_prediction",
                    "absolute_error": "upgraded_absolute_error",
                    "squared_error": "upgraded_squared_error",
                }
            ),
            on=["game_date", "player_key", "target"],
            how="inner",
        )
        prediction_frames.append(joined)
        logger.info(
            "Shadow feature upgrade %s | baseline MAE %.3f | upgraded MAE %.3f",
            target,
            base_metrics["mae"],
            upgraded_metrics["mae"],
        )
    return pd.DataFrame(rows), pd.concat(prediction_frames, ignore_index=True)


def projected_side(prediction: float, line: float) -> str:
    if pd.isna(prediction) or pd.isna(line):
        return ""
    return "over" if prediction >= line else "under"


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


def win_rate(frame: pd.DataFrame, column: str) -> float:
    decisions = frame[frame[column].isin(["win", "loss"])]
    if decisions.empty:
        return np.nan
    return float((decisions[column] == "win").mean())


def edge_confidence(frame: pd.DataFrame, pred_col: str, rmse_lookup: dict[str, float]) -> pd.Series:
    rmse = frame["market"].map(rmse_lookup).astype(float).replace(0, np.nan).fillna(1.0)
    edge = (frame[pred_col] - frame["sportsbook_line"]).abs()
    return (0.50 + (edge / (2.0 * rmse))).clip(0.50, 0.75)


def line_performance(predictions: pd.DataFrame, validation_report: pd.DataFrame, ledger: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if ledger.empty:
        return pd.DataFrame(), pd.DataFrame()
    pred = predictions.copy()
    pred["market"] = pred["target"].map(TARGET_TO_MARKET)
    pred["date"] = pd.to_datetime(pred["game_date"], errors="coerce").dt.normalize()
    merged = pred.merge(
        ledger,
        on=["date", "player_key", "market"],
        how="inner",
        suffixes=("", "_ledger"),
    )
    if merged.empty:
        return pd.DataFrame(), pd.DataFrame()

    for prefix in ["baseline", "upgraded"]:
        pred_col = f"{prefix}_prediction"
        merged[f"{prefix}_projected_side"] = [
            projected_side(prediction, line)
            for prediction, line in zip(merged[pred_col], merged["sportsbook_line"])
        ]
        merged[f"{prefix}_result"] = [
            directional_result(side, line, actual)
            for side, line, actual in zip(
                merged[f"{prefix}_projected_side"],
                merged["sportsbook_line"],
                merged["actual_result"],
            )
        ]

    baseline_rmse = validation_report.set_index("target")["baseline_rmse"].to_dict()
    upgraded_rmse = validation_report.set_index("target")["upgraded_rmse"].to_dict()
    merged["baseline_estimated_confidence"] = edge_confidence(merged, "baseline_prediction", baseline_rmse)
    merged["upgraded_estimated_confidence"] = edge_confidence(merged, "upgraded_prediction", upgraded_rmse)

    rows = []
    for market, group in merged.groupby("market", dropna=False):
        base_wr = win_rate(group, "baseline_result")
        up_wr = win_rate(group, "upgraded_result")
        rows.append(
            {
                "market": market,
                "line_sample_size": int(len(group)),
                "baseline_win_rate": base_wr,
                "upgraded_win_rate": up_wr,
                "win_rate_delta": up_wr - base_wr if pd.notna(base_wr) and pd.notna(up_wr) else np.nan,
                "baseline_calibration_error": abs(float(group["baseline_estimated_confidence"].mean()) - base_wr)
                if pd.notna(base_wr)
                else np.nan,
                "upgraded_calibration_error": abs(float(group["upgraded_estimated_confidence"].mean()) - up_wr)
                if pd.notna(up_wr)
                else np.nan,
                "calibration_error_delta": (
                    abs(float(group["upgraded_estimated_confidence"].mean()) - up_wr)
                    - abs(float(group["baseline_estimated_confidence"].mean()) - base_wr)
                )
                if pd.notna(base_wr) and pd.notna(up_wr)
                else np.nan,
                "baseline_avg_confidence": float(group["baseline_estimated_confidence"].mean()),
                "upgraded_avg_confidence": float(group["upgraded_estimated_confidence"].mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("market"), merged


def build_recommendation(validation: pd.DataFrame, line_report: pd.DataFrame) -> dict:
    improved = validation[(validation["mae_delta"] <= -MIN_MAE_GAIN) & (validation["rmse_delta"] <= 0)]
    line_guard = True
    weak_markets: list[str] = []
    if not line_report.empty:
        meaningful = line_report[line_report["line_sample_size"] >= MIN_LINE_SAMPLE]
        weak = meaningful[meaningful["win_rate_delta"] < MAX_WIN_RATE_LOSS]
        weak_markets = sorted(weak["market"].astype(str).tolist())
        line_guard = weak.empty
    qualifies = len(improved) >= MIN_PROMOTION_TARGETS and line_guard
    return {
        "created_at_utc": utc_now(),
        "decision": "recommend_future_shadow_canary" if qualifies else "do_not_promote",
        "reason": (
            "The upgraded feature set improved enough target models without degrading meaningful line samples."
            if qualifies
            else "The upgraded feature set did not clear both stat-accuracy and line-performance promotion gates."
        ),
        "improved_targets": sorted(improved["target"].astype(str).tolist()),
        "line_markets_with_guardrail_loss": weak_markets,
        "gates": {
            "min_improved_targets": MIN_PROMOTION_TARGETS,
            "required_mae_delta_at_most": -MIN_MAE_GAIN,
            "required_rmse_delta_at_most": 0,
            "min_line_sample": MIN_LINE_SAMPLE,
            "allowed_win_rate_delta_floor": MAX_WIN_RATE_LOSS,
        },
    }


def write_summary(
    excluded: pd.DataFrame,
    validation: pd.DataFrame,
    line_report: pd.DataFrame,
    recommendation: dict,
) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    selected = excluded[excluded["selected_for_upgrade"]]["feature"].astype(str).tolist()
    lines = [
        "# WNBA Phase 8 Feature Upgrade Shadow",
        "",
        f"Generated: {utc_now()}",
        "",
        "This is a shadow-only learned feature upgrade. It trains separate models under `data/models/shadow_feature_upgrade` and does not alter production model files, grading, publish, or public boards.",
        "",
        "## Excluded Features Selected",
    ]
    if selected:
        for feature in selected:
            lines.append(f"- {feature}")
    else:
        lines.append("- None")

    lines.extend(["", "## Historical Validation"])
    for _, row in validation.sort_values("mae_delta").iterrows():
        lines.append(
            f"- {row['target']}: MAE {row['baseline_mae']:.3f} -> {row['upgraded_mae']:.3f} "
            f"({row['mae_delta']:+.3f}); RMSE {row['rmse_delta']:+.3f}; R2 {row['r2_delta']:+.3f}"
        )

    lines.extend(["", "## Win Rate vs Line"])
    if line_report.empty:
        lines.append("- No matching validation rows were found in the graded ledger for line-side evaluation.")
    else:
        for _, row in line_report.iterrows():
            lines.append(
                f"- {row['market']}: n={int(row['line_sample_size'])}, win rate "
                f"{row['baseline_win_rate']:.1%} -> {row['upgraded_win_rate']:.1%} "
                f"({row['win_rate_delta']:+.1%}); calibration error delta {row['calibration_error_delta']:+.3f}"
            )

    lines.extend(
        [
            "",
            "## Promotion Recommendation",
            f"- Decision: **{recommendation['decision']}**",
            f"- Reason: {recommendation['reason']}",
            f"- Improved targets: {', '.join(recommendation['improved_targets']) or 'none'}",
            f"- Line guardrail losses: {', '.join(recommendation['line_markets_with_guardrail_loss']) or 'none'}",
            "",
            "## Production Safety",
            "- Default behavior remains OFF unless WNBA_ENABLE_FEATURE_UPGRADE_SHADOW=1 is set.",
            "- Shadow models are written only to `data/models/shadow_feature_upgrade`.",
            "- Public board and production model paths are not written.",
        ]
    )
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    logger = setup_logging("wnba_feature_upgrade_shadow")
    if not enabled():
        logger.info("WNBA_ENABLE_FEATURE_UPGRADE_SHADOW is off; no shadow models or reports generated.")
        return

    dataset = pd.read_csv(DATASET_PATH, parse_dates=["game_date"])
    base_features = feature_columns()
    missing = [feature for feature in base_features if feature not in dataset.columns]
    if missing:
        raise ValueError(f"Training dataset missing production features: {missing}")

    excluded = excluded_feature_rows(dataset, base_features)
    selected = [feature for feature in MATCHUP_CANDIDATES if feature in dataset.columns and feature not in base_features]
    upgraded_features = base_features + selected

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    excluded.to_csv(EXCLUDED_FEATURES_PATH, index=False)

    validation, predictions = train_shadow_models(dataset, base_features, upgraded_features, logger)
    ledger = normalize_ledger(read_csv(LEDGER_PATH))
    line_report, scored_lines = line_performance(predictions, validation, ledger)
    recommendation = build_recommendation(validation, line_report)

    validation.to_csv(VALIDATION_REPORT_PATH, index=False)
    line_report.to_csv(LINE_REPORT_PATH, index=False)
    scored_lines.to_csv(SCORED_LINES_PATH, index=False)
    PROMOTION_PATH.write_text(json.dumps(recommendation, indent=2) + "\n", encoding="utf-8")
    write_summary(excluded, validation, line_report, recommendation)
    logger.info("Wrote Phase 8 feature upgrade shadow report: %s", SUMMARY_PATH)


if __name__ == "__main__":
    main()
