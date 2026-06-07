#!/usr/bin/env python3
"""Write the daily WNBA monitoring summary used by cron checks."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
PROCESSED = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
OUTPUT_PATH = PROCESSED / "wnba_monitoring_summary.json"


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_read_error": str(exc)}


def file_stamp(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path),
        "size": stat.st_size,
        "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def latest_backtest_metrics() -> dict:
    path = PROCESSED / "wnba_backtest_report.csv"
    if not path.exists():
        return {"path": str(path), "available": False}
    try:
        report = pd.read_csv(path)
    except Exception as exc:
        return {"path": str(path), "available": False, "error": str(exc)}
    if report.empty:
        return {"path": str(path), "available": False, "error": "empty"}
    row = report.sort_values("window_days").iloc[-1].to_dict()
    return {
        "path": str(path),
        "available": True,
        "window_days": int(row.get("window_days", 0)),
        "graded_predictions": int(row.get("graded_predictions", 0)),
        "accuracy": float(row.get("accuracy")) if pd.notna(row.get("accuracy")) else None,
        "brier": float(row.get("brier")) if pd.notna(row.get("brier")) else None,
        "log_loss": float(row.get("log_loss")) if pd.notna(row.get("log_loss")) else None,
    }


def main() -> int:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    slate = read_json(PROCESSED / "wnba_slate_validation_manifest.json")
    actuals = read_json(RAW / "wnba_espn_actuals_manifest.json")
    learning = read_json(PROCESSED / "wnba_learning_manifest.json")
    production = read_json(PROCESSED / "wnba_production_status.json")
    promotion = read_json(PROCESSED / "wnba_phase2c_live_promotion_manifest.json")
    backtest = latest_backtest_metrics()

    output_file = ROOT / "wnba_best_bets_today.csv"
    warnings: list[str] = []
    if slate.get("status") != "PASS":
        warnings.append("slate_validation_not_pass")
    if not output_file.exists() or output_file.stat().st_size <= 0:
        warnings.append("missing_or_empty_published_source_output")
    if str(actuals.get("source", "")).startswith("fallback"):
        warnings.append("actuals_fallback_only")
    if int(learning.get("predictions_graded") or 0) <= 0:
        warnings.append("zero_predictions_graded")
    if backtest.get("brier") is None or backtest.get("log_loss") is None:
        warnings.append("missing_backtest_calibration_metrics")
    if production.get("WNBA_PRODUCTION_STATUS") != "PASS":
        warnings.append("production_status_not_pass")
    if production.get("stale_output_blocked") != "yes":
        warnings.append("stale_output_guard_not_confirmed")

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "slate_status": {
            "status": slate.get("status"),
            "slate_date": slate.get("slate_date"),
            "expected_game_count": slate.get("expected_game_count"),
            "generated_game_count": slate.get("generated_game_count"),
            "missing_games": slate.get("missing_games", []),
            "duplicate_games": slate.get("duplicate_games", []),
        },
        "source_freshness": {
            "best_bets": file_stamp(output_file),
            "projections": file_stamp(ROOT / "projections.csv"),
            "app_view": file_stamp(ROOT / "Projections_app_view.csv"),
            "production_status": production.get("WNBA_PRODUCTION_STATUS"),
            "promotion_scope": promotion.get("promotion_scope"),
            "public_schema_changes": promotion.get("public_schema_changes"),
        },
        "actuals": {
            "source": actuals.get("source"),
            "latest_actual_date": actuals.get("latest_actual_date"),
            "completed_events_ingested": actuals.get("completed_events_ingested"),
            "player_rows_total": actuals.get("player_rows_total"),
            "team_rows_total": actuals.get("team_rows_total"),
        },
        "learning": {
            "last_graded_date": learning.get("last_graded_date"),
            "games_graded": learning.get("games_graded"),
            "predictions_graded": learning.get("predictions_graded"),
            "projection_error_rows": learning.get("projection_error_rows"),
            "minutes_error_rows": learning.get("minutes_error_rows"),
            "accuracy": learning.get("accuracy"),
            "brier": backtest.get("brier"),
            "log_loss": backtest.get("log_loss"),
            "backtest_window_days": backtest.get("window_days"),
        },
        "published": {
            "source_output_modified_at_utc": file_stamp(output_file).get("modified_at_utc"),
            "published_flag": production.get("published"),
            "stale_output_blocked": production.get("stale_output_blocked"),
        },
        "warning_flags": warnings,
        "healthy": not warnings,
    }
    OUTPUT_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not warnings else 2


if __name__ == "__main__":
    raise SystemExit(main())
