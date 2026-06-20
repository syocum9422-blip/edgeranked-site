from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from wnba_model_config import DATASET_PATH, PROCESSED_DIR
from wnba_model_utils import clean_feature_frame, setup_logging


ROOT = Path(__file__).resolve().parent
LEARNING_DIR = ROOT / "learning"
REPORTS_DIR = LEARNING_DIR / "reports"
LEDGER_PATH = LEARNING_DIR / "graded_predictions_ledger.csv"
CANARY_LEDGER_PATH = LEARNING_DIR / "wnba_selective_feature_canary_ledger.csv"
STATE_PATH = LEARNING_DIR / "wnba_selective_feature_canary_state.json"
SHADOW_MODEL_DIR = ROOT / "data" / "models" / "shadow_feature_upgrade"

DAILY_REPORT_PATH = PROCESSED_DIR / "wnba_selective_feature_canary_daily_report.csv"
ROLLING_REPORT_PATH = PROCESSED_DIR / "wnba_selective_feature_canary_rolling_report.csv"
MARKET_REPORT_PATH = PROCESSED_DIR / "wnba_selective_feature_canary_market_report.csv"
CONFIDENCE_BUCKET_PATH = PROCESSED_DIR / "wnba_selective_feature_canary_confidence_buckets.csv"
PROMOTION_PATH = PROCESSED_DIR / "wnba_selective_feature_canary_promotion_recommendation.json"
SUMMARY_PATH = REPORTS_DIR / "wnba_selective_feature_canary_report.md"

SELECTIVE_MARKETS = {"points", "rebounds"}
TARGET_TO_MODEL = {
    "points": "wnba_points_upgraded_feature_shadow.joblib",
    "rebounds": "wnba_rebounds_upgraded_feature_shadow.joblib",
}
CONFIDENCE_BINS = [0.50, 0.55, 0.60, 0.65, 0.70, 1.01]
CONFIDENCE_LABELS = ["50-55", "55-60", "60-65", "65-70", "70+"]
MIN_PROMOTION_SAMPLE = 100
MIN_WIN_RATE_GAIN = 0.04
EPS = 1e-12


def enabled() -> bool:
    values = [
        os.environ.get("WNBA_ENABLE_SELECTIVE_FEATURE_CANARY", ""),
        os.environ.get("WNBA_ENABLE_SELECTIVE_FEATURE_SHADOW", ""),
    ]
    return any(value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    } for value in values)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(state: dict) -> None:
    LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def ensure_shadow_models(logger) -> None:
    missing = [name for name in TARGET_TO_MODEL.values() if not (SHADOW_MODEL_DIR / name).exists()]
    if not missing:
        return
    logger.info("Selective feature shadow models missing; running Phase 8 feature upgrade shadow first.")
    env = os.environ.copy()
    env["WNBA_ENABLE_FEATURE_UPGRADE_SHADOW"] = "1"
    subprocess.run([sys.executable, str(ROOT / "wnba_feature_upgrade_shadow.py")], check=True, env=env)


