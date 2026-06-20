from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from wnba_model_config import DATASET_PATH, PROCESSED_DIR, STAT_TARGETS
from wnba_model_utils import build_regression_pipeline, clean_feature_frame, feature_columns, setup_logging


ROOT = Path(__file__).resolve().parent
LEARNING_DIR = ROOT / "learning"
REPORTS_DIR = LEARNING_DIR / "reports"
LEDGER_PATH = LEARNING_DIR / "graded_predictions_ledger.csv"
SHADOW_MODEL_DIR = ROOT / "data" / "models" / "shadow_projection_engine"

MINUTES_REPORT_PATH = PROCESSED_DIR / "wnba_projection_engine_minutes_report.csv"
USAGE_REPORT_PATH = PROCESSED_DIR / "wnba_projection_engine_usage_report.csv"
STAT_REPORT_PATH = PROCESSED_DIR / "wnba_projection_engine_stat_report.csv"
MARKET_REPLAY_PATH = PROCESSED_DIR / "wnba_projection_engine_market_replay.csv"
PROMOTION_PATH = PROCESSED_DIR / "wnba_projection_engine_promotion_recommendation.json"
SUMMARY_PATH = REPORTS_DIR / "wnba_projection_engine_shadow_report.md"

BASE_MARKETS = ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]
COMPONENT_MARKETS = ["points", "rebounds", "assists"]
COMBO_MARKETS = {
    "pra": ["points", "rebounds", "assists"],
    "pr": ["points", "rebounds"],
    "pa": ["points", "assists"],
    "ra": ["rebounds", "assists"],
}
POSITIONAL_FEATURES = [
    "pos_points_allowed_last_10",
    "pos_rebounds_allowed_last_10",
    "pos_assists_allowed_last_10",
    "pos_threes_made_allowed_last_10",
    "pos_steals_allowed_last_10",
    "pos_blocks_allowed_last_10",
]
ROLE_FEATURES = [
    "minutes_lag_1",
    "minutes_lag_2",
    "minutes_lag_3",
    "minutes_delta_1_over_5",
    "minutes_trend_pct_3_over_10",
    "rotation_minutes_share_last_10",
    "rotation_rank_last_10",
    "rotation_rank_delta_3_over_10",
    "rotation_tier",
    "role_change_flag",
    "shadow_projected_minutes",
    "learned_usage_projection",
]
MIN_PROMOTION_SAMPLE = 100
MIN_WIN_RATE_GAIN = 0.0
MAX_MAE_LOSS = 0.0
MAX_CALIBRATION_LOSS = 0.0


