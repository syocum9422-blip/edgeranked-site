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
CANARY_LEDGER_PATH = LEARNING_DIR / "wnba_combo_hybrid_minutes_canary_ledger.csv"
STATE_PATH = LEARNING_DIR / "wnba_combo_hybrid_minutes_canary_state.json"
SHADOW_MODEL_DIR = ROOT / "data" / "models" / "shadow_hybrid_minutes"

DAILY_REPORT_PATH = PROCESSED_DIR / "wnba_combo_hybrid_minutes_canary_daily_report.csv"
ROLLING_REPORT_PATH = PROCESSED_DIR / "wnba_combo_hybrid_minutes_canary_rolling_report.csv"
MARKET_REPORT_PATH = PROCESSED_DIR / "wnba_combo_hybrid_minutes_canary_market_report.csv"
CONFIDENCE_BUCKET_PATH = PROCESSED_DIR / "wnba_combo_hybrid_minutes_canary_confidence_buckets.csv"
PROMOTION_PATH = PROCESSED_DIR / "wnba_combo_hybrid_minutes_canary_promotion_recommendation.json"
SUMMARY_PATH = REPORTS_DIR / "wnba_combo_hybrid_minutes_canary_report.md"

MARKET_BLEND = {
    "pa": 0.25,
    "pr": 1.00,
    "pra": 0.50,
}
MARKET_COMPONENTS = {
    "pa": ["points", "assists"],
    "pr": ["points", "rebounds"],
    "pra": ["points", "rebounds", "assists"],
}
STAT_MODEL_FILES = {
    "points": "wnba_points_stat_model_production_structure.pkl",
    "rebounds": "wnba_rebounds_stat_model_production_structure.pkl",
    "assists": "wnba_assists_stat_model_production_structure.pkl",
}
PRODUCTION_MINUTES_MODEL = "wnba_minutes_production_like.pkl"
ROLE_MINUTES_MODEL = "wnba_minutes_role_pattern.pkl"
CONFIDENCE_BINS = [0.50, 0.55, 0.60, 0.65, 0.70, 1.01]
CONFIDENCE_LABELS = ["50-55", "55-60", "60-65", "65-70", "70+"]
MIN_PROMOTION_SAMPLE = 40
MIN_WIN_RATE_GAIN = 0.03
EPS = 1e-12


def enabled() -> bool:
    return os.environ.get("WNBA_ENABLE_COMBO_HYBRID_MINUTES_CANARY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
    required = [PRODUCTION_MINUTES_MODEL, ROLE_MINUTES_MODEL, *STAT_MODEL_FILES.values()]
    missing = [name for name in required if not (SHADOW_MODEL_DIR / name).exists()]
    if not missing:
        return
    logger.info("Hybrid minutes shadow artifacts missing; running Phase 11 shadow first.")
    env = os.environ.copy()
    env["WNBA_ENABLE_HYBRID_MINUTES_SHADOW"] = "1"
    subprocess.run([sys.executable, str(ROOT / "wnba_hybrid_minutes_shadow.py")], check=True, env=env)


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
        ledger["market"].isin(MARKET_BLEND)
        & ledger["result"].isin(["win", "loss", "push"])
        & ledger["date"].notna()
        & ledger["created_at_utc"].notna()
    ].copy()


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


def prediction_features(rows: pd.DataFrame) -> pd.DataFrame:
    dataset = pd.read_csv(DATASET_PATH, parse_dates=["game_date"])
    dataset = add_role_features(dataset)
    dataset["game_date"] = pd.to_datetime(dataset["game_date"], errors="coerce").dt.normalize()
    dataset["player_key"] = dataset["player_key"].astype(str).str.strip()
    return rows.merge(
        dataset,
        left_on=["date", "player_key"],
        right_on=["game_date", "player_key"],
        how="left",
        suffixes=("", "_feature"),
    )


def predict_bundle(bundle: dict, frame: pd.DataFrame) -> np.ndarray:
    x = clean_feature_frame(frame, bundle["feature_list"])
    return np.clip((bundle["ridge_model"].predict(x) + bundle["tree_model"].predict(x)) / 2.0, 0, None)


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