def normalize_ledger(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    ledger = frame.copy()
    ledger.columns = [str(column).strip().lower() for column in ledger.columns]
    required = [
        "prediction_id",
        "date",
        "player_key",
        "market",
        "side",
        "projection",
        "sportsbook_line",
        "actual_result",
        "result",
        "created_at_utc",
    ]
    missing = [column for column in required if column not in ledger.columns]
    if missing:
        raise ValueError(f"graded_predictions_ledger.csv missing required columns: {missing}")
    ledger["date"] = pd.to_datetime(ledger["date"], errors="coerce").dt.normalize()
    ledger["created_at_utc"] = pd.to_datetime(ledger["created_at_utc"], errors="coerce", utc=True)
    ledger["player_key"] = ledger["player_key"].astype(str).str.strip()
    ledger["market"] = ledger["market"].astype(str).str.lower().str.strip()
    ledger["side"] = ledger["side"].astype(str).str.lower().str.strip()
    ledger["result"] = ledger["result"].astype(str).str.lower().str.strip()
    for column in ["projection", "sportsbook_line", "actual_result", "predicted_hit_rate"]:
        if column not in ledger.columns:
            ledger[column] = np.nan
        ledger[column] = pd.to_numeric(ledger[column], errors="coerce")
    return ledger[
        ledger["market"].isin(SELECTIVE_MARKETS)
        & ledger["result"].isin(["win", "loss", "push"])
        & ledger["date"].notna()
        & ledger["created_at_utc"].notna()
    ].copy()


def prediction_features(dataset: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    features = dataset.copy()
    features["game_date"] = pd.to_datetime(features["game_date"], errors="coerce").dt.normalize()
    features["player_key"] = features["player_key"].astype(str).str.strip()
    merged = rows.merge(
        features,
        left_on=["date", "player_key"],
        right_on=["game_date", "player_key"],
        how="left",
        suffixes=("", "_feature"),
    )
    return merged


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


def normalize_probability(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if values.dropna().gt(1.0).any():
        values = values / 100.0
    return values.clip(0.50, 0.99)


def shadow_confidence(projection: pd.Series, line: pd.Series, rmse: float) -> pd.Series:
    edge = (pd.to_numeric(projection, errors="coerce") - pd.to_numeric(line, errors="coerce")).abs()
    return (0.50 + edge / max(2.0 * rmse, EPS)).clip(0.50, 0.75)


def score_new_rows(rows: pd.DataFrame, logger) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()
    ensure_shadow_models(logger)
    dataset = pd.read_csv(DATASET_PATH, parse_dates=["game_date"])
    merged = prediction_features(dataset, rows)
    scored = []
    for market, group in merged.groupby("market", dropna=False):
        model_path = SHADOW_MODEL_DIR / TARGET_TO_MODEL[market]
        bundle = joblib.load(model_path)
        feature_list = bundle["feature_list"]
        missing_features = [feature for feature in feature_list if feature not in group.columns]
        if missing_features:
            raise ValueError(f"Feature dataset missing shadow model features for {market}: {missing_features}")
        pred = np.clip(
            (
                bundle["ridge_model"].predict(clean_feature_frame(group, feature_list))
                + bundle["tree_model"].predict(clean_feature_frame(group, feature_list))
            )
            / 2.0,
            0,
            None,
        )
        rmse = float(bundle.get("metrics", {}).get("rmse", 1.0) or 1.0)
        item = group.copy()
        item["selective_projection"] = pred
        item["selective_projected_side"] = [
            projected_side(projection, line)
            for projection, line in zip(item["selective_projection"], item["sportsbook_line"])
        ]
        item["selective_result"] = [
            directional_result(side, line, actual)
            for side, line, actual in zip(
                item["selective_projected_side"],
                item["sportsbook_line"],
                item["actual_result"],
            )
        ]
        item["selective_confidence"] = shadow_confidence(
            item["selective_projection"],
            item["sportsbook_line"],
            rmse,
        )
        scored.append(item)
    out = pd.concat(scored, ignore_index=True)
    out["canary_run_date"] = utc_today()
    out["canary_created_at_utc"] = utc_now()
    out["production_projection"] = out["projection"]
    out["production_result"] = out["result"]
    out["production_projected_side"] = out["side"]
    out["production_confidence"] = normalize_probability(out["predicted_hit_rate"]).fillna(0.50)
    for scenario in ["production", "selective"]:
        projection_col = "production_projection" if scenario == "production" else "selective_projection"
        result_col = "production_result" if scenario == "production" else "selective_result"
        error = pd.to_numeric(out[projection_col], errors="coerce") - pd.to_numeric(out["actual_result"], errors="coerce")
        out[f"{scenario}_absolute_error"] = error.abs()
        out[f"{scenario}_squared_error"] = error**2
        out[f"{scenario}_is_win"] = out[result_col].eq("win")
        out[f"{scenario}_is_decision"] = out[result_col].isin(["win", "loss"])
    keep = [
        "canary_run_date",
        "canary_created_at_utc",
        "prediction_id",
        "date",
        "player",
        "player_key",
        "team",
        "opponent",
        "market",
        "sportsbook_line",
        "actual_result",
        "production_projection",
        "production_projected_side",
        "production_result",
        "production_confidence",
        "production_absolute_error",
        "production_squared_error",
        "selective_projection",
        "selective_projected_side",
        "selective_result",
        "selective_confidence",
        "selective_absolute_error",
        "selective_squared_error",
        "created_at_utc",
    ]
    return out[[column for column in keep if column in out.columns]].copy()


def append_canary_rows(scored: pd.DataFrame) -> pd.DataFrame:
    existing = read_csv(CANARY_LEDGER_PATH)
    if scored.empty:
        return existing
    if not existing.empty and "prediction_id" in existing.columns:
        scored = scored[~scored["prediction_id"].isin(set(existing["prediction_id"].astype(str)))]
    combined = pd.concat([existing, scored], ignore_index=True) if not existing.empty else scored
    combined = combined.drop_duplicates("prediction_id", keep="last")
    LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_csv(CANARY_LEDGER_PATH, index=False)
    return combined


def rate(frame: pd.DataFrame, scenario: str) -> float:
    result_col = f"{scenario}_result"
    decisions = frame[frame[result_col].isin(["win", "loss"])]
    if decisions.empty:
        return np.nan
    return float(decisions[result_col].eq("win").mean())


def summarize(frame: pd.DataFrame, scenario: str, run_date: str | None = None, market: str = "all") -> dict:
    subset = frame.copy()
    if run_date is not None:
        subset = subset[subset["canary_run_date"] == run_date]
    if market != "all":
        subset = subset[subset["market"] == market]
    if subset.empty:
        return {
            "canary_run_date": run_date or "all",
            "scenario": scenario,
            "market": market,
            "sample_size": 0,
            "win_rate": np.nan,
            "mae": np.nan,
            "rmse": np.nan,
            "avg_confidence": np.nan,
            "calibration_error": np.nan,
        }
    wr = rate(subset, scenario)
    avg_conf = float(pd.to_numeric(subset[f"{scenario}_confidence"], errors="coerce").mean())
    return {
        "canary_run_date": run_date or "all",
        "scenario": scenario,
        "market": market,
        "sample_size": int(len(subset)),
        "win_rate": wr,
        "mae": float(pd.to_numeric(subset[f"{scenario}_absolute_error"], errors="coerce").mean()),
        "rmse": float(math.sqrt(pd.to_numeric(subset[f"{scenario}_squared_error"], errors="coerce").mean())),
        "avg_confidence": avg_conf,
        "calibration_error": abs(avg_conf - wr) if pd.notna(wr) else np.nan,
    }


def build_reports(canary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if canary.empty:
        empty_daily = pd.DataFrame(
            columns=["canary_run_date", "scenario", "market", "sample_size", "win_rate", "mae", "rmse", "avg_confidence", "calibration_error"]
        )
        empty_rolling = pd.DataFrame(
            columns=["as_of_date", "scenario", "window_days", "sample_size", "win_rate", "mae", "rmse", "calibration_error"]
        )
        empty_buckets = pd.DataFrame(
            columns=["scenario", "market", "confidence_bucket", "sample_size", "win_rate", "avg_confidence", "calibration_error"]
        )
        return empty_daily, empty_rolling, empty_daily.copy(), empty_buckets

    canary = canary.copy()
    canary["canary_run_date"] = pd.to_datetime(canary["canary_run_date"], errors="coerce").dt.date.astype(str)
    scenarios = ["production", "selective"]
    daily_rows = []
    for run_date in sorted(canary["canary_run_date"].dropna().unique()):
        for scenario in scenarios:
            daily_rows.append(summarize(canary, scenario, run_date, "all"))
            for market in sorted(SELECTIVE_MARKETS):
                daily_rows.append(summarize(canary, scenario, run_date, market))
    daily = pd.DataFrame(daily_rows)

    rolling_rows = []
    dates = sorted(canary["canary_run_date"].dropna().unique())
    for as_of in dates:
        as_of_ts = pd.Timestamp(as_of)
        for window in [3, 7]:
            start = (as_of_ts - pd.Timedelta(days=window - 1)).date().isoformat()
            window_frame = canary[(canary["canary_run_date"] >= start) & (canary["canary_run_date"] <= as_of)]
            for scenario in scenarios:
                row = summarize(window_frame, scenario)
                row.update({"as_of_date": as_of, "window_days": window})
                rolling_rows.append(row)
    rolling = pd.DataFrame(rolling_rows)

    market_rows = []
    for scenario in scenarios:
        market_rows.append(summarize(canary, scenario, market="all"))
        for market in sorted(SELECTIVE_MARKETS):
            market_rows.append(summarize(canary, scenario, market=market))
    market = pd.DataFrame(market_rows)

    bucket_rows = []
    for scenario in scenarios:
        bucket_col = f"{scenario}_confidence_bucket"
        canary[bucket_col] = pd.cut(
            pd.to_numeric(canary[f"{scenario}_confidence"], errors="coerce"),
            bins=CONFIDENCE_BINS,
            labels=CONFIDENCE_LABELS,
            include_lowest=True,
            right=False,
        ).astype(str)
        for (market_name, bucket), group in canary.groupby(["market", bucket_col], dropna=False):
            wr = rate(group, scenario)
            avg_conf = float(pd.to_numeric(group[f"{scenario}_confidence"], errors="coerce").mean())
            bucket_rows.append(
                {
                    "scenario": scenario,
                    "market": market_name,
                    "confidence_bucket": bucket,
                    "sample_size": int(len(group)),
                    "win_rate": wr,
                    "avg_confidence": avg_conf,
                    "calibration_error": abs(avg_conf - wr) if pd.notna(wr) else np.nan,
                }
            )
    buckets = pd.DataFrame(bucket_rows)
    return daily, rolling, market, buckets


def promotion_recommendation(market_report: pd.DataFrame) -> dict:
    if market_report.empty:
        sample_size = 0
        prod = {}
        challenger = {}
    else:
        overall = market_report[(market_report["market"] == "all")].set_index("scenario")
        prod = overall.loc["production"].to_dict() if "production" in overall.index else {}
        challenger = overall.loc["selective"].to_dict() if "selective" in overall.index else {}
        sample_size = int(challenger.get("sample_size", 0) or 0)
    win_delta = float(challenger.get("win_rate", np.nan) - prod.get("win_rate", np.nan)) if prod and challenger else np.nan
    mae_delta = float(challenger.get("mae", np.nan) - prod.get("mae", np.nan)) if prod and challenger else np.nan
    calibration_delta = (
        float(challenger.get("calibration_error", np.nan) - prod.get("calibration_error", np.nan))
        if prod and challenger
        else np.nan
    )
    qualifies = (
        sample_size >= MIN_PROMOTION_SAMPLE
        and pd.notna(win_delta)
        and win_delta >= MIN_WIN_RATE_GAIN
        and pd.notna(mae_delta)
        and mae_delta <= 0
        and pd.notna(calibration_delta)
        and calibration_delta <= 0
    )
    return {
        "created_at_utc": utc_now(),
        "decision": "recommend_production_enablement" if qualifies else "do_not_promote",
        "reason": (
            "Selective canary cleared win-rate, MAE, calibration, and sample-size promotion gates."
            if qualifies
            else "Selective canary has not yet cleared all promotion gates on new graded picks."
        ),
        "sample_size": sample_size,
        "win_rate_delta": win_delta,
        "mae_delta": mae_delta,
        "calibration_error_delta": calibration_delta,
        "gates": {
            "minimum_new_graded_picks": MIN_PROMOTION_SAMPLE,
            "required_win_rate_delta": MIN_WIN_RATE_GAIN,
            "mae_must_be_no_worse": True,
            "calibration_must_be_no_worse": True,
        },
    }


def write_summary(daily: pd.DataFrame, rolling: pd.DataFrame, market: pd.DataFrame, recommendation: dict, new_rows: int) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# WNBA Phase 10 Selective Feature Canary",
        "",
        f"Generated: {utc_now()}",
        "",
        f"New rows processed this run: {new_rows}",
        "",
        "This is a shadow-only canary for upgraded points/rebounds feature models. It appends only newly graded rows after the canary checkpoint.",
        "",
        "## Report Paths",
        f"- Daily: `{DAILY_REPORT_PATH}`",
        f"- Rolling: `{ROLLING_REPORT_PATH}`",
        f"- Market: `{MARKET_REPORT_PATH}`",
        f"- Confidence buckets: `{CONFIDENCE_BUCKET_PATH}`",
        f"- Promotion JSON: `{PROMOTION_PATH}`",
        "",
        "## Current Aggregate",
    ]
    if market.empty:
        lines.append("- No new graded canary rows have been accumulated yet.")
    else:
        for _, row in market[market["market"] == "all"].iterrows():
            wr = row["win_rate"]
            wr_text = "n/a" if pd.isna(wr) else f"{wr:.1%}"
            lines.append(
                f"- {row['scenario']}: n={int(row['sample_size'])}, win rate {wr_text}, "
                f"MAE {row['mae']:.3f}, RMSE {row['rmse']:.3f}, calibration error {row['calibration_error']:.3f}"
            )
    lines.extend(
        [
            "",
            "## Promotion Recommendation",
            f"- Decision: **{recommendation['decision']}**",
            f"- Reason: {recommendation['reason']}",
            "",
            "## Production Safety",
            "- Default behavior remains OFF unless WNBA_ENABLE_SELECTIVE_FEATURE_SHADOW=1 or WNBA_ENABLE_SELECTIVE_FEATURE_CANARY=1 is set.",
            "- Production model files, grading files, public board, and publish outputs are not written.",
        ]
    )
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    logger = setup_logging("wnba_selective_feature_canary")
    if not enabled():
        logger.info("WNBA_ENABLE_SELECTIVE_FEATURE_CANARY/WNBA_ENABLE_SELECTIVE_FEATURE_SHADOW is off; no canary reports generated.")
        return

    ledger = normalize_ledger(read_csv(LEDGER_PATH))
    state = load_state()
    max_seen = state.get("max_created_at_utc")
    if not max_seen:
        high_water = ledger["created_at_utc"].max()
        state = {
            "initialized_at_utc": utc_now(),
            "max_created_at_utc": high_water.isoformat() if pd.notna(high_water) else utc_now(),
            "note": "Initialized without backfill; future runs process new graded ledger rows only.",
        }
        save_state(state)
        canary = append_canary_rows(pd.DataFrame())
        daily, rolling, market, buckets = build_reports(canary)
        recommendation = promotion_recommendation(market)
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        daily.to_csv(DAILY_REPORT_PATH, index=False)
        rolling.to_csv(ROLLING_REPORT_PATH, index=False)
        market.to_csv(MARKET_REPORT_PATH, index=False)
        buckets.to_csv(CONFIDENCE_BUCKET_PATH, index=False)
        PROMOTION_PATH.write_text(json.dumps(recommendation, indent=2) + "\n", encoding="utf-8")
        write_summary(daily, rolling, market, recommendation, 0)
        logger.info("Initialized selective feature canary checkpoint without backfill.")
        return

    cutoff = pd.Timestamp(max_seen)
    new_rows = ledger[ledger["created_at_utc"] > cutoff].copy()
    existing = read_csv(CANARY_LEDGER_PATH)
    if not existing.empty and "prediction_id" in existing.columns:
        new_rows = new_rows[~new_rows["prediction_id"].isin(set(existing["prediction_id"].astype(str)))]

    scored = score_new_rows(new_rows, logger)
    canary = append_canary_rows(scored)
    if not ledger.empty:
        state["max_created_at_utc"] = ledger["created_at_utc"].max().isoformat()
        state["last_run_at_utc"] = utc_now()
        save_state(state)

    daily, rolling, market, buckets = build_reports(canary)
    recommendation = promotion_recommendation(market)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    daily.to_csv(DAILY_REPORT_PATH, index=False)
    rolling.to_csv(ROLLING_REPORT_PATH, index=False)
    market.to_csv(MARKET_REPORT_PATH, index=False)
    buckets.to_csv(CONFIDENCE_BUCKET_PATH, index=False)
    PROMOTION_PATH.write_text(json.dumps(recommendation, indent=2) + "\n", encoding="utf-8")
    write_summary(daily, rolling, market, recommendation, len(scored))
    logger.info("Selective feature canary processed %s new rows.", len(scored))


if __name__ == "__main__":
    main()