def enabled() -> bool:
    return os.environ.get("WNBA_ENABLE_PROJECTION_ENGINE_SHADOW", "").strip().lower() in {
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


def split_train_valid(data: pd.DataFrame, target: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    model_data = data.dropna(subset=[target, "game_date"]).copy()
    split_date = model_data["game_date"].quantile(0.8)
    train = model_data[model_data["game_date"] <= split_date].copy()
    valid = model_data[model_data["game_date"] > split_date].copy()
    if valid.empty:
        valid = train.tail(max(1, len(train) // 5)).copy()
        train = train.iloc[:-len(valid)].copy()
    if train.empty or valid.empty:
        raise ValueError(f"Unable to split train/validation rows for {target}")
    return train, valid


def add_role_features(dataset: pd.DataFrame) -> pd.DataFrame:
    frame = dataset.sort_values(["player_key", "game_date"]).copy()
    for lag in [1, 2, 3]:
        frame[f"minutes_lag_{lag}"] = frame.groupby("player_key")["minutes"].shift(lag)
    frame["minutes_delta_1_over_5"] = frame["minutes_lag_1"] - frame["minutes_rolling_mean_5"]
    frame["minutes_trend_pct_3_over_10"] = frame["minutes_trend_3_over_10"] / frame["minutes_rolling_mean_10"].replace(0, np.nan)
    frame["minutes_trend_pct_3_over_10"] = frame["minutes_trend_pct_3_over_10"].replace([np.inf, -np.inf], np.nan)

    team_rotation = frame.groupby(["game_date", "team"])["minutes_rolling_mean_10"].transform("sum")
    frame["rotation_minutes_share_last_10"] = frame["minutes_rolling_mean_10"] / team_rotation.replace(0, np.nan)
    frame["rotation_rank_last_10"] = frame.groupby(["game_date", "team"])["minutes_rolling_mean_10"].rank(
        method="dense",
        ascending=False,
    )
    frame["rotation_rank_last_3"] = frame.groupby(["game_date", "team"])["minutes_rolling_mean_3"].rank(
        method="dense",
        ascending=False,
    )
    frame["rotation_rank_delta_3_over_10"] = frame["rotation_rank_last_10"] - frame["rotation_rank_last_3"]
    frame["rotation_tier"] = pd.cut(
        frame["rotation_rank_last_10"],
        bins=[0, 3, 5, 8, 99],
        labels=["core", "starter_level", "rotation", "deep"],
    ).astype(str)
    frame["role_change_flag"] = (
        (frame["minutes_delta_1_over_5"].abs() >= 6)
        | (frame["minutes_trend_3_over_10"].abs() >= 5)
        | (frame["rotation_rank_delta_3_over_10"].abs() >= 2)
    ).astype(int)
    return frame


def fit_predict(
    train: pd.DataFrame,
    valid: pd.DataFrame,
    target: str,
    features: list[str],
) -> tuple[dict, np.ndarray, np.ndarray, pd.DataFrame, pd.DataFrame]:
    train_model = train.dropna(subset=[target]).copy()
    valid_model = valid.dropna(subset=[target]).copy()
    x_train = clean_feature_frame(train_model, features)
    x_valid = clean_feature_frame(valid_model, features)
    y_train = pd.to_numeric(train_model[target], errors="coerce")
    y_valid = pd.to_numeric(valid_model[target], errors="coerce")
    ridge, tree, _, _ = build_regression_pipeline(x_train)
    ridge.fit(x_train, y_train)
    tree.fit(x_train, y_train)
    train_pred = np.clip((ridge.predict(x_train) + tree.predict(x_train)) / 2.0, 0, None)
    valid_pred = np.clip((ridge.predict(x_valid) + tree.predict(x_valid)) / 2.0, 0, None)
    metrics = {
        "target": target,
        "train_rows": int(len(train_model)),
        "valid_rows": int(len(valid_model)),
        "mae": float(mean_absolute_error(y_valid, valid_pred)),
        "rmse": float(math.sqrt(mean_squared_error(y_valid, valid_pred))),
        "r2": float(r2_score(y_valid, valid_pred)),
    }
    bundle = {
        "ridge_model": ridge,
        "tree_model": tree,
        "feature_list": features,
        "metrics": metrics,
        "shadow": True,
        "created_at_utc": utc_now(),
    }
    return bundle, train_pred, valid_pred, train_model, valid_model


def metric_row(target: str, scenario: str, actual: pd.Series, pred: np.ndarray) -> dict:
    return {
        "target": target,
        "scenario": scenario,
        "sample_size": int(len(actual)),
        "mae": float(mean_absolute_error(actual, pred)),
        "rmse": float(math.sqrt(mean_squared_error(actual, pred))),
        "r2": float(r2_score(actual, pred)),
    }


def train_projection_engine(dataset: pd.DataFrame, logger) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base_features = feature_columns()
    base_minutes_features = [feature for feature in base_features if feature != "minutes"]
    role_base = [feature for feature in ROLE_FEATURES if feature not in {"shadow_projected_minutes", "learned_usage_projection"}]
    matchup_features = [feature for feature in POSITIONAL_FEATURES + ["opp_points_last_10"] if feature in dataset.columns]
    minutes_features = base_minutes_features + [feature for feature in role_base + matchup_features if feature not in base_minutes_features]

    train, valid = split_train_valid(dataset, "minutes")
    base_minutes_bundle, _, base_minutes_valid, _, minutes_valid = fit_predict(train, valid, "minutes", base_minutes_features)
    shadow_minutes_bundle, shadow_minutes_train, shadow_minutes_valid, minutes_train, minutes_valid = fit_predict(train, valid, "minutes", minutes_features)
    minutes_report = pd.DataFrame(
        [
            metric_row("minutes", "production_like_baseline", minutes_valid["minutes"], base_minutes_valid),
            metric_row("minutes", "role_pattern_shadow", minutes_valid["minutes"], shadow_minutes_valid),
        ]
    )

    train = train.copy()
    valid = valid.copy()
    train["shadow_projected_minutes"] = shadow_minutes_train
    valid["shadow_projected_minutes"] = shadow_minutes_valid

    usage_features = [
        feature
        for feature in base_minutes_features + role_base + matchup_features + ["shadow_projected_minutes"]
        if feature in train.columns
    ]
    usage_bundle, usage_train, usage_valid, usage_train_frame, usage_valid_frame = fit_predict(train, valid, "usage_proxy", usage_features)
    train["learned_usage_projection"] = usage_train
    valid["learned_usage_projection"] = usage_valid
    usage_report = pd.DataFrame(
        [
            metric_row("usage_proxy", "learned_usage_shadow", usage_valid_frame["usage_proxy"], usage_valid),
        ]
    )

    stat_rows = []
    prediction_rows = []
    shadow_stat_features = [
        feature
        for feature in base_features + role_base + matchup_features + ["shadow_projected_minutes", "learned_usage_projection"]
        if feature in train.columns
    ]
    shadow_stat_features = [feature for feature in shadow_stat_features if feature != "minutes"]
    SHADOW_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for target in STAT_TARGETS:
        baseline_bundle, _, base_valid, _, base_valid_frame = fit_predict(train, valid, target, base_features)
        shadow_bundle, _, shadow_valid, _, shadow_valid_frame = fit_predict(train, valid, target, shadow_stat_features)
        stat_rows.extend(
            [
                metric_row(target, "production_like_baseline", base_valid_frame[target], base_valid),
                metric_row(target, "projection_engine_shadow", shadow_valid_frame[target], shadow_valid),
            ]
        )
        pd.to_pickle(baseline_bundle, SHADOW_MODEL_DIR / f"wnba_{target}_production_like_baseline.pkl")
        pd.to_pickle(shadow_bundle, SHADOW_MODEL_DIR / f"wnba_{target}_projection_engine_shadow.pkl")
        pred = base_valid_frame[["game_date", "player_key", "player_name", "team", "opponent"]].copy()
        pred["market"] = target
        pred["actual_result"] = base_valid_frame[target].to_numpy()
        pred["production_like_projection"] = base_valid
        pred["shadow_projection"] = shadow_valid
        prediction_rows.append(pred)
        logger.info(
            "Projection engine shadow %s | baseline MAE %.3f | shadow MAE %.3f",
            target,
            mean_absolute_error(base_valid_frame[target], base_valid),
            mean_absolute_error(shadow_valid_frame[target], shadow_valid),
        )

    predictions = pd.concat(prediction_rows, ignore_index=True)
    component = predictions[predictions["market"].isin(COMPONENT_MARKETS)].copy()
    wide = component.pivot_table(
        index=["game_date", "player_key", "player_name", "team", "opponent"],
        columns="market",
        values=["actual_result", "production_like_projection", "shadow_projection"],
        aggfunc="first",
    )
    wide.columns = [f"{value}_{market}" for value, market in wide.columns]
    wide = wide.reset_index()
    combo_rows = []
    for market, parts in COMBO_MARKETS.items():
        combo = wide[["game_date", "player_key", "player_name", "team", "opponent"]].copy()
        combo["market"] = market
        combo["actual_result"] = sum(wide[f"actual_result_{part}"] for part in parts)
        combo["production_like_projection"] = sum(wide[f"production_like_projection_{part}"] for part in parts)
        combo["shadow_projection"] = sum(wide[f"shadow_projection_{part}"] for part in parts)
        combo_rows.append(combo)
    predictions = pd.concat([predictions, *combo_rows], ignore_index=True)

    pd.to_pickle(base_minutes_bundle, SHADOW_MODEL_DIR / "wnba_minutes_production_like_baseline.pkl")
    pd.to_pickle(shadow_minutes_bundle, SHADOW_MODEL_DIR / "wnba_minutes_role_pattern_shadow.pkl")
    pd.to_pickle(usage_bundle, SHADOW_MODEL_DIR / "wnba_usage_redistribution_shadow.pkl")
    return minutes_report, usage_report, pd.DataFrame(stat_rows), predictions


def normalize_ledger(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    ledger = frame.copy()
    ledger.columns = [str(column).strip().lower() for column in ledger.columns]
    required = ["date", "player_key", "market", "projection", "sportsbook_line", "actual_result", "result", "predicted_hit_rate"]
    missing = [column for column in required if column not in ledger.columns]
    if missing:
        raise ValueError(f"graded_predictions_ledger.csv missing required columns: {missing}")
    ledger["date"] = pd.to_datetime(ledger["date"], errors="coerce").dt.normalize()
    ledger["player_key"] = ledger["player_key"].astype(str).str.strip()
    ledger["market"] = ledger["market"].astype(str).str.lower().str.strip()
    ledger["result"] = ledger["result"].astype(str).str.lower().str.strip()
    for column in ["projection", "sportsbook_line", "actual_result", "predicted_hit_rate"]:
        ledger[column] = pd.to_numeric(ledger[column], errors="coerce")
    return ledger.dropna(subset=["date", "player_key", "market", "sportsbook_line", "actual_result"])


def projected_side(projection: float, line: float) -> str:
    if pd.isna(projection) or pd.isna(line):
        return ""
    return "over" if projection >= line else "under"


def grade_side(side: str, line: float, actual: float) -> str:
    if pd.isna(line) or pd.isna(actual):
        return ""
    if actual == line:
        return "push"
    if side == "over":
        return "win" if actual > line else "loss"
    return "win" if actual < line else "loss"


def win_rate(frame: pd.DataFrame, result_col: str) -> float:
    decisions = frame[frame[result_col].isin(["win", "loss"])]
    if decisions.empty:
        return np.nan
    return float((decisions[result_col] == "win").mean())


def line_confidence(projection: pd.Series, line: pd.Series, rmse: float) -> pd.Series:
    edge = (pd.to_numeric(projection, errors="coerce") - pd.to_numeric(line, errors="coerce")).abs()
    return (0.50 + edge / max(2.0 * rmse, 1e-9)).clip(0.50, 0.75)


def market_replay(predictions: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    if ledger.empty:
        return pd.DataFrame()
    pred = predictions.copy()
    pred["date"] = pd.to_datetime(pred["game_date"], errors="coerce").dt.normalize()
    merged = ledger.merge(
        pred,
        on=["date", "player_key", "market"],
        how="inner",
        suffixes=("_production", ""),
    )
    if merged.empty:
        return pd.DataFrame()
    rows = []
    for market, group in merged.groupby("market", dropna=False):
        rmse_shadow = math.sqrt(float(((group["shadow_projection"] - group["actual_result_production"]) ** 2).mean()))
        group = group.copy()
        group["shadow_side"] = [projected_side(p, line) for p, line in zip(group["shadow_projection"], group["sportsbook_line"])]
        group["shadow_result"] = [
            grade_side(side, line, actual)
            for side, line, actual in zip(group["shadow_side"], group["sportsbook_line"], group["actual_result_production"])
        ]
        group["production_error"] = group["projection"] - group["actual_result_production"]
        group["shadow_error"] = group["shadow_projection"] - group["actual_result_production"]
        prod_conf = group["predicted_hit_rate"].copy()
        if prod_conf.dropna().gt(1).any():
            prod_conf = prod_conf / 100.0
        shadow_conf = line_confidence(group["shadow_projection"], group["sportsbook_line"], rmse_shadow)
        prod_wr = win_rate(group, "result")
        shadow_wr = win_rate(group, "shadow_result")
        rows.append(
            {
                "market": market,
                "sample_size": int(len(group)),
                "production_mae": float(group["production_error"].abs().mean()),
                "shadow_mae": float(group["shadow_error"].abs().mean()),
                "mae_delta": float(group["shadow_error"].abs().mean() - group["production_error"].abs().mean()),
                "production_rmse": float(math.sqrt((group["production_error"] ** 2).mean())),
                "shadow_rmse": rmse_shadow,
                "rmse_delta": float(rmse_shadow - math.sqrt((group["production_error"] ** 2).mean())),
                "production_win_rate": prod_wr,
                "shadow_win_rate": shadow_wr,
                "win_rate_delta": shadow_wr - prod_wr if pd.notna(prod_wr) and pd.notna(shadow_wr) else np.nan,
                "production_calibration_error": abs(float(prod_conf.mean()) - prod_wr) if pd.notna(prod_wr) else np.nan,
                "shadow_calibration_error": abs(float(shadow_conf.mean()) - shadow_wr) if pd.notna(shadow_wr) else np.nan,
                "calibration_error_delta": (
                    abs(float(shadow_conf.mean()) - shadow_wr) - abs(float(prod_conf.mean()) - prod_wr)
                    if pd.notna(prod_wr) and pd.notna(shadow_wr)
                    else np.nan
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(["market"]).reset_index(drop=True)


def promotion_recommendation(replay: pd.DataFrame) -> dict:
    market_rows = []
    for _, row in replay.iterrows():
        qualifies_historical = (
            int(row["sample_size"]) >= MIN_PROMOTION_SAMPLE
            and float(row["mae_delta"]) <= MAX_MAE_LOSS
            and float(row["calibration_error_delta"]) <= MAX_CALIBRATION_LOSS
            and float(row["win_rate_delta"]) >= MIN_WIN_RATE_GAIN
        )
        market_rows.append(
            {
                "market": row["market"],
                "historical_replay_pass": bool(qualifies_historical),
                "fresh_canary_pass": False,
                "recommendation": "continue_shadow_canary" if qualifies_historical else "do_not_promote",
                "sample_size": int(row["sample_size"]),
                "mae_delta": float(row["mae_delta"]),
                "win_rate_delta": float(row["win_rate_delta"]) if pd.notna(row["win_rate_delta"]) else None,
                "calibration_error_delta": float(row["calibration_error_delta"]) if pd.notna(row["calibration_error_delta"]) else None,
            }
        )
    return {
        "created_at_utc": utc_now(),
        "decision": "do_not_promote_to_production",
        "reason": "Per-market promotion requires both historical replay and fresh canary evidence. This shadow run only supplies historical replay.",
        "market_recommendations": market_rows,
        "gates": {
            "minimum_historical_sample": MIN_PROMOTION_SAMPLE,
            "win_rate_delta_must_be_at_least": MIN_WIN_RATE_GAIN,
            "mae_must_be_no_worse": True,
            "calibration_must_be_no_worse": True,
            "fresh_canary_required": True,
        },
    }


def write_summary(minutes: pd.DataFrame, usage: pd.DataFrame, stats: pd.DataFrame, replay: pd.DataFrame, recommendation: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# WNBA Projection Engine Shadow",
        "",
        f"Generated: {utc_now()}",
        "",
        "Shadow-only projection-engine work. No board ranking, confidence capping, qualification, publish, or grading logic is changed.",
        "",
        "## Minutes",
    ]
    for _, row in minutes.iterrows():
        lines.append(f"- {row['scenario']}: MAE {row['mae']:.3f}, RMSE {row['rmse']:.3f}, R2 {row['r2']:.3f}, n={int(row['sample_size'])}")
    lines.append("")
    lines.append("## Usage")
    for _, row in usage.iterrows():
        lines.append(f"- {row['scenario']}: MAE {row['mae']:.3f}, RMSE {row['rmse']:.3f}, R2 {row['r2']:.3f}, n={int(row['sample_size'])}")
    lines.append("")
    lines.append("## Stat Validation")
    for target in sorted(stats["target"].unique()):
        subset = stats[stats["target"] == target].set_index("scenario")
        if {"production_like_baseline", "projection_engine_shadow"}.issubset(subset.index):
            base = subset.loc["production_like_baseline"]
            shadow = subset.loc["projection_engine_shadow"]
            lines.append(f"- {target}: MAE {base['mae']:.3f} -> {shadow['mae']:.3f}; RMSE {base['rmse']:.3f} -> {shadow['rmse']:.3f}")
    lines.append("")
    lines.append("## Market Replay vs Production Ledger")
    if replay.empty:
        lines.append("- No matched ledger rows for replay.")
    else:
        for _, row in replay.iterrows():
            lines.append(
                f"- {row['market']}: n={int(row['sample_size'])}, MAE delta {row['mae_delta']:+.3f}, "
                f"win-rate delta {row['win_rate_delta']:+.1%}, calibration delta {row['calibration_error_delta']:+.3f}"
            )
    lines.extend(
        [
            "",
            "## Promotion",
            f"- Decision: **{recommendation['decision']}**",
            f"- Reason: {recommendation['reason']}",
            "",
            "## Production Safety",
            "- Default OFF unless WNBA_ENABLE_PROJECTION_ENGINE_SHADOW=1 is set.",
            "- Writes only shadow reports and shadow model artifacts.",
        ]
    )
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    logger = setup_logging("wnba_projection_engine_shadow")
    if not enabled():
        logger.info("WNBA_ENABLE_PROJECTION_ENGINE_SHADOW is off; no projection-engine shadow run generated.")
        return

    dataset = pd.read_csv(DATASET_PATH, parse_dates=["game_date"])
    dataset = add_role_features(dataset)
    minutes, usage, stats, predictions = train_projection_engine(dataset, logger)
    ledger = normalize_ledger(read_csv(LEDGER_PATH))
    replay = market_replay(predictions, ledger)
    recommendation = promotion_recommendation(replay)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    minutes.to_csv(MINUTES_REPORT_PATH, index=False)
    usage.to_csv(USAGE_REPORT_PATH, index=False)
    stats.to_csv(STAT_REPORT_PATH, index=False)
    replay.to_csv(MARKET_REPLAY_PATH, index=False)
    PROMOTION_PATH.write_text(json.dumps(recommendation, indent=2) + "\n", encoding="utf-8")
    write_summary(minutes, usage, stats, replay, recommendation)
    logger.info("Wrote projection engine shadow report: %s", SUMMARY_PATH)


if __name__ == "__main__":
    main()