def normalize_probability(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if values.dropna().gt(1.0).any():
        values = values / 100.0
    return values.clip(0.50, 0.99)


def score_new_rows(rows: pd.DataFrame, logger) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()
    ensure_shadow_models(logger)
    merged = prediction_features(rows)
    production_minutes_model = joblib.load(SHADOW_MODEL_DIR / PRODUCTION_MINUTES_MODEL)
    role_minutes_model = joblib.load(SHADOW_MODEL_DIR / ROLE_MINUTES_MODEL)
    stat_models = {
        stat: joblib.load(SHADOW_MODEL_DIR / filename)
        for stat, filename in STAT_MODEL_FILES.items()
    }

    scored_frames = []
    for market, group in merged.groupby("market", dropna=False):
        blend = MARKET_BLEND[market]
        item = group.copy()
        prod_minutes = predict_bundle(production_minutes_model, item)
        role_minutes = predict_bundle(role_minutes_model, item)
        item["production_minutes_feature"] = prod_minutes
        item["role_pattern_minutes_feature"] = role_minutes
        item["hybrid_minutes_feature"] = (1.0 - blend) * prod_minutes + blend * role_minutes
        item["minutes"] = item["hybrid_minutes_feature"]
        item["hybrid_projection"] = 0.0
        for component in MARKET_COMPONENTS[market]:
            component_pred = predict_bundle(stat_models[component], item)
            item[f"hybrid_{component}_projection"] = component_pred
            item["hybrid_projection"] += component_pred
        item["hybrid_side"] = [
            projected_side(projection, line)
            for projection, line in zip(item["hybrid_projection"], item["sportsbook_line"])
        ]
        item["hybrid_result"] = [
            grade_side(side, line, actual)
            for side, line, actual in zip(item["hybrid_side"], item["sportsbook_line"], item["actual_result"])
        ]
        hybrid_error = item["hybrid_projection"] - item["actual_result"]
        production_error = item["projection"] - item["actual_result"]
        item["hybrid_absolute_error"] = hybrid_error.abs()
        item["hybrid_squared_error"] = hybrid_error**2
        item["production_absolute_error"] = production_error.abs()
        item["production_squared_error"] = production_error**2
        rmse = math.sqrt(float((hybrid_error**2).mean())) if len(item) else 1.0
        edge = (item["hybrid_projection"] - item["sportsbook_line"]).abs()
        item["hybrid_confidence"] = (0.50 + edge / max(2.0 * rmse, EPS)).clip(0.50, 0.75)
        scored_frames.append(item)

    out = pd.concat(scored_frames, ignore_index=True)
    out["canary_run_date"] = utc_today()
    out["canary_created_at_utc"] = utc_now()
    out["production_projection"] = out["projection"]
    out["production_side"] = out["side"]
    out["production_result"] = out["result"]
    out["production_confidence"] = normalize_probability(out["predicted_hit_rate"]).fillna(0.50)
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
        "production_side",
        "production_result",
        "production_confidence",
        "production_absolute_error",
        "production_squared_error",
        "production_minutes_feature",
        "role_pattern_minutes_feature",
        "hybrid_minutes_feature",
        "hybrid_projection",
        "hybrid_side",
        "hybrid_result",
        "hybrid_confidence",
        "hybrid_absolute_error",
        "hybrid_squared_error",
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


def win_rate(frame: pd.DataFrame, scenario: str) -> float:
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
    wr = win_rate(subset, scenario)
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
        daily_cols = ["canary_run_date", "scenario", "market", "sample_size", "win_rate", "mae", "rmse", "avg_confidence", "calibration_error"]
        rolling_cols = ["as_of_date", "scenario", "window_days", "sample_size", "win_rate", "mae", "rmse", "calibration_error"]
        bucket_cols = ["scenario", "market", "confidence_bucket", "sample_size", "win_rate", "avg_confidence", "calibration_error"]
        return pd.DataFrame(columns=daily_cols), pd.DataFrame(columns=rolling_cols), pd.DataFrame(columns=daily_cols), pd.DataFrame(columns=bucket_cols)

    canary = canary.copy()
    canary["canary_run_date"] = pd.to_datetime(canary["canary_run_date"], errors="coerce").dt.date.astype(str)
    scenarios = ["production", "hybrid"]
    markets = sorted(MARKET_BLEND)
    daily_rows = []
    for run_date in sorted(canary["canary_run_date"].dropna().unique()):
        for scenario in scenarios:
            daily_rows.append(summarize(canary, scenario, run_date, "all"))
            for market in markets:
                daily_rows.append(summarize(canary, scenario, run_date, market))
    daily = pd.DataFrame(daily_rows)

    rolling_rows = []
    for as_of in sorted(canary["canary_run_date"].dropna().unique()):
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
        for market in markets:
            market_rows.append(summarize(canary, scenario, market=market))
    market_report = pd.DataFrame(market_rows)

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
        for (market, bucket), group in canary.groupby(["market", bucket_col], dropna=False):
            wr = win_rate(group, scenario)
            avg_conf = float(pd.to_numeric(group[f"{scenario}_confidence"], errors="coerce").mean())
            bucket_rows.append(
                {
                    "scenario": scenario,
                    "market": market,
                    "confidence_bucket": bucket,
                    "sample_size": int(len(group)),
                    "win_rate": wr,
                    "avg_confidence": avg_conf,
                    "calibration_error": abs(avg_conf - wr) if pd.notna(wr) else np.nan,
                }
            )
    return daily, rolling, market_report, pd.DataFrame(bucket_rows)


def promotion_recommendation(market_report: pd.DataFrame) -> dict:
    if market_report.empty:
        sample_size = 0
        win_delta = mae_delta = calibration_delta = np.nan
    else:
        overall = market_report[market_report["market"] == "all"].set_index("scenario")
        prod = overall.loc["production"].to_dict() if "production" in overall.index else {}
        hybrid = overall.loc["hybrid"].to_dict() if "hybrid" in overall.index else {}
        sample_size = int(hybrid.get("sample_size", 0) or 0)
        win_delta = float(hybrid.get("win_rate", np.nan) - prod.get("win_rate", np.nan)) if prod and hybrid else np.nan
        mae_delta = float(hybrid.get("mae", np.nan) - prod.get("mae", np.nan)) if prod and hybrid else np.nan
        calibration_delta = (
            float(hybrid.get("calibration_error", np.nan) - prod.get("calibration_error", np.nan))
            if prod and hybrid
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
            "Combo hybrid minutes canary cleared win-rate, MAE, calibration, and sample-size gates."
            if qualifies
            else "Combo hybrid minutes canary has not yet cleared all promotion gates on new graded picks."
        ),
        "markets": sorted(MARKET_BLEND),
        "blend_map": MARKET_BLEND,
        "sample_size": sample_size,
        "win_rate_delta": win_delta,
        "mae_delta": mae_delta,
        "calibration_error_delta": calibration_delta,
        "gates": {
            "minimum_new_combo_market_graded_picks": MIN_PROMOTION_SAMPLE,
            "required_win_rate_delta": MIN_WIN_RATE_GAIN,
            "mae_must_be_no_worse": True,
            "calibration_must_be_no_worse": True,
        },
    }


