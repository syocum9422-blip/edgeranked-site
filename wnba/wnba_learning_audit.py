from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from wnba_model_config import BETTING_RECORD_PATH, CANONICAL_PLAYER_GAMES_PATH, CANONICAL_PLAYER_STATUS_PATH, GRADED_BETS_PATH, PROCESSED_DIR
from wnba_model_utils import canonicalize_name, setup_logging, standardize_team_abbrev


ROOT = Path(__file__).resolve().parent
LEARNING_DIR = ROOT / "learning"
ERRORS_DIR = LEARNING_DIR / "errors"
REPORTS_DIR = LEARNING_DIR / "reports"
PERSISTENT_LEDGER_PATH = LEARNING_DIR / "graded_predictions_ledger.csv"
MARKET_VALIDATION_PATH = PROCESSED_DIR / "wnba_market_validation_report.csv"
CONFIDENCE_BUCKET_PATH = PROCESSED_DIR / "wnba_confidence_bucket_report.csv"
CHALLENGER_REPORT_PATH = PROCESSED_DIR / "wnba_challenger_comparison_report.csv"
CHALLENGER_ROWS_PATH = PROCESSED_DIR / "wnba_challenger_scored_rows.csv"
PROMOTION_RECOMMENDATION_PATH = PROCESSED_DIR / "wnba_challenger_promotion_recommendation.json"
NIGHTLY_REPORT_PATH = REPORTS_DIR / "wnba_nightly_learning_report.md"
AUDIT_REPORT_PATH = REPORTS_DIR / "wnba_model_audit_report.md"
PROJECTION_ERRORS_PATH = ERRORS_DIR / "projection_errors.csv"
MINUTES_ERRORS_PATH = ERRORS_DIR / "minutes_errors.csv"

MODEL_VERSION = "production_p7_shadow_learning_v1"
EPS = 1e-6

SUPPORTED_MARKETS = [
    "points",
    "rebounds",
    "assists",
    "threes_made",
    "steals",
    "blocks",
    "pra",
    "pr",
    "pa",
    "ra",
    "sb",
]

LEDGER_COLUMNS = [
    "prediction_id",
    "date",
    "player",
    "player_key",
    "team",
    "opponent",
    "market",
    "side",
    "projection",
    "sportsbook_line",
    "sportsbook",
    "actual_result",
    "result",
    "difference_from_line",
    "projection_error",
    "absolute_error",
    "squared_error",
    "minutes_projected",
    "minutes_played",
    "usage",
    "pace",
    "home_away",
    "rest_days",
    "injury_flags",
    "confidence_score",
    "predicted_hit_rate",
    "model_version",
    "created_at_utc",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def lower_unique_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    if frame.columns.duplicated().any():
        frame = frame.loc[:, ~frame.columns.duplicated()].copy()
    return frame


def first_series(frame: pd.DataFrame, names: list[str], default: object = np.nan) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return frame[name]
    return pd.Series([default] * len(frame), index=frame.index)


def normalize_market(value: object) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "pts": "points",
        "reb": "rebounds",
        "ast": "assists",
        "fg3m": "threes_made",
        "3pm": "threes_made",
        "stl": "steals",
        "blk": "blocks",
    }
    return aliases.get(text, text)


