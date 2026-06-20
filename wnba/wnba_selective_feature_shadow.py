from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from wnba_model_config import PROCESSED_DIR
from wnba_model_utils import setup_logging


ROOT = Path(__file__).resolve().parent
REPORTS_DIR = ROOT / "learning" / "reports"
PHASE8_SCORED_LINES_PATH = PROCESSED_DIR / "wnba_feature_upgrade_scored_lines.csv"
PHASE8_VALIDATION_PATH = PROCESSED_DIR / "wnba_feature_upgrade_validation_report.csv"

SCENARIO_COMPARISON_PATH = PROCESSED_DIR / "wnba_selective_feature_shadow_comparison.csv"
MARKET_PERFORMANCE_PATH = PROCESSED_DIR / "wnba_selective_feature_shadow_market_performance.csv"
CONFIDENCE_BUCKET_PATH = PROCESSED_DIR / "wnba_selective_feature_shadow_confidence_buckets.csv"
SCORED_ROWS_PATH = PROCESSED_DIR / "wnba_selective_feature_shadow_scored_rows.csv"
PROMOTION_PATH = PROCESSED_DIR / "wnba_selective_feature_shadow_promotion_recommendation.json"
SUMMARY_PATH = REPORTS_DIR / "wnba_selective_feature_shadow_report.md"

SELECTIVE_MARKETS = {"points", "rebounds"}
CONFIDENCE_BINS = [0.50, 0.55, 0.60, 0.65, 0.70, 1.01]
CONFIDENCE_LABELS = ["50-55", "55-60", "60-65", "65-70", "70+"]
MIN_PROMOTION_SAMPLE = 100
MIN_MARKET_SAMPLE = 25
MIN_WIN_RATE_GAIN = 0.005
MAX_MAE_LOSS = 0.01