def write_summary(market_report: pd.DataFrame, recommendation: dict, new_rows: int) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# WNBA Phase 12 Combo Hybrid Minutes Canary",
        "",
        f"Generated: {utc_now()}",
        "",
        f"New rows processed this run: {new_rows}",
        "",
        "Shadow-only canary using Phase 11 combo-market blend recommendations only.",
        "",
        "## Blend Map",
        "- PA: 25% shadow minutes",
        "- PR: 100% shadow minutes",
        "- PRA: 50% shadow minutes",
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
    if market_report.empty:
        lines.append("- No new combo canary rows have been accumulated yet.")
    else:
        for _, row in market_report[market_report["market"] == "all"].iterrows():
            wr = "n/a" if pd.isna(row["win_rate"]) else f"{row['win_rate']:.1%}"
            lines.append(
                f"- {row['scenario']}: n={int(row['sample_size'])}, win rate {wr}, "
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
            "- Default OFF unless WNBA_ENABLE_COMBO_HYBRID_MINUTES_CANARY=1 is set.",
            "- Production model files, grading files, public board, and publish outputs are not written.",
        ]
    )
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    logger = setup_logging("wnba_combo_hybrid_minutes_canary")
    if not enabled():
        logger.info("WNBA_ENABLE_COMBO_HYBRID_MINUTES_CANARY is off; no canary reports generated.")
        return

    ledger = normalize_ledger(read_csv(LEDGER_PATH))
    state = load_state()
    max_seen = state.get("max_created_at_utc")
    if not max_seen:
        high_water = ledger["created_at_utc"].max()
        save_state(
            {
                "initialized_at_utc": utc_now(),
                "max_created_at_utc": high_water.isoformat() if pd.notna(high_water) else utc_now(),
                "note": "Initialized without backfill; future runs process new PA/PR/PRA graded ledger rows only.",
            }
        )
        canary = append_canary_rows(pd.DataFrame())
        daily, rolling, market_report, buckets = build_reports(canary)
        rec = promotion_recommendation(market_report)
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        daily.to_csv(DAILY_REPORT_PATH, index=False)
        rolling.to_csv(ROLLING_REPORT_PATH, index=False)
        market_report.to_csv(MARKET_REPORT_PATH, index=False)
        buckets.to_csv(CONFIDENCE_BUCKET_PATH, index=False)
        PROMOTION_PATH.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        write_summary(market_report, rec, 0)
        logger.info("Initialized combo hybrid minutes canary checkpoint without backfill.")
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

    daily, rolling, market_report, buckets = build_reports(canary)
    rec = promotion_recommendation(market_report)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    daily.to_csv(DAILY_REPORT_PATH, index=False)
    rolling.to_csv(ROLLING_REPORT_PATH, index=False)
    market_report.to_csv(MARKET_REPORT_PATH, index=False)
    buckets.to_csv(CONFIDENCE_BUCKET_PATH, index=False)
    PROMOTION_PATH.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    write_summary(market_report, rec, len(scored))
    logger.info("Combo hybrid minutes canary processed %s new rows.", len(scored))


if __name__ == "__main__":
    main()
