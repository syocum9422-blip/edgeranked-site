#!/usr/bin/env python3
"""Shadow WNBA calibration and weakness diagnostics.

This script reads graded production outputs, builds diagnostics, and tests a
conservative confidence-only calibration layer without changing public outputs.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
PROCESSED = ROOT / "data" / "processed"
GRADED_PATH = ROOT / "Best_Bets" / "graded_bets.csv"
PROJECTION_ERRORS_PATH = ROOT / "learning" / "errors" / "projection_errors.csv"
MINUTES_ERRORS_PATH = ROOT / "learning" / "errors" / "minutes_errors.csv"

BASELINE_REPORT = PROCESSED / "wnba_phase2c_baseline_report.csv"
WEAKNESS_REPORT = PROCESSED / "wnba_phase2c_weakness_breakdown.csv"
SHADOW_REPORT = PROCESSED / "wnba_phase2c_shadow_tuning_report.csv"
BEFORE_AFTER_REPORT = PROCESSED / "wnba_phase2c_before_after_metrics.csv"
SHADOW_ROWS_REPORT = PROCESSED / "wnba_phase2c_shadow_scored_rows.csv"
SHADOW_FACTORS = PROCESSED / "wnba_phase2c_shadow_calibration_factors.json"
PROMOTION_DECISION = PROCESSED / "wnba_phase2c_promotion_decision.json"

WINDOWS = (7, 14, 30)
MIN_COVERAGE_RATIO = 0.92
PLAY_THRESHOLD = 0.56
EPS = 1e-6


def _lower_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    original_cols = [str(c).strip() for c in df.columns]
    df.columns = [c.lower() for c in original_cols]
    if df.columns.duplicated().any():
        # Graded exports carry both private snake_case and public all-caps
        # columns. Prefer the first occurrence, which is the private schema.
        df = df.loc[:, ~df.columns.duplicated()].copy()
    return df


def _first_col(df: pd.DataFrame, names: Iterable[str]) -> str | None:
    for name in names:
        if name in df.columns:
            return name
    return None


def _to_num(series: pd.Series, default: float = np.nan) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def _bucket_confidence(p: float) -> str:
    if pd.isna(p):
        return "missing"
    if p < 0.55:
        return "<55"
    if p < 0.60:
        return "55-60"
    if p < 0.65:
        return "60-65"
    if p < 0.70:
        return "65-70"
    if p < 0.80:
        return "70-80"
    if p < 0.90:
        return "80-90"
    return "90+"


def _bucket_minutes(minutes: float) -> str:
    if pd.isna(minutes):
        return "missing"
    if minutes < 10:
        return "<10"
    if minutes < 18:
        return "10-18"
    if minutes < 24:
        return "18-24"
    if minutes < 30:
        return "24-30"
    if minutes < 35:
        return "30-35"
    return "35+"


def _bucket_line(stat: str, line: float) -> str:
    if pd.isna(line):
        return "missing"
    stat = (stat or "").lower()
    if stat in {"points", "pts"}:
        cuts = [8, 12, 16, 20, 25]
    elif stat in {"rebounds", "reb"}:
        cuts = [3, 5, 7, 9, 12]
    elif stat in {"assists", "ast"}:
        cuts = [2, 4, 6, 8, 10]
    elif stat in {"pra", "points_rebounds_assists"}:
        cuts = [12, 18, 24, 30, 36]
    elif stat in {"pr", "points_rebounds", "pa", "points_assists", "ra", "rebounds_assists"}:
        cuts = [8, 12, 16, 22, 28]
    else:
        cuts = [0.5, 1.5, 2.5, 4.5, 6.5]
    last = "-inf"
    for cut in cuts:
        if line < cut:
            return f"{last}-{cut:g}"
        last = f"{cut:g}"
    return f"{last}+"


def _log_loss(y: pd.Series, p: pd.Series) -> float:
    valid = y.notna() & p.notna()
    if not valid.any():
        return np.nan
    yy = y[valid].astype(float)
    pp = p[valid].clip(EPS, 1 - EPS).astype(float)
    return float(-(yy * np.log(pp) + (1 - yy) * np.log(1 - pp)).mean())


def _brier(y: pd.Series, p: pd.Series) -> float:
    valid = y.notna() & p.notna()
    if not valid.any():
        return np.nan
    return float(((p[valid].astype(float) - y[valid].astype(float)) ** 2).mean())


def _metrics(df: pd.DataFrame, prob_col: str) -> dict[str, float]:
    resolved = df[df["result_binary"].notna()].copy()
    non_push = df[df["bet_result"].isin(["win", "loss"])].copy()
    wins = int((non_push["bet_result"] == "win").sum())
    losses = int((non_push["bet_result"] == "loss").sum())
    accuracy = wins / (wins + losses) if wins + losses else np.nan
    return {
        "rows": int(len(df)),
        "graded_predictions": int(len(resolved)),
        "wins": wins,
        "losses": losses,
        "pushes": int((df["bet_result"] == "push").sum()),
        "accuracy": accuracy,
        "brier": _brier(resolved["result_binary"], resolved[prob_col]) if len(resolved) else np.nan,
        "log_loss": _log_loss(resolved["result_binary"], resolved[prob_col]) if len(resolved) else np.nan,
        "plays_retained_at_56": int((df[prob_col] >= PLAY_THRESHOLD).sum()),
    }


def _window_frame(df: pd.DataFrame, days: int) -> pd.DataFrame:
    end_date = df["bet_date"].max()
    start_date = end_date - pd.Timedelta(days=days - 1)
    return df[df["bet_date"] >= start_date].copy()


def _safe_rate(wins: int, total: int, prior_rate: float, prior_n: int) -> tuple[float, int]:
    if total <= 0:
        return prior_rate, 0
    rate = (wins + prior_rate * prior_n) / (total + prior_n)
    return float(rate), int(total)


def _build_group_rates(train: pd.DataFrame) -> dict:
    train = train[train["result_binary"].notna()].copy()
    global_rate = float(train["result_binary"].mean()) if len(train) else 0.55
    factors = {
        "global_rate": global_rate,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_rows": int(len(train)),
        "stat_side": {},
        "confidence_bucket": {},
        "minutes_bucket": {},
        "player_stat": {},
    }
    if not len(train):
        return factors

    def add_rates(group_cols: list[str], key_name: str, min_n: int, prior_n: int) -> None:
        grouped = train.groupby(group_cols, dropna=False)["result_binary"].agg(["sum", "count"]).reset_index()
        for _, row in grouped.iterrows():
            wins = int(row["sum"])
            count = int(row["count"])
            if count < min_n:
                continue
            rate, support = _safe_rate(wins, count, global_rate, prior_n)
            key = "::".join(str(row[c]) for c in group_cols)
            factors[key_name][key] = {"rate": rate, "support": support}

    add_rates(["stat", "side"], "stat_side", min_n=20, prior_n=40)
    add_rates(["baseline_confidence_bucket"], "confidence_bucket", min_n=20, prior_n=50)
    add_rates(["minutes_bucket"], "minutes_bucket", min_n=20, prior_n=40)
    add_rates(["player_name", "stat"], "player_stat", min_n=12, prior_n=60)
    return factors


def _lookup_rate(factors: dict, section: str, key: str) -> tuple[float | None, int]:
    item = factors.get(section, {}).get(key)
    if not item:
        return None, 0
    return float(item["rate"]), int(item.get("support", 0))


def _shadow_probability(row: pd.Series, factors: dict) -> float:
    base = float(row["hit_rate"])
    global_rate = float(factors.get("global_rate", 0.55))
    p = 0.78 * base + 0.22 * global_rate

    adjustments: list[tuple[float, float]] = []
    stat_key = f"{row.get('stat')}::{row.get('side')}"
    rate, support = _lookup_rate(factors, "stat_side", stat_key)
    if rate is not None:
        adjustments.append((rate - global_rate, min(0.16, support / 500)))

    rate, support = _lookup_rate(factors, "confidence_bucket", str(row.get("baseline_confidence_bucket")))
    if rate is not None:
        adjustments.append((rate - global_rate, min(0.11, support / 800)))

    rate, support = _lookup_rate(factors, "minutes_bucket", str(row.get("minutes_bucket")))
    if rate is not None:
        adjustments.append((rate - global_rate, min(0.09, support / 700)))

    player_key = f"{row.get('player_name')}::{row.get('stat')}"
    rate, support = _lookup_rate(factors, "player_stat", player_key)
    if rate is not None:
        adjustments.append((rate - global_rate, min(0.06, support / 1000)))

    for delta, weight in adjustments:
        p += delta * weight

    minutes = row.get("projected_minutes")
    minutes_abs_error = row.get("minutes_abs_error")
    abs_edge = abs(row.get("line_delta", 0.0))
    sample_support = row.get("player_stat_support", 0)

    if pd.notna(minutes):
        if minutes < 15:
            p -= 0.055
        elif minutes < 22:
            p -= 0.025
    if pd.notna(minutes_abs_error):
        if minutes_abs_error >= 8:
            p -= 0.045
        elif minutes_abs_error >= 5:
            p -= 0.025
    if pd.notna(abs_edge) and abs_edge < 1.5:
        p -= 0.025
    if sample_support < 12 and base > 0.72:
        p = min(p, 0.68)
    if sample_support < 8:
        p = min(p, 0.64)

    # Do not allow this shadow layer to manufacture extreme confidence.
    if base < 0.70:
        p = min(p, 0.70)
    if row.get("confidence_label_norm") in {"low", "missing"}:
        p = min(p, 0.62)
    return float(np.clip(p, 0.505, 0.82))


def _prepare() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    graded = _lower_cols(pd.read_csv(GRADED_PATH))
    if graded.empty:
        raise SystemExit("graded_bets.csv has no rows; fail closed")

    date_col = _first_col(graded, ["bet_date", "date"])
    if not date_col:
        raise SystemExit("graded bets missing date column; fail closed")
    graded["bet_date"] = pd.to_datetime(graded[date_col], errors="coerce").dt.normalize()

    for required in ["player_name", "team", "opponent", "stat", "side", "line", "hit_rate", "bet_result"]:
        if required not in graded.columns:
            raise SystemExit(f"graded bets missing required column {required}; fail closed")

    for col in ["line", "hit_rate", "line_delta", "projection_mean", "projected_minutes"]:
        if col in graded.columns:
            graded[col] = _to_num(graded[col])
        else:
            graded[col] = np.nan

    graded["player_name"] = graded["player_name"].astype(str).str.strip()
    graded["team"] = graded["team"].astype(str).str.upper().str.strip()
    graded["opponent"] = graded["opponent"].astype(str).str.upper().str.strip()
    graded["stat"] = graded["stat"].astype(str).str.lower().str.strip()
    graded["side"] = graded["side"].astype(str).str.lower().str.strip()
    graded["bet_result"] = graded["bet_result"].astype(str).str.lower().str.strip()
    graded["result_binary"] = np.where(graded["bet_result"] == "win", 1.0, np.where(graded["bet_result"] == "loss", 0.0, np.nan))
    graded["hit_rate"] = graded["hit_rate"].clip(EPS, 1 - EPS)
    graded["baseline_confidence_bucket"] = graded["hit_rate"].apply(_bucket_confidence)
    graded["minutes_bucket"] = graded["projected_minutes"].apply(_bucket_minutes)
    graded["line_bucket"] = graded.apply(lambda r: _bucket_line(r["stat"], r["line"]), axis=1)
    graded["starter_proxy"] = np.where(graded["projected_minutes"] >= 25, "starter_proxy", "bench_proxy")
    graded["confidence_label_norm"] = graded.get("confidence_label", graded.get("confidence", "missing")).astype(str).str.lower().str.strip()

    projection_errors = _lower_cols(pd.read_csv(PROJECTION_ERRORS_PATH)) if PROJECTION_ERRORS_PATH.exists() else pd.DataFrame()
    if len(projection_errors):
        projection_errors["game_date"] = pd.to_datetime(projection_errors["game_date"], errors="coerce").dt.normalize()
        projection_errors["stat"] = projection_errors["stat"].astype(str).str.lower().str.strip()
        projection_errors["absolute_error"] = _to_num(projection_errors["absolute_error"])

    minutes_errors = _lower_cols(pd.read_csv(MINUTES_ERRORS_PATH)) if MINUTES_ERRORS_PATH.exists() else pd.DataFrame()
    if len(minutes_errors):
        minutes_errors["game_date"] = pd.to_datetime(minutes_errors["game_date"], errors="coerce").dt.normalize()
        minutes_errors["absolute_error"] = _to_num(minutes_errors["absolute_error"])
        minutes_summary = minutes_errors.groupby(["game_date", "player_name"], dropna=False)["absolute_error"].mean().reset_index()
        minutes_summary = minutes_summary.rename(columns={"game_date": "bet_date", "absolute_error": "minutes_abs_error"})
        graded = graded.merge(minutes_summary, on=["bet_date", "player_name"], how="left")
    else:
        graded["minutes_abs_error"] = np.nan

    player_support = (
        graded[graded["result_binary"].notna()]
        .groupby(["player_name", "stat"], dropna=False)["result_binary"]
        .size()
        .rename("player_stat_support")
        .reset_index()
    )
    graded = graded.merge(player_support, on=["player_name", "stat"], how="left")
    graded["player_stat_support"] = graded["player_stat_support"].fillna(0).astype(int)
    graded = graded[graded["bet_date"].notna()].copy()
    return graded, projection_errors, minutes_errors


def _baseline_report(graded: pd.DataFrame, projection_errors: pd.DataFrame, minutes_errors: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for days in WINDOWS:
        frame = _window_frame(graded, days)
        metrics = _metrics(frame, "hit_rate")
        metrics["window_days"] = days

        if len(projection_errors):
            cutoff = graded["bet_date"].max() - pd.Timedelta(days=days - 1)
            pe = projection_errors[projection_errors["game_date"] >= cutoff]
            metrics["projection_mae"] = float(pe["absolute_error"].mean()) if len(pe) else np.nan
            metrics["projection_rmse"] = float(math.sqrt(pe["squared_error"].mean())) if "squared_error" in pe and len(pe) else np.nan
        else:
            metrics["projection_mae"] = np.nan
            metrics["projection_rmse"] = np.nan

        if len(minutes_errors):
            cutoff = graded["bet_date"].max() - pd.Timedelta(days=days - 1)
            me = minutes_errors[minutes_errors["game_date"] >= cutoff]
            metrics["minutes_mae"] = float(me["absolute_error"].mean()) if len(me) else np.nan
            metrics["minutes_rmse"] = float(math.sqrt(me["squared_error"].mean())) if "squared_error" in me and len(me) else np.nan
        else:
            metrics["minutes_mae"] = np.nan
            metrics["minutes_rmse"] = np.nan
        rows.append(metrics)
    return pd.DataFrame(rows)


def _weakness_breakdown(graded: pd.DataFrame, projection_errors: pd.DataFrame, minutes_errors: pd.DataFrame) -> pd.DataFrame:
    rows = []

    def add_breakdown(dimension: str, source: pd.DataFrame, group_col: str, include_projection: bool = False) -> None:
        for value, group in source.groupby(group_col, dropna=False):
            metric = _metrics(group, "hit_rate")
            metric.update({"dimension": dimension, "segment": str(value)})
            if include_projection:
                metric["projection_mae"] = float(group["absolute_error"].mean()) if "absolute_error" in group else np.nan
                metric["projection_rmse"] = float(math.sqrt(group["squared_error"].mean())) if "squared_error" in group and len(group) else np.nan
            rows.append(metric)

    for dimension, group_col in [
        ("market_stat", "stat"),
        ("player", "player_name"),
        ("team", "team"),
        ("line_range", "line_bucket"),
        ("confidence_bucket", "baseline_confidence_bucket"),
        ("minutes_bucket", "minutes_bucket"),
        ("starter_vs_bench_proxy", "starter_proxy"),
    ]:
        add_breakdown(dimension, graded, group_col)

    if len(projection_errors):
        pe = projection_errors.copy()
        pe["bet_result"] = np.nan
        pe["result_binary"] = np.nan
        pe["hit_rate"] = np.nan
        add_breakdown("projection_error_by_stat", pe, "stat", include_projection=True)

    if len(minutes_errors):
        rows.append(
            {
                "dimension": "minutes_projection",
                "segment": "all",
                "rows": int(len(minutes_errors)),
                "graded_predictions": np.nan,
                "wins": np.nan,
                "losses": np.nan,
                "pushes": np.nan,
                "accuracy": np.nan,
                "brier": np.nan,
                "log_loss": np.nan,
                "plays_retained_at_56": np.nan,
                "projection_mae": float(minutes_errors["absolute_error"].mean()),
                "projection_rmse": float(math.sqrt(minutes_errors["squared_error"].mean())) if "squared_error" in minutes_errors else np.nan,
            }
        )

    out = pd.DataFrame(rows)
    sort_cols = [c for c in ["dimension", "graded_predictions", "rows"] if c in out.columns]
    return out.sort_values(sort_cols, ascending=[True, False, False]).reset_index(drop=True)


def _shadow_backtest(graded: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    all_shadow = []
    report_rows = []
    factors_for_latest = _build_group_rates(graded[graded["result_binary"].notna()].copy())
    max_date = graded["bet_date"].max()
    for days in WINDOWS:
        test_start = max_date - pd.Timedelta(days=days - 1)
        test = graded[graded["bet_date"] >= test_start].copy()
        scored_parts = []
        min_train_rows = 120
        train_rows_used = []
        fallback_rows = 0
        for bet_date, day_frame in test.groupby("bet_date", sort=True):
            train = graded[graded["bet_date"] < bet_date].copy()
            train_count = int(train["result_binary"].notna().sum())
            day_scored = day_frame.copy()
            if train_count < min_train_rows:
                day_scored["shadow_hit_rate"] = day_scored["hit_rate"]
                fallback_rows += len(day_scored)
            else:
                factors = _build_group_rates(train)
                day_scored["shadow_hit_rate"] = day_scored.apply(lambda row: _shadow_probability(row, factors), axis=1)
            train_rows_used.append(train_count)
            scored_parts.append(day_scored)
        test = pd.concat(scored_parts, ignore_index=True) if scored_parts else test.assign(shadow_hit_rate=pd.Series(dtype=float))
        baseline = _metrics(test, "hit_rate")
        shadow = _metrics(test, "shadow_hit_rate")
        coverage_ratio = shadow["plays_retained_at_56"] / baseline["plays_retained_at_56"] if baseline["plays_retained_at_56"] else np.nan
        report_rows.append(
            {
                "window_days": days,
                "min_prior_train_rows": int(min(train_rows_used) if train_rows_used else 0),
                "max_prior_train_rows": int(max(train_rows_used) if train_rows_used else 0),
                "fallback_rows_due_to_thin_prior": int(fallback_rows),
                "test_rows": int(len(test)),
                "baseline_accuracy": baseline["accuracy"],
                "shadow_accuracy": shadow["accuracy"],
                "baseline_brier": baseline["brier"],
                "shadow_brier": shadow["brier"],
                "baseline_log_loss": baseline["log_loss"],
                "shadow_log_loss": shadow["log_loss"],
                "baseline_plays_retained_at_56": baseline["plays_retained_at_56"],
                "shadow_plays_retained_at_56": shadow["plays_retained_at_56"],
                "coverage_ratio_at_56": coverage_ratio,
                "brier_delta": shadow["brier"] - baseline["brier"],
                "log_loss_delta": shadow["log_loss"] - baseline["log_loss"],
            }
        )
        all_shadow.append(test)
    return pd.DataFrame(report_rows), pd.concat(all_shadow, ignore_index=True), factors_for_latest


def _promotion_decision(shadow_report: pd.DataFrame) -> dict:
    rows = shadow_report.set_index("window_days")
    decision = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "promoted": False,
        "reason": "",
        "criteria": {
            "must_improve_brier_14_and_30": True,
            "must_improve_log_loss_14_and_30": True,
            "minimum_coverage_ratio_at_56": MIN_COVERAGE_RATIO,
            "public_schema_changes": False,
            "shadow_only": True,
        },
    }
    needed = [14, 30]
    if any(day not in rows.index for day in needed):
        decision["reason"] = "missing_required_validation_windows"
        return decision
    ok = True
    reasons = []
    for day in needed:
        row = rows.loc[day]
        if not (row["shadow_brier"] < row["baseline_brier"]):
            ok = False
            reasons.append(f"{day}d_brier_not_improved")
        if not (row["shadow_log_loss"] < row["baseline_log_loss"]):
            ok = False
            reasons.append(f"{day}d_log_loss_not_improved")
        if not (row["coverage_ratio_at_56"] >= MIN_COVERAGE_RATIO):
            ok = False
            reasons.append(f"{day}d_coverage_below_{MIN_COVERAGE_RATIO}")
    decision["promoted"] = bool(ok)
    decision["reason"] = "shadow_layer_met_validation_criteria" if ok else ",".join(reasons)
    return decision


def main() -> int:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    graded, projection_errors, minutes_errors = _prepare()

    baseline = _baseline_report(graded, projection_errors, minutes_errors)
    weakness = _weakness_breakdown(graded, projection_errors, minutes_errors)
    shadow_report, shadow_rows, factors = _shadow_backtest(graded)

    before_after = baseline.merge(
        shadow_report,
        on="window_days",
        how="left",
        suffixes=("_baseline_report", "_shadow_report"),
    )
    decision = _promotion_decision(shadow_report)

    baseline.to_csv(BASELINE_REPORT, index=False)
    weakness.to_csv(WEAKNESS_REPORT, index=False)
    shadow_report.to_csv(SHADOW_REPORT, index=False)
    before_after.to_csv(BEFORE_AFTER_REPORT, index=False)
    shadow_rows.to_csv(SHADOW_ROWS_REPORT, index=False)
    SHADOW_FACTORS.write_text(json.dumps(factors, indent=2, sort_keys=True) + "\n")
    PROMOTION_DECISION.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n")

    print("WNBA Phase 2C shadow calibration complete")
    print(f"baseline_report={BASELINE_REPORT}")
    print(f"weakness_report={WEAKNESS_REPORT}")
    print(f"shadow_report={SHADOW_REPORT}")
    print(f"before_after_report={BEFORE_AFTER_REPORT}")
    print(f"promotion_decision={PROMOTION_DECISION}")
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
