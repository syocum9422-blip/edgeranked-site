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
SHADOW_MODEL_DIR = ROOT / "data" / "models" / "shadow_hybrid_minutes"

MINUTES_REPORT_PATH = PROCESSED_DIR / "wnba_hybrid_minutes_minutes_comparison.csv"
BLEND_VALIDATION_PATH = PROCESSED_DIR / "wnba_hybrid_minutes_blend_validation.csv"
MARKET_REPLAY_PATH = PROCESSED_DIR / "wnba_hybrid_minutes_market_replay.csv"
RECOMMENDATION_PATH = PROCESSED_DIR / "wnba_hybrid_minutes_recommendation.json"
SUMMARY_PATH = REPORTS_DIR / "wnba_hybrid_minutes_shadow_report.md"

BLENDS = [0.0, 0.25, 0.50, 0.75, 1.0]
BASE_COMPONENTS = ["points", "rebounds", "assists"]
REPLAY_MARKETS = ["points", "rebounds", "assists", "pra", "pr", "pa", "ra"]
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
    "opp_points_last_10",
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
]
MIN_RECOMMEND_SAMPLE = 25


def enabled() -> bool:
    return os.environ.get("WNBA_ENABLE_HYBRID_MINUTES_SHADOW", "").strip().lower() in {
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


def add_role_features(dataset: pd.DataFrame) -> pd.DataFrame:
    frame = dataset.sort_values(["player_key", "game_date"]).copy()
    for lag in [1, 2, 3]:
        frame[f"minutes_lag_{lag}"] = frame.groupby("player_key")["minutes"].shift(lag)
    frame["minutes_delta_1_over_5"] = frame["minutes_lag_1"] - frame["minutes_rolling_mean_5"]
    frame["minutes_trend_pct_3_over_10"] = frame["minutes_trend_3_over_10"] / frame["minutes_rolling_mean_10"].replace(0, np.nan)
    frame["minutes_trend_pct_3_over_10"] = frame["minutes_trend_pct_3_over_10"].replace([np.inf, -np.inf], np.nan)
    team_minutes = frame.groupby(["game_date", "team"])["minutes_rolling_mean_10"].transform("sum")
    frame["rotation_minutes_share_last_10"] = frame["minutes_rolling_mean_10"] / team_minutes.replace(0, np.nan)
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


def fit_model(train: pd.DataFrame, target: str, features: list[str]) -> dict:
    model_data = train.dropna(subset=[target]).copy()
    x_train = clean_feature_frame(model_data, features)
    y_train = pd.to_numeric(model_data[target], errors="coerce")
    ridge, tree, _, _ = build_regression_pipeline(x_train)
    ridge.fit(x_train, y_train)
    tree.fit(x_train, y_train)
    return {
        "ridge_model": ridge,
        "tree_model": tree,
        "feature_list": features,
        "target": target,
        "created_at_utc": utc_now(),
        "shadow": True,
    }


def predict_bundle(bundle: dict, frame: pd.DataFrame) -> np.ndarray:
    features = bundle["feature_list"]
    x = clean_feature_frame(frame, features)
    return np.clip((bundle["ridge_model"].predict(x) + bundle["tree_model"].predict(x)) / 2.0, 0, None)


def metric_values(actual: pd.Series, pred: np.ndarray) -> dict:
    return {
        "mae": float(mean_absolute_error(actual, pred)),
        "rmse": float(math.sqrt(mean_squared_error(actual, pred))),
        "r2": float(r2_score(actual, pred)) if len(actual) > 1 else np.nan,
    }


def train_minutes_models(dataset: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base_features = [feature for feature in feature_columns() if feature != "minutes"]
    role_features = [
        feature
        for feature in base_features + ROLE_FEATURES + [feature for feature in POSITIONAL_FEATURES if feature in dataset.columns]
        if feature in dataset.columns
    ]
    train, valid = split_train_valid(dataset, "minutes")
    production_minutes_model = fit_model(train, "minutes", base_features)
    role_minutes_model = fit_model(train, "minutes", role_features)
    production_minutes = predict_bundle(production_minutes_model, valid)
    role_minutes = predict_bundle(role_minutes_model, valid)
    report = pd.DataFrame(
        [
            {"scenario": "production_minutes_model", "sample_size": len(valid), **metric_values(valid["minutes"], production_minutes)},
            {"scenario": "role_pattern_minutes_model", "sample_size": len(valid), **metric_values(valid["minutes"], role_minutes)},
        ]
    )
    valid = valid.copy()
    valid["production_minutes_feature"] = production_minutes
    valid["role_pattern_minutes_feature"] = role_minutes
    pd.to_pickle(production_minutes_model, SHADOW_MODEL_DIR / "wnba_minutes_production_like.pkl")
    pd.to_pickle(role_minutes_model, SHADOW_MODEL_DIR / "wnba_minutes_role_pattern.pkl")
    return train, valid, report


def train_stat_models(train: pd.DataFrame) -> dict[str, dict]:
    features = feature_columns()
    models: dict[str, dict] = {}
    for target in STAT_TARGETS:
        models[target] = fit_model(train, target, features)
        pd.to_pickle(models[target], SHADOW_MODEL_DIR / f"wnba_{target}_stat_model_production_structure.pkl")
    return models


def build_blend_predictions(valid: pd.DataFrame, models: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for blend in BLENDS:
        blended = valid.copy()
        blended["minutes"] = (
            (1.0 - blend) * blended["production_minutes_feature"]
            + blend * blended["role_pattern_minutes_feature"]
        )
        stat_predictions = {}
        for target, bundle in models.items():
            target_frame = blended.dropna(subset=[target]).copy()
            pred = predict_bundle(bundle, target_frame)
            stat_predictions[target] = target_frame[
                ["game_date", "player_key", "player_name", "team", "opponent", target]
            ].copy()
            stat_predictions[target]["market"] = target
            stat_predictions[target]["actual_result"] = target_frame[target].to_numpy()
            stat_predictions[target]["projection"] = pred
            stat_predictions[target]["blend"] = blend
            rows.append(stat_predictions[target].drop(columns=[target]))

        components = [stat_predictions[target] for target in BASE_COMPONENTS if target in stat_predictions]
        if len(components) == len(BASE_COMPONENTS):
            wide = pd.concat(components, ignore_index=True).pivot_table(
                index=["game_date", "player_key", "player_name", "team", "opponent", "blend"],
                columns="market",
                values=["actual_result", "projection"],
                aggfunc="first",
            )
            wide.columns = [f"{value}_{market}" for value, market in wide.columns]
            wide = wide.reset_index()
            for market, parts in COMBO_MARKETS.items():
                combo = wide[["game_date", "player_key", "player_name", "team", "opponent", "blend"]].copy()
                combo["market"] = market
                combo["actual_result"] = sum(wide[f"actual_result_{part}"] for part in parts)
                combo["projection"] = sum(wide[f"projection_{part}"] for part in parts)
                rows.append(combo)
    return pd.concat(rows, ignore_index=True)


def validation_report(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (market, blend), group in predictions[predictions["market"].isin(REPLAY_MARKETS)].groupby(["market", "blend"]):
        metrics = metric_values(group["actual_result"], group["projection"].to_numpy())
        rows.append(
            {
                "market": market,
                "blend": blend,
                "sample_size": int(len(group)),
                **metrics,
            }
        )
    return pd.DataFrame(rows).sort_values(["market", "blend"]).reset_index(drop=True)


def normalize_ledger(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    ledger = frame.copy()
    ledger.columns = [str(column).strip().lower() for column in ledger.columns]
    required = ["date", "player_key", "market", "sportsbook_line", "actual_result", "result", "predicted_hit_rate"]
    missing = [column for column in required if column not in ledger.columns]
    if missing:
        raise ValueError(f"graded_predictions_ledger.csv missing required columns: {missing}")
    ledger["date"] = pd.to_datetime(ledger["date"], errors="coerce").dt.normalize()
    ledger["player_key"] = ledger["player_key"].astype(str).str.strip()
    ledger["market"] = ledger["market"].astype(str).str.lower().str.strip()
    ledger["result"] = ledger["result"].astype(str).str.lower().str.strip()
    for column in ["sportsbook_line", "actual_result", "projection", "predicted_hit_rate"]:
        if column not in ledger.columns:
            ledger[column] = np.nan
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


def replay_report(predictions: pd.DataFrame, validation: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    pred = predictions.copy()
    pred["date"] = pd.to_datetime(pred["game_date"], errors="coerce").dt.normalize()
    merged = ledger[ledger["market"].isin(REPLAY_MARKETS)].merge(
        pred[pred["market"].isin(REPLAY_MARKETS)],
        on=["date", "player_key", "market"],
        how="inner",
        suffixes=("_ledger", ""),
    )
    if merged.empty:
        return pd.DataFrame()
    rmse_lookup = validation.set_index(["market", "blend"])["rmse"].to_dict()
    rows = []
    for (market, blend), group in merged.groupby(["market", "blend"]):
        group = group.copy()
        group["blend_side"] = [projected_side(p, line) for p, line in zip(group["projection"], group["sportsbook_line"])]
        group["blend_result"] = [
            grade_side(side, line, actual)
            for side, line, actual in zip(group["blend_side"], group["sportsbook_line"], group["actual_result_ledger"])
        ]
        error = group["projection"] - group["actual_result_ledger"]
        rmse = float(math.sqrt((error**2).mean()))
        edge = (group["projection"] - group["sportsbook_line"]).abs()
        conf = (0.50 + edge / max(2.0 * rmse_lookup.get((market, blend), rmse), 1e-9)).clip(0.50, 0.75)
        wr = win_rate(group, "blend_result")
        rows.append(
            {
                "market": market,
                "blend": blend,
                "sample_size": int(len(group)),
                "mae": float(error.abs().mean()),
                "rmse": rmse,
                "win_rate": wr,
                "avg_confidence": float(conf.mean()),
                "calibration_error": abs(float(conf.mean()) - wr) if pd.notna(wr) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(["market", "blend"]).reset_index(drop=True)


def recommendation(replay: pd.DataFrame) -> dict:
    rows = []
    for market, group in replay.groupby("market"):
        baseline = group[group["blend"] == 0.0]
        if baseline.empty:
            continue
        base = baseline.iloc[0]
        candidates = group[
            (group["blend"] > 0.0)
            & (group["sample_size"] >= MIN_RECOMMEND_SAMPLE)
            & (group["win_rate"] > base["win_rate"])
            & (group["mae"] <= base["mae"])
        ].copy()
        if candidates.empty:
            rows.append(
                {
                    "market": market,
                    "recommended_blend": 0.0,
                    "decision": "keep_production_minutes",
                    "reason": "No shadow blend improved win rate without worsening MAE.",
                    "baseline_win_rate": float(base["win_rate"]) if pd.notna(base["win_rate"]) else None,
                    "baseline_mae": float(base["mae"]),
                }
            )
            continue
        candidates["win_rate_gain"] = candidates["win_rate"] - base["win_rate"]
        candidates["mae_gain"] = base["mae"] - candidates["mae"]
        best = candidates.sort_values(["win_rate_gain", "mae_gain"], ascending=[False, False]).iloc[0]
        rows.append(
            {
                "market": market,
                "recommended_blend": float(best["blend"]),
                "decision": "continue_shadow_canary",
                "reason": "Blend improved win rate and did not worsen MAE in historical replay; fresh canary still required.",
                "sample_size": int(best["sample_size"]),
                "baseline_win_rate": float(base["win_rate"]) if pd.notna(base["win_rate"]) else None,
                "blend_win_rate": float(best["win_rate"]) if pd.notna(best["win_rate"]) else None,
                "win_rate_delta": float(best["win_rate"] - base["win_rate"]) if pd.notna(best["win_rate"]) and pd.notna(base["win_rate"]) else None,
                "baseline_mae": float(base["mae"]),
                "blend_mae": float(best["mae"]),
                "mae_delta": float(best["mae"] - base["mae"]),
            }
        )
    return {
        "created_at_utc": utc_now(),
        "decision": "do_not_promote_to_production",
        "reason": "Hybrid minutes blends are shadow-only. Per-market production promotion requires historical replay plus fresh canary.",
        "market_recommendations": rows,
        "gates": {
            "recommend_only_if_win_rate_improves": True,
            "recommend_only_if_mae_not_worse": True,
            "minimum_market_sample": MIN_RECOMMEND_SAMPLE,
            "fresh_canary_required_for_promotion": True,
        },
    }


def write_summary(minutes: pd.DataFrame, replay: pd.DataFrame, rec: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# WNBA Phase 11 Hybrid Minutes Shadow",
        "",
        f"Generated: {utc_now()}",
        "",
        "Shadow-only test of role-pattern minutes as an alternative `minutes` feature inside the existing stat model structure.",
        "",
        "## Minutes Comparison",
    ]
    for _, row in minutes.iterrows():
        lines.append(f"- {row['scenario']}: MAE {row['mae']:.3f}, RMSE {row['rmse']:.3f}, R2 {row['r2']:.3f}, n={int(row['sample_size'])}")
    lines.extend(["", "## Recommended Historical Blends"])
    for item in rec["market_recommendations"]:
        if item["recommended_blend"] == 0.0:
            lines.append(f"- {item['market']}: keep production minutes; {item['reason']}")
        else:
            lines.append(
                f"- {item['market']}: blend {item['recommended_blend']:.2f}; "
                f"win-rate delta {item.get('win_rate_delta', 0):+.1%}; MAE delta {item.get('mae_delta', 0):+.3f}"
            )
    lines.extend(
        [
            "",
            "## Production Safety",
            "- Default OFF unless WNBA_ENABLE_HYBRID_MINUTES_SHADOW=1 is set.",
            "- Does not write production models, grading files, publish outputs, or public boards.",
        ]
    )
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    logger = setup_logging("wnba_hybrid_minutes_shadow")
    if not enabled():
        logger.info("WNBA_ENABLE_HYBRID_MINUTES_SHADOW is off; no reports generated.")
        return

    SHADOW_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    dataset = pd.read_csv(DATASET_PATH, parse_dates=["game_date"])
    dataset = add_role_features(dataset)
    train, valid, minutes = train_minutes_models(dataset)
    stat_models = train_stat_models(train)
    predictions = build_blend_predictions(valid, stat_models)
    validation = validation_report(predictions)
    ledger = normalize_ledger(read_csv(LEDGER_PATH))
    replay = replay_report(predictions, validation, ledger)
    rec = recommendation(replay)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    minutes.to_csv(MINUTES_REPORT_PATH, index=False)
    validation.to_csv(BLEND_VALIDATION_PATH, index=False)
    replay.to_csv(MARKET_REPLAY_PATH, index=False)
    RECOMMENDATION_PATH.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    write_summary(minutes, replay, rec)
    logger.info("Wrote hybrid minutes shadow report: %s", SUMMARY_PATH)


if __name__ == "__main__":
    main()