def normalize_bets(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    bets = lower_unique_columns(frame)
    normalized = pd.DataFrame(index=bets.index)
    normalized["date"] = pd.to_datetime(first_series(bets, ["bet_date", "date"]), errors="coerce").dt.date.astype(str)
    normalized["player"] = first_series(bets, ["player_name", "player"]).astype(str).str.strip()
    normalized["player_key"] = normalized["player"].map(canonicalize_name)
    normalized["team"] = first_series(bets, ["team"]).map(standardize_team_abbrev)
    normalized["opponent"] = first_series(bets, ["opponent"]).map(standardize_team_abbrev)
    normalized["market"] = first_series(bets, ["stat", "raw_stat"]).map(normalize_market)
    normalized["side"] = first_series(bets, ["side"]).astype(str).str.lower().str.strip()
    normalized["sportsbook_line"] = pd.to_numeric(first_series(bets, ["line"]), errors="coerce")
    normalized["sportsbook"] = first_series(bets, ["sportsbook"], "unknown").astype(str)
    normalized["predicted_hit_rate"] = pd.to_numeric(first_series(bets, ["hit_rate"]), errors="coerce")
    normalized["confidence_score"] = pd.to_numeric(first_series(bets, ["confidence_score"]), errors="coerce")
    normalized["confidence_label"] = first_series(bets, ["confidence_label", "confidence"], "unknown").astype(str).str.lower()
    normalized["projection"] = pd.to_numeric(first_series(bets, ["projection_mean", "projection"]), errors="coerce")
    normalized["minutes_projected"] = pd.to_numeric(first_series(bets, ["projected_minutes"]), errors="coerce")
    normalized["actual_result"] = pd.to_numeric(first_series(bets, ["actual_value", "actual"]), errors="coerce")
    normalized["result"] = first_series(bets, ["bet_result", "result"]).astype(str).str.lower().str.strip()
    normalized["result"] = normalized["result"].replace({"nan": ""})
    normalized = normalized[normalized["result"].isin(["win", "loss", "push"])].copy()
    normalized["difference_from_line"] = normalized["actual_result"] - normalized["sportsbook_line"]
    normalized["projection_error"] = normalized["projection"] - normalized["actual_result"]
    normalized["absolute_error"] = normalized["projection_error"].abs()
    normalized["squared_error"] = normalized["projection_error"] ** 2
    normalized["prediction_id"] = (
        normalized["date"].astype(str)
        + "|"
        + normalized["player_key"].astype(str)
        + "|"
        + normalized["market"].astype(str)
        + "|"
        + normalized["side"].astype(str)
        + "|"
        + normalized["sportsbook_line"].round(4).astype(str)
    )
    return normalized.drop_duplicates("prediction_id", keep="last")


def load_actual_context() -> pd.DataFrame:
    actuals = read_csv(CANONICAL_PLAYER_GAMES_PATH)
    if actuals.empty:
        return pd.DataFrame()
    actuals = lower_unique_columns(actuals)
    actuals["date"] = pd.to_datetime(actuals.get("game_date"), errors="coerce").dt.date.astype(str)
    actuals["player"] = actuals.get("player_name", "").astype(str)
    actuals["player_key"] = actuals["player"].map(canonicalize_name)
    actuals["team"] = actuals.get("team", "").map(standardize_team_abbrev)
    actuals["home_away"] = actuals.get("home_away", "").astype(str).str.upper().str[:1]
    keep = ["date", "player_key", "team", "minutes", "usage_proxy", "pace_last_10", "home_away", "rest_days"]
    for column in keep:
        if column not in actuals.columns:
            actuals[column] = np.nan
    return actuals[keep].rename(
        columns={
            "minutes": "minutes_played",
            "usage_proxy": "usage",
            "pace_last_10": "pace",
        }
    )


def load_injury_context() -> pd.DataFrame:
    status = read_csv(CANONICAL_PLAYER_STATUS_PATH)
    if status.empty:
        return pd.DataFrame(columns=["player_key", "injury_flags"])
    status = lower_unique_columns(status)
    name = first_series(status, ["player_name", "player"]).astype(str)
    status["player_key"] = first_series(status, ["player_key"], "").astype(str)
    missing = status["player_key"].str.strip() == ""
    status.loc[missing, "player_key"] = name[missing].map(canonicalize_name)
    status["injury_flags"] = first_series(status, ["status", "injury_status"], "").astype(str)
    return status[["player_key", "injury_flags"]].drop_duplicates("player_key", keep="last")


def build_ledger_rows(graded: pd.DataFrame) -> pd.DataFrame:
    bets = normalize_bets(graded)
    if bets.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    context = load_actual_context()
    if not context.empty:
        bets = bets.merge(context, on=["date", "player_key", "team"], how="left")
    for column in ["minutes_played", "usage", "pace", "home_away", "rest_days"]:
        if column not in bets.columns:
            bets[column] = np.nan
    injuries = load_injury_context()
    if not injuries.empty:
        bets = bets.merge(injuries, on="player_key", how="left")
    if "injury_flags" not in bets.columns:
        bets["injury_flags"] = ""
    bets["model_version"] = MODEL_VERSION
    bets["created_at_utc"] = utc_now()
    return bets.reindex(columns=LEDGER_COLUMNS)


def append_ledger(rows: pd.DataFrame) -> int:
    if rows.empty:
        return 0
    PERSISTENT_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing_ids: set[str] = set()
    if PERSISTENT_LEDGER_PATH.exists():
        try:
            existing = pd.read_csv(PERSISTENT_LEDGER_PATH, usecols=["prediction_id"])
            existing_ids = set(existing["prediction_id"].dropna().astype(str))
        except Exception:
            existing_ids = set()
    new_rows = rows[~rows["prediction_id"].astype(str).isin(existing_ids)].copy()
    if new_rows.empty:
        return 0
    new_rows.to_csv(PERSISTENT_LEDGER_PATH, mode="a", header=not PERSISTENT_LEDGER_PATH.exists(), index=False)
    return len(new_rows)


def accuracy(group: pd.DataFrame) -> float:
    decisions = group[group["result"].isin(["win", "loss"])]
    if decisions.empty:
        return np.nan
    return float((decisions["result"] == "win").mean())


def brier_score(group: pd.DataFrame, prob_col: str = "predicted_hit_rate") -> float:
    decisions = group[group["result"].isin(["win", "loss"])].copy()
    if decisions.empty:
        return np.nan
    y = (decisions["result"] == "win").astype(float)
    p = pd.to_numeric(decisions[prob_col], errors="coerce").clip(EPS, 1 - EPS)
    valid = p.notna()
    if not valid.any():
        return np.nan
    return float(((p[valid] - y[valid]) ** 2).mean())


def calibration_gap(group: pd.DataFrame, prob_col: str = "predicted_hit_rate") -> float:
    actual = accuracy(group)
    predicted = pd.to_numeric(group[prob_col], errors="coerce").mean()
    if pd.isna(actual) or pd.isna(predicted):
        return np.nan
    return float(actual - predicted)


def rolling_accuracy(frame: pd.DataFrame, market: str, days: int) -> float:
    work = frame[frame["market"] == market].copy()
    if work.empty:
        return np.nan
    work["_date"] = pd.to_datetime(work["date"], errors="coerce")
    end = work["_date"].max()
    if pd.isna(end):
        return np.nan
    start = end - pd.Timedelta(days=days - 1)
    return accuracy(work[work["_date"] >= start])


def build_market_validation(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "market",
        "sample_size",
        "wins",
        "losses",
        "pushes",
        "win_pct",
        "loss_pct",
        "push_pct",
        "mae",
        "rmse",
        "calibration",
        "brier_score",
        "rolling_7_day_accuracy",
        "rolling_30_day_accuracy",
        "signed_projection_bias",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for market, group in frame.groupby("market", dropna=False):
        sample = len(group)
        wins = int((group["result"] == "win").sum())
        losses = int((group["result"] == "loss").sum())
        pushes = int((group["result"] == "push").sum())
        decisions = wins + losses
        rows.append(
            {
                "market": str(market),
                "sample_size": sample,
                "wins": wins,
                "losses": losses,
                "pushes": pushes,
                "win_pct": wins / decisions if decisions else np.nan,
                "loss_pct": losses / decisions if decisions else np.nan,
                "push_pct": pushes / sample if sample else np.nan,
                "mae": pd.to_numeric(group["absolute_error"], errors="coerce").mean(),
                "rmse": math.sqrt(pd.to_numeric(group["squared_error"], errors="coerce").mean()),
                "calibration": calibration_gap(group),
                "brier_score": brier_score(group),
                "rolling_7_day_accuracy": rolling_accuracy(frame, str(market), 7),
                "rolling_30_day_accuracy": rolling_accuracy(frame, str(market), 30),
                "signed_projection_bias": pd.to_numeric(group["projection_error"], errors="coerce").mean(),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(["win_pct", "sample_size"], ascending=[False, False])


def confidence_bucket(value: object) -> str:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return "missing"
    if number < 0.55:
        return "50-55%"
    if number < 0.60:
        return "55-60%"
    if number < 0.65:
        return "60-65%"
    if number < 0.70:
        return "65-70%"
    return "70%+"


def build_confidence_report(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["confidence_bucket", "sample_size", "wins", "losses", "pushes", "realized_accuracy", "avg_predicted_hit_rate", "calibration_gap"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    work = frame.copy()
    work["confidence_bucket"] = work["predicted_hit_rate"].map(confidence_bucket)
    rows = []
    order = ["50-55%", "55-60%", "60-65%", "65-70%", "70%+", "missing"]
    for bucket in order:
        group = work[work["confidence_bucket"] == bucket]
        if group.empty:
            continue
        wins = int((group["result"] == "win").sum())
        losses = int((group["result"] == "loss").sum())
        pushes = int((group["result"] == "push").sum())
        rows.append(
            {
                "confidence_bucket": bucket,
                "sample_size": int(len(group)),
                "wins": wins,
                "losses": losses,
                "pushes": pushes,
                "realized_accuracy": accuracy(group),
                "avg_predicted_hit_rate": pd.to_numeric(group["predicted_hit_rate"], errors="coerce").mean(),
                "calibration_gap": calibration_gap(group),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def challenger_scored_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    work = frame.copy()
    work["_date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.sort_values(["_date", "prediction_id"]).reset_index(drop=True)
    global_errors: list[float] = []
    market_errors: dict[str, list[float]] = {}
    challenger_projection = []
    challenger_hit_rate = []
    for _, row in work.iterrows():
        market = str(row["market"])
        prior = market_errors.get(market, [])
        if len(prior) >= 20:
            bias = float(np.mean(prior[-100:]))
            support = len(prior)
        elif len(global_errors) >= 50:
            bias = float(np.mean(global_errors[-200:]))
            support = len(global_errors)
        else:
            bias = 0.0
            support = 0
        projection = pd.to_numeric(row["projection"], errors="coerce")
        line = pd.to_numeric(row["sportsbook_line"], errors="coerce")
        base_prob = pd.to_numeric(row["predicted_hit_rate"], errors="coerce")
        adjusted_projection = projection - bias if pd.notna(projection) else np.nan
        delta = adjusted_projection - line if pd.notna(adjusted_projection) and pd.notna(line) else np.nan
        if pd.isna(base_prob) or pd.isna(delta):
            adjusted_prob = base_prob
        else:
            edge_prob = 0.5 + min(abs(float(delta)) / 12.0, 0.24)
            adjusted_prob = 0.65 * float(base_prob) + 0.35 * edge_prob
            if support < 20:
                adjusted_prob = min(adjusted_prob, 0.66)
            adjusted_prob = float(np.clip(adjusted_prob, 0.505, 0.82))
        challenger_projection.append(adjusted_projection)
        challenger_hit_rate.append(adjusted_prob)
        error = pd.to_numeric(row["projection_error"], errors="coerce")
        if pd.notna(error):
            market_errors.setdefault(market, []).append(float(error))
            global_errors.append(float(error))
    work["challenger_projection"] = challenger_projection
    work["challenger_hit_rate"] = challenger_hit_rate
    work["challenger_projection_error"] = work["challenger_projection"] - pd.to_numeric(work["actual_result"], errors="coerce")
    work["challenger_absolute_error"] = work["challenger_projection_error"].abs()
    work["challenger_squared_error"] = work["challenger_projection_error"] ** 2
    return work.drop(columns=["_date"])


def component_metrics(frame: pd.DataFrame, prob_col: str, abs_col: str, sq_col: str) -> dict:
    return {
        "sample_size": int(len(frame)),
        "win_rate": accuracy(frame),
        "mae": pd.to_numeric(frame[abs_col], errors="coerce").mean(),
        "rmse": math.sqrt(pd.to_numeric(frame[sq_col], errors="coerce").mean()),
        "calibration": calibration_gap(frame, prob_col),
        "brier_score": brier_score(frame, prob_col),
    }


def build_challenger_report(scored: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    columns = ["segment", "market", "sample_size", "production_win_rate", "challenger_win_rate", "production_mae", "challenger_mae", "production_rmse", "challenger_rmse", "production_calibration", "challenger_calibration", "production_brier", "challenger_brier"]
    if scored.empty:
        return pd.DataFrame(columns=columns), {"promote": False, "reason": "no_scored_rows"}
    rows = []
    groups = [("all", "all", scored)]
    groups.extend(("market", market, group) for market, group in scored.groupby("market", dropna=False))
    for segment, market, group in groups:
        prod = component_metrics(group, "predicted_hit_rate", "absolute_error", "squared_error")
        chal = component_metrics(group, "challenger_hit_rate", "challenger_absolute_error", "challenger_squared_error")
        rows.append(
            {
                "segment": segment,
                "market": str(market),
                "sample_size": int(len(group)),
                "production_win_rate": prod["win_rate"],
                "challenger_win_rate": chal["win_rate"],
                "production_mae": prod["mae"],
                "challenger_mae": chal["mae"],
                "production_rmse": prod["rmse"],
                "challenger_rmse": chal["rmse"],
                "production_calibration": prod["calibration"],
                "challenger_calibration": chal["calibration"],
                "production_brier": prod["brier_score"],
                "challenger_brier": chal["brier_score"],
            }
        )
    report = pd.DataFrame(rows, columns=columns)
    overall = report[report["segment"] == "all"].iloc[0]
    min_sample = int(overall["sample_size"]) >= 250
    mae_gain = float(overall["production_mae"] - overall["challenger_mae"]) if pd.notna(overall["production_mae"]) and pd.notna(overall["challenger_mae"]) else np.nan
    brier_gain = float(overall["production_brier"] - overall["challenger_brier"]) if pd.notna(overall["production_brier"]) and pd.notna(overall["challenger_brier"]) else np.nan
    meaningful = bool(min_sample and pd.notna(mae_gain) and mae_gain > 0.05 and pd.notna(brier_gain) and brier_gain > 0.005)
    recommendation = {
        "generated_at_utc": utc_now(),
        "promote": False,
        "recommendation": "do_not_promote",
        "reason": "requires_manual_review_and_statistically_meaningful_improvement" if not meaningful else "shadow_improved_mae_and_brier_but_promotion_is_advisory_only",
        "criteria": {
            "minimum_sample_size": 250,
            "minimum_mae_gain": 0.05,
            "minimum_brier_gain": 0.005,
            "production_outputs_changed": False,
            "feature_flag_required_for_any_future_activation": True,
        },
        "observed": {
            "sample_size": int(overall["sample_size"]),
            "mae_gain": None if pd.isna(mae_gain) else round(mae_gain, 6),
            "brier_gain": None if pd.isna(brier_gain) else round(brier_gain, 6),
        },
    }
    return report, recommendation


def format_pct(value: object) -> str:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return "n/a"
    return f"{number:.1%}"


def top_table(frame: pd.DataFrame, columns: list[str], n: int = 8) -> str:
    if frame.empty:
        return "No rows available."
    return frame[columns].head(n).to_string(index=False)


def generate_reports(ledger: pd.DataFrame, market_report: pd.DataFrame, confidence_report: pd.DataFrame, challenger_report: pd.DataFrame, recommendation: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    graded = ledger[ledger["result"].isin(["win", "loss", "push"])].copy()
    biggest_misses = graded.sort_values("absolute_error", ascending=False)
    biggest_hits = graded.sort_values("absolute_error", ascending=True)
    team_rows = []
    for team, group in graded.groupby("team", dropna=False):
        team_rows.append({"team": team, "sample_size": len(group), "accuracy": accuracy(group), "mae": group["absolute_error"].mean()})
    team_report = pd.DataFrame(team_rows).sort_values(["accuracy", "sample_size"], ascending=[False, False]) if team_rows else pd.DataFrame()
    player_rows = []
    for player, group in graded.groupby("player", dropna=False):
        if len(group) >= 5:
            player_rows.append({"player": player, "sample_size": len(group), "accuracy": accuracy(group), "mae": group["absolute_error"].mean()})
    player_report = pd.DataFrame(player_rows).sort_values("mae", ascending=False) if player_rows else pd.DataFrame()

    strongest = market_report.sort_values(["win_pct", "sample_size"], ascending=[False, False]).head(5)
    weakest = market_report.sort_values(["win_pct", "sample_size"], ascending=[True, False]).head(5)
    lines = [
        "# WNBA Nightly Learning Report",
        "",
        f"Generated: {utc_now()}",
        f"Graded predictions in ledger: {len(graded)}",
        "",
        "## Best-Performing Markets",
        top_table(strongest, ["market", "sample_size", "win_pct", "mae", "calibration"]),
        "",
        "## Worst-Performing Markets",
        top_table(weakest, ["market", "sample_size", "win_pct", "mae", "calibration"]),
        "",
        "## Biggest Misses",
        top_table(biggest_misses, ["date", "player", "market", "side", "projection", "sportsbook_line", "actual_result", "absolute_error"], 10),
        "",
        "## Biggest Hits",
        top_table(biggest_hits, ["date", "player", "market", "side", "projection", "sportsbook_line", "actual_result", "absolute_error"], 10),
        "",
        "## Team Accuracy",
        top_table(team_report, ["team", "sample_size", "accuracy", "mae"], 12),
        "",
        "## Player Outliers",
        top_table(player_report, ["player", "sample_size", "accuracy", "mae"], 12),
        "",
        "## Confidence Calibration",
        top_table(confidence_report, ["confidence_bucket", "sample_size", "realized_accuracy", "avg_predicted_hit_rate", "calibration_gap"], 10),
        "",
        "## Challenger Summary",
        top_table(challenger_report, ["segment", "market", "sample_size", "production_mae", "challenger_mae", "production_brier", "challenger_brier"], 12),
        "",
        f"Promotion recommendation: {recommendation.get('recommendation', 'do_not_promote')} ({recommendation.get('reason', '')})",
        "",
        "## Recommendations",
        "- Recalibrate high-confidence buckets before trusting 70%+ probabilities.",
        "- Prioritize markets with negative calibration gaps and high sample sizes.",
        "- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.",
        "- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.",
    ]
    NIGHTLY_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    audit_lines = [
        "# WNBA Model Audit Report",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Feature Impact",
        "The trained stat model report shows points and rebounds have the highest predictive signal by R2, while steals and blocks have weak R2 and are dominated by event variance. The active feature set is heavily driven by rolling player rates, rolling minutes, season averages, team/opponent last-10 context, position allowance, rest, and home/away.",
        "",
        "## Outdated Assumptions",
        "- Confidence still overstates certainty in several high-probability buckets.",
        "- Player status is treated through current status snapshots, but historical injury flags are not persistently stored with every graded bet unless this audit ledger is enabled.",
        "- Combo markets inherit base-stat simulation assumptions and need market-specific validation, not just aggregate grading.",
        "- Current production Phase 7 realism gates default ON; future experimental changes should use separate OFF-by-default flags.",
        "",
        "## Systematic Bias",
        "Use `signed_projection_bias` in `data/processed/wnba_market_validation_report.csv`: positive means overestimation, negative means underestimation. The challenger uses only prior observed market bias to avoid lookahead.",
        "",
        "## Worst Markets",
        top_table(weakest, ["market", "sample_size", "win_pct", "mae", "signed_projection_bias", "calibration"], 8),
        "",
        "## Stale or Heuristic Components",
        "- Player positions and player statuses remain CSV/manual-source dependent.",
        "- Confidence scoring is a heuristic blend of agreement, volatility, and minutes stability.",
        "- Best-bet caps and thresholds are fixed constants.",
        "- Promotion is advisory; no automatic production activation is wired.",
        "",
        "## Highest-Leverage Improvements",
        "- Market-level calibration and gating by market/side/confidence bucket.",
        "- Minutes-error-aware confidence caps.",
        "- Persistent graded ledger with context for long-term drift detection.",
        "- Shadow challenger backtests with explicit promotion criteria.",
    ]
    AUDIT_REPORT_PATH.write_text("\n".join(audit_lines) + "\n", encoding="utf-8")


def main() -> int:
    logger = setup_logging("wnba_learning_audit")
    LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    graded = read_csv(GRADED_BETS_PATH)
    if graded.empty:
        graded = read_csv(BETTING_RECORD_PATH)
    ledger_rows = build_ledger_rows(graded)
    appended = append_ledger(ledger_rows)
    ledger = read_csv(PERSISTENT_LEDGER_PATH)
    if ledger.empty:
        ledger = ledger_rows

    market_report = build_market_validation(ledger)
    confidence_report = build_confidence_report(ledger)
    scored = challenger_scored_rows(ledger)
    challenger_report, recommendation = build_challenger_report(scored)

    market_report.to_csv(MARKET_VALIDATION_PATH, index=False)
    confidence_report.to_csv(CONFIDENCE_BUCKET_PATH, index=False)
    challenger_report.to_csv(CHALLENGER_REPORT_PATH, index=False)
    scored.to_csv(CHALLENGER_ROWS_PATH, index=False)
    PROMOTION_RECOMMENDATION_PATH.write_text(json.dumps(recommendation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    generate_reports(ledger, market_report, confidence_report, challenger_report, recommendation)

    logger.info(
        "WNBA learning audit complete | appended=%s | ledger_rows=%s | markets=%s",
        appended,
        len(ledger),
        len(market_report),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