def enabled() -> bool:
    return os.environ.get("WNBA_ENABLE_SELECTIVE_FEATURE_SHADOW", "").strip().lower() in {
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


def ensure_phase8_outputs(logger) -> None:
    if PHASE8_SCORED_LINES_PATH.exists() and PHASE8_VALIDATION_PATH.exists():
        return
    logger.info("Phase 8 scored outputs missing; running WNBA feature upgrade shadow first.")
    env = os.environ.copy()
    env["WNBA_ENABLE_FEATURE_UPGRADE_SHADOW"] = "1"
    subprocess.run([sys.executable, str(ROOT / "wnba_feature_upgrade_shadow.py")], check=True, env=env)


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


def win_rate(frame: pd.DataFrame, result_col: str) -> float:
    decisions = frame[frame[result_col].isin(["win", "loss"])]
    if decisions.empty:
        return np.nan
    return float((decisions[result_col] == "win").mean())


def normalize_probability(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if values.dropna().gt(1.0).any():
        values = values / 100.0
    return values.clip(0.50, 0.99)


def prepare_scenarios(scored: pd.DataFrame) -> pd.DataFrame:
    frame = scored.copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    required = [
        "market",
        "projection",
        "sportsbook_line",
        "actual_result",
        "result",
        "baseline_prediction",
        "upgraded_prediction",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Phase 8 scored lines missing columns: {missing}")

    for column in [
        "projection",
        "sportsbook_line",
        "actual_result",
        "baseline_prediction",
        "upgraded_prediction",
        "predicted_hit_rate",
        "baseline_estimated_confidence",
        "upgraded_estimated_confidence",
    ]:
        if column not in frame.columns:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["market"] = frame["market"].astype(str).str.lower().str.strip()
    frame["production_projection"] = frame["projection"]
    frame["full_feature_projection"] = frame["upgraded_prediction"]
    frame["selective_feature_projection"] = np.where(
        frame["market"].isin(SELECTIVE_MARKETS),
        frame["upgraded_prediction"],
        frame["baseline_prediction"],
    )

    frame["production_result"] = frame["result"].astype(str).str.lower().str.strip()
    frame["production_projected_side"] = frame.get("side", "").astype(str).str.lower().str.strip()
    for scenario in ["full_feature", "selective_feature"]:
        projection_col = f"{scenario}_projection"
        frame[f"{scenario}_projected_side"] = [
            projected_side(projection, line)
            for projection, line in zip(frame[projection_col], frame["sportsbook_line"])
        ]
        frame[f"{scenario}_result"] = [
            directional_result(side, line, actual)
            for side, line, actual in zip(
                frame[f"{scenario}_projected_side"],
                frame["sportsbook_line"],
                frame["actual_result"],
            )
        ]

    frame["production_confidence"] = normalize_probability(frame["predicted_hit_rate"]).fillna(0.50)
    frame["full_feature_confidence"] = normalize_probability(frame["upgraded_estimated_confidence"]).fillna(0.50)
    frame["selective_feature_confidence"] = np.where(
        frame["market"].isin(SELECTIVE_MARKETS),
        frame["upgraded_estimated_confidence"],
        frame["baseline_estimated_confidence"],
    )
    frame["selective_feature_confidence"] = normalize_probability(frame["selective_feature_confidence"]).fillna(0.50)

    for scenario in ["production", "full_feature", "selective_feature"]:
        error = frame[f"{scenario}_projection"] - frame["actual_result"]
        frame[f"{scenario}_absolute_error"] = error.abs()
        frame[f"{scenario}_squared_error"] = error**2
    return frame.dropna(subset=["sportsbook_line", "actual_result", "production_projection"]).copy()


def summarize(frame: pd.DataFrame, scenario: str, market: str = "all") -> dict:
    subset = frame if market == "all" else frame[frame["market"] == market]
    if subset.empty:
        return {
            "scenario": scenario,
            "market": market,
            "sample_size": 0,
            "mae": np.nan,
            "rmse": np.nan,
            "win_rate": np.nan,
            "avg_confidence": np.nan,
            "calibration_error": np.nan,
        }
    wr = win_rate(subset, f"{scenario}_result")
    avg_conf = float(subset[f"{scenario}_confidence"].mean())
    return {
        "scenario": scenario,
        "market": market,
        "sample_size": int(len(subset)),
        "mae": float(subset[f"{scenario}_absolute_error"].mean()),
        "rmse": float(math.sqrt(subset[f"{scenario}_squared_error"].mean())),
        "win_rate": wr,
        "avg_confidence": avg_conf,
        "calibration_error": abs(avg_conf - wr) if pd.notna(wr) else np.nan,
    }


def build_reports(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    scenarios = ["production", "full_feature", "selective_feature"]
    comparison = pd.DataFrame([summarize(frame, scenario) for scenario in scenarios])

    market_rows = []
    for scenario in scenarios:
        for market in ["points", "rebounds", *sorted(m for m in frame["market"].unique() if m not in SELECTIVE_MARKETS)]:
            market_rows.append(summarize(frame, scenario, market))
    market_report = pd.DataFrame(market_rows)

    bucket_rows = []
    for scenario in scenarios:
        bucket_col = f"{scenario}_confidence_bucket"
        frame[bucket_col] = pd.cut(
            frame[f"{scenario}_confidence"],
            bins=CONFIDENCE_BINS,
            labels=CONFIDENCE_LABELS,
            include_lowest=True,
            right=False,
        ).astype(str)
        for (market, bucket), group in frame.groupby(["market", bucket_col], dropna=False):
            bucket_rows.append(
                {
                    "scenario": scenario,
                    "market": market,
                    "confidence_bucket": bucket,
                    "sample_size": int(len(group)),
                    "win_rate": win_rate(group, f"{scenario}_result"),
                    "avg_confidence": float(group[f"{scenario}_confidence"].mean()),
                    "calibration_error": abs(float(group[f"{scenario}_confidence"].mean()) - win_rate(group, f"{scenario}_result"))
                    if pd.notna(win_rate(group, f"{scenario}_result"))
                    else np.nan,
                }
            )
    return comparison, market_report, pd.DataFrame(bucket_rows)


def build_recommendation(comparison: pd.DataFrame, market_report: pd.DataFrame) -> dict:
    prod = comparison.set_index("scenario").loc["production"]
    full = comparison.set_index("scenario").loc["full_feature"]
    selective = comparison.set_index("scenario").loc["selective_feature"]
    selected_markets = market_report[
        (market_report["scenario"] == "selective_feature")
        & (market_report["market"].isin(SELECTIVE_MARKETS))
        & (market_report["sample_size"] >= MIN_MARKET_SAMPLE)
    ].copy()
    prod_markets = market_report[
        (market_report["scenario"] == "production")
        & (market_report["market"].isin(SELECTIVE_MARKETS))
    ].set_index("market")

    market_guard = True
    market_notes = []
    for _, row in selected_markets.iterrows():
        market = row["market"]
        prod_row = prod_markets.loc[market]
        win_delta = float(row["win_rate"] - prod_row["win_rate"])
        mae_delta = float(row["mae"] - prod_row["mae"])
        market_notes.append({"market": market, "win_rate_delta_vs_production": win_delta, "mae_delta_vs_production": mae_delta})
        if win_delta < 0 or mae_delta > MAX_MAE_LOSS:
            market_guard = False

    beats_full = (
        pd.notna(selective["win_rate"])
        and pd.notna(full["win_rate"])
        and float(selective["win_rate"]) >= float(full["win_rate"])
        and float(selective["mae"]) <= float(full["mae"]) + MAX_MAE_LOSS
    )
    qualifies = (
        int(selective["sample_size"]) >= MIN_PROMOTION_SAMPLE
        and float(selective["win_rate"] - prod["win_rate"]) >= MIN_WIN_RATE_GAIN
        and float(selective["mae"] - prod["mae"]) <= MAX_MAE_LOSS
        and market_guard
        and beats_full
    )
    return {
        "created_at_utc": utc_now(),
        "decision": "recommend_future_shadow_canary" if qualifies else "do_not_promote",
        "selective_markets": sorted(SELECTIVE_MARKETS),
        "selective_beats_full_feature_upgrade": bool(beats_full),
        "reason": (
            "Selective points+rebounds cleared production and full-upgrade guardrails."
            if qualifies
            else "Selective points+rebounds did not clear every promotion gate against production and full upgrade."
        ),
        "overall_delta_vs_production": {
            "win_rate_delta": float(selective["win_rate"] - prod["win_rate"]),
            "mae_delta": float(selective["mae"] - prod["mae"]),
            "rmse_delta": float(selective["rmse"] - prod["rmse"]),
            "calibration_error_delta": float(selective["calibration_error"] - prod["calibration_error"]),
        },
        "overall_delta_vs_full_feature": {
            "win_rate_delta": float(selective["win_rate"] - full["win_rate"]),
            "mae_delta": float(selective["mae"] - full["mae"]),
            "rmse_delta": float(selective["rmse"] - full["rmse"]),
            "calibration_error_delta": float(selective["calibration_error"] - full["calibration_error"]),
        },
        "market_guards": market_notes,
        "gates": {
            "min_sample": MIN_PROMOTION_SAMPLE,
            "required_win_rate_delta_vs_production": MIN_WIN_RATE_GAIN,
            "max_mae_loss_vs_production": MAX_MAE_LOSS,
            "must_beat_or_tie_full_upgrade": True,
            "selected_market_min_sample": MIN_MARKET_SAMPLE,
        },
    }


def write_summary(comparison: pd.DataFrame, market_report: pd.DataFrame, recommendation: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# WNBA Phase 9 Selective Feature Upgrade Shadow",
        "",
        f"Generated: {utc_now()}",
        "",
        "Shadow-only comparison of production baseline, full feature upgrade, and selective points+rebounds upgrade.",
        "",
        "## Exact Markets Included",
        "- points",
        "- rebounds",
        "",
        "## Overall Results",
    ]
    for _, row in comparison.iterrows():
        lines.append(
            f"- {row['scenario']}: n={int(row['sample_size'])}, win rate {row['win_rate']:.1%}, "
            f"MAE {row['mae']:.3f}, RMSE {row['rmse']:.3f}, calibration error {row['calibration_error']:.3f}"
        )
    lines.extend(["", "## Points/Rebounds"])
    for scenario in ["production", "full_feature", "selective_feature"]:
        subset = market_report[
            (market_report["scenario"] == scenario)
            & (market_report["market"].isin(SELECTIVE_MARKETS))
        ]
        for _, row in subset.iterrows():
            lines.append(
                f"- {scenario} / {row['market']}: n={int(row['sample_size'])}, win rate {row['win_rate']:.1%}, "
                f"MAE {row['mae']:.3f}, RMSE {row['rmse']:.3f}, calibration error {row['calibration_error']:.3f}"
            )
    lines.extend(
        [
            "",
            "## Promotion Recommendation",
            f"- Decision: **{recommendation['decision']}**",
            f"- Selective beats full feature upgrade: {recommendation['selective_beats_full_feature_upgrade']}",
            f"- Reason: {recommendation['reason']}",
            "",
            "## Production Safety",
            "- Default behavior remains OFF unless WNBA_ENABLE_SELECTIVE_FEATURE_SHADOW=1 is set.",
            "- Reads Phase 8 shadow outputs and writes only Phase 9 shadow reports.",
            "- Does not write production model files, public boards, grading ledgers, or publish outputs.",
        ]
    )
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    logger = setup_logging("wnba_selective_feature_shadow")
    if not enabled():
        logger.info("WNBA_ENABLE_SELECTIVE_FEATURE_SHADOW is off; no shadow reports generated.")
        return

    ensure_phase8_outputs(logger)
    scored = read_csv(PHASE8_SCORED_LINES_PATH)
    if scored.empty:
        raise RuntimeError(f"No Phase 8 scored lines available at {PHASE8_SCORED_LINES_PATH}")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    frame = prepare_scenarios(scored)
    comparison, market_report, bucket_report = build_reports(frame)
    recommendation = build_recommendation(comparison, market_report)

    frame.to_csv(SCORED_ROWS_PATH, index=False)
    comparison.to_csv(SCENARIO_COMPARISON_PATH, index=False)
    market_report.to_csv(MARKET_PERFORMANCE_PATH, index=False)
    bucket_report.to_csv(CONFIDENCE_BUCKET_PATH, index=False)
    PROMOTION_PATH.write_text(json.dumps(recommendation, indent=2) + "\n", encoding="utf-8")
    write_summary(comparison, market_report, recommendation)
    logger.info("Wrote Phase 9 selective feature shadow report: %s", SUMMARY_PATH)


if __name__ == "__main__":
    main()
