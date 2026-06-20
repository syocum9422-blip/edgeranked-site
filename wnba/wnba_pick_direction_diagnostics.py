from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from wnba_model_config import BEST_BETS_DIR, PROCESSED_DIR
from wnba_model_utils import canonicalize_name, setup_logging


ROOT = Path(__file__).resolve().parent
LEARNING_DIR = ROOT / "learning"
REPORTS_DIR = LEARNING_DIR / "reports"
LEDGER_PATH = LEARNING_DIR / "graded_predictions_ledger.csv"
GRADED_BETS_PATH = BEST_BETS_DIR / "graded_bets.csv"
PICK_DIRECTION_REPORT_PATH = PROCESSED_DIR / "wnba_pick_direction_report.csv"
MARKET_SIDE_REPORT_PATH = PROCESSED_DIR / "wnba_market_side_report.csv"
EDGE_THRESHOLD_REPORT_PATH = PROCESSED_DIR / "wnba_edge_threshold_report.csv"
SUMMARY_PATH = REPORTS_DIR / "wnba_pick_direction_summary.md"

MEANINGFUL_MARKET_SAMPLE = 50
MEANINGFUL_SIDE_SAMPLE = 20
WEAK_SIDE_WIN_RATE = 0.48
SUPPRESS_WIN_RATE = 0.50
MIN_THRESHOLD_SAMPLE = 15


def enabled() -> bool:
    return os.environ.get("WNBA_ENABLE_PICK_DIRECTION_DIAGNOSTICS", "").strip().lower() in {"1", "true", "yes", "on"}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def normalize_ledger(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    ledger = frame.copy()
    ledger.columns = [str(column).strip().lower() for column in ledger.columns]
    for column in ["date", "player", "market", "side", "projection", "sportsbook_line", "actual_result", "result"]:
        if column not in ledger.columns:
            raise ValueError(f"graded_predictions_ledger.csv missing required column: {column}")
    ledger["date"] = pd.to_datetime(ledger["date"], errors="coerce").dt.date.astype(str)
    ledger["player"] = ledger["player"].astype(str).str.strip()
    ledger["player_key"] = ledger.get("player_key", ledger["player"].map(canonicalize_name)).astype(str)
    missing_key = ledger["player_key"].str.strip().isin(["", "nan", "None"])
    ledger.loc[missing_key, "player_key"] = ledger.loc[missing_key, "player"].map(canonicalize_name)
    ledger["market"] = ledger["market"].astype(str).str.lower().str.strip()
    ledger["side"] = ledger["side"].astype(str).str.lower().str.strip()
    ledger["result"] = ledger["result"].astype(str).str.lower().str.strip()
    for column in ["projection", "sportsbook_line", "actual_result", "predicted_hit_rate"]:
        if column not in ledger.columns:
            ledger[column] = np.nan
        ledger[column] = pd.to_numeric(ledger[column], errors="coerce")
    ledger["projection_edge"] = ledger["projection"] - ledger["sportsbook_line"]
    ledger["abs_projection_edge"] = ledger["projection_edge"].abs()
    ledger["line_delta_sign"] = np.where(ledger["projection_edge"] >= 0, "projection_over_line", "projection_under_line")
    ledger["actual_edge"] = ledger["actual_result"] - ledger["sportsbook_line"]
    ledger["actual_side"] = np.where(ledger["actual_edge"] > 0, "over", np.where(ledger["actual_edge"] < 0, "under", "push"))
    ledger["wrong_side"] = ledger["result"].eq("loss")
    ledger["closer_than_line"] = (ledger["projection"] - ledger["actual_result"]).abs() < (ledger["sportsbook_line"] - ledger["actual_result"]).abs()
    ledger["closer_but_wrong_side"] = ledger["closer_than_line"] & ledger["wrong_side"]
    ledger["edge_bucket"] = pd.cut(
        ledger["abs_projection_edge"],
        bins=[-0.001, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, np.inf],
        labels=["0-0.5", "0.5-1", "1-1.5", "1.5-2", "2-3", "3-5", "5+"],
    ).astype(str)
    return ledger[ledger["result"].isin(["win", "loss", "push"])].copy()


def line_movement_frame() -> pd.DataFrame:
    graded = read_csv(GRADED_BETS_PATH)
    if graded.empty:
        return pd.DataFrame()
    graded.columns = [str(column).strip().lower() for column in graded.columns]
    if graded.columns.duplicated().any():
        graded = graded.loc[:, ~graded.columns.duplicated()].copy()
    required = {"bet_date", "player_name", "stat", "side", "line"}
    if not required.issubset(set(graded.columns)):
        return pd.DataFrame()
    move = graded.copy()
    move["date"] = pd.to_datetime(move["bet_date"], errors="coerce").dt.date.astype(str)
    move["player_key"] = move["player_name"].map(canonicalize_name)
    move["market"] = move["stat"].astype(str).str.lower().str.strip()
    move["side"] = move["side"].astype(str).str.lower().str.strip()
    move["sportsbook_line"] = pd.to_numeric(move["line"], errors="coerce")
    for column in ["line_open", "line_move", "line_pulled"]:
        if column not in move.columns:
            move[column] = np.nan
    return move[["date", "player_key", "market", "side", "sportsbook_line", "line_open", "line_move", "line_pulled"]].drop_duplicates(
        ["date", "player_key", "market", "side", "sportsbook_line"], keep="last"
    )


def attach_line_movement(ledger: pd.DataFrame) -> pd.DataFrame:
    move = line_movement_frame()
    if move.empty:
        ledger["line_open"] = np.nan
        ledger["line_move"] = np.nan
        ledger["line_pulled"] = np.nan
        ledger["line_move_bucket"] = "missing"
        return ledger
    merged = ledger.merge(
        move,
        on=["date", "player_key", "market", "side", "sportsbook_line"],
        how="left",
    )
    merged["line_move"] = pd.to_numeric(merged["line_move"], errors="coerce")
    merged["line_move_bucket"] = pd.cut(
        merged["line_move"],
        bins=[-np.inf, -1.0, -0.25, 0.25, 1.0, np.inf],
        labels=["moved_down_1+", "moved_down", "flat", "moved_up", "moved_up_1+"],
    ).astype(str)
    merged.loc[merged["line_move"].isna(), "line_move_bucket"] = "missing"
    return merged


def rate(group: pd.DataFrame, column: str = "result") -> float:
    decisions = group[group[column].isin(["win", "loss"])]
    if decisions.empty:
        return np.nan
    return float((decisions[column] == "win").mean())


def summarize_group(group: pd.DataFrame) -> dict:
    wins = int((group["result"] == "win").sum())
    losses = int((group["result"] == "loss").sum())
    pushes = int((group["result"] == "push").sum())
    decisions = wins + losses
    return {
        "sample_size": int(len(group)),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": wins / decisions if decisions else np.nan,
        "avg_abs_projection_edge": float(group["abs_projection_edge"].mean()),
        "avg_projection_edge": float(group["projection_edge"].mean()),
        "closer_but_wrong_side_rate": float(group["closer_but_wrong_side"].mean()),
        "line_move_coverage": float(group["line_move"].notna().mean()) if "line_move" in group.columns else 0.0,
        "avg_line_move": float(group["line_move"].mean()) if "line_move" in group.columns else np.nan,
    }


def build_market_side_report(ledger: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (market, side), group in ledger.groupby(["market", "side"], dropna=False):
        row = {"market": market, "side": side}
        row.update(summarize_group(group))
        rows.append(row)
    report = pd.DataFrame(rows).sort_values(["market", "side"]).reset_index(drop=True)
    return report


def build_pick_direction_report(ledger: pd.DataFrame) -> pd.DataFrame:
    rows = []
    dimensions = [
        ("market", ["market"]),
        ("market_side", ["market", "side"]),
        ("market_edge_bucket", ["market", "edge_bucket"]),
        ("market_line_delta_sign", ["market", "line_delta_sign"]),
        ("market_line_move_bucket", ["market", "line_move_bucket"]),
    ]
    for dimension, columns in dimensions:
        for keys, group in ledger.groupby(columns, dropna=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            row = {"dimension": dimension}
            for column, value in zip(columns, keys):
                row[column] = value
            row.update(summarize_group(group))
            rows.append(row)
    return pd.DataFrame(rows).sort_values(["dimension", "market", "sample_size"], ascending=[True, True, False]).reset_index(drop=True)


def threshold_metrics(group: pd.DataFrame, threshold: float) -> dict:
    subset = group[group["abs_projection_edge"] >= threshold]
    sample = len(subset)
    return {
        "threshold": threshold,
        "sample_size": sample,
        "win_rate": rate(subset),
        "avg_abs_projection_edge": float(subset["abs_projection_edge"].mean()) if sample else np.nan,
    }


def side_recommendation(side_report: pd.DataFrame, market: str) -> tuple[str, str]:
    sides = side_report[side_report["market"] == market].copy()
    if sides.empty:
        return "allow_both", ""
    meaningful = sides[sides["sample_size"] >= MEANINGFUL_SIDE_SAMPLE]
    weak = meaningful[meaningful["win_rate"] < WEAK_SIDE_WIN_RATE]
    if len(meaningful) >= 2 and len(weak) == 1:
        weak_side = str(weak.iloc[0]["side"])
        allowed = "under_only" if weak_side == "over" else "over_only"
        return allowed, f"{weak_side}_side_below_{WEAK_SIDE_WIN_RATE:.2f}"
    if len(meaningful) and (meaningful["win_rate"] < WEAK_SIDE_WIN_RATE).all():
        return "suppress_market", "both_sides_weak"
    return "allow_both", ""


def build_edge_threshold_report(ledger: pd.DataFrame, side_report: pd.DataFrame) -> pd.DataFrame:
    thresholds = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0]
    rows = []
    for market, group in ledger.groupby("market", dropna=False):
        market_sample = len(group)
        market_win_rate = rate(group)
        recommended_threshold = np.nan
        best_rate = -1.0
        best_threshold = 0.0
        for threshold in thresholds:
            metrics = threshold_metrics(group, threshold)
            metrics.update({"market": market, "market_sample_size": market_sample, "market_win_rate": market_win_rate})
            rows.append(metrics)
            if metrics["sample_size"] >= MIN_THRESHOLD_SAMPLE and pd.notna(metrics["win_rate"]):
                if metrics["win_rate"] > best_rate:
                    best_rate = metrics["win_rate"]
                    best_threshold = threshold
        recommended_threshold = best_threshold
        allowed_side, side_reason = side_recommendation(side_report, market)
        suppress = bool(market_sample >= MEANINGFUL_MARKET_SAMPLE and market_win_rate < SUPPRESS_WIN_RATE)
        confidence_penalty = ""
        if market_sample >= MEANINGFUL_MARKET_SAMPLE and market_win_rate < 0.52:
            confidence_penalty = "cap_confidence_at_60"
        if allowed_side != "allow_both":
            confidence_penalty = (confidence_penalty + "; " if confidence_penalty else "") + "penalize_disallowed_side"
        for row in rows:
            if row["market"] == market:
                row["recommended_min_edge"] = recommended_threshold
                row["allowed_side"] = allowed_side
                row["side_reason"] = side_reason
                row["suppress_market"] = suppress
                row["confidence_penalty_rule"] = confidence_penalty
                combo = market in {"pra", "pa", "pr", "ra"}
                row["combo_market"] = combo
                row["combo_needs_higher_threshold"] = bool(combo and recommended_threshold >= 1.5)
    return pd.DataFrame(rows).sort_values(["market", "threshold"]).reset_index(drop=True)


def table(frame: pd.DataFrame, columns: list[str], n: int = 12) -> str:
    if frame.empty:
        return "No rows available."
    return frame[columns].head(n).to_string(index=False)


def write_summary(direction: pd.DataFrame, side: pd.DataFrame, thresholds: pd.DataFrame) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    recommendations = thresholds[thresholds["threshold"] == 0.0].copy()
    weak_sides = side[(side["sample_size"] >= MEANINGFUL_SIDE_SAMPLE) & (side["win_rate"] < WEAK_SIDE_WIN_RATE)].copy()
    closer_wrong = direction[direction["dimension"] == "market"].sort_values("closer_but_wrong_side_rate", ascending=False)
    lines = [
        "# WNBA Pick Direction Diagnostics",
        "",
        "## Side Recommendations",
        table(recommendations, ["market", "market_sample_size", "market_win_rate", "recommended_min_edge", "allowed_side", "suppress_market", "confidence_penalty_rule"], 20),
        "",
        "## Weak Market Sides",
        table(weak_sides.sort_values("win_rate"), ["market", "side", "sample_size", "win_rate", "avg_abs_projection_edge", "closer_but_wrong_side_rate"], 20),
        "",
        "## Closer But Wrong Side",
        table(closer_wrong, ["market", "sample_size", "win_rate", "closer_but_wrong_side_rate", "avg_abs_projection_edge"], 20),
        "",
        "## Edge Bucket Diagnostics",
        table(direction[direction["dimension"] == "market_edge_bucket"], ["market", "edge_bucket", "sample_size", "win_rate", "avg_abs_projection_edge"], 30),
        "",
        "## Line Movement Coverage",
        table(direction[direction["dimension"] == "market_line_move_bucket"], ["market", "line_move_bucket", "sample_size", "win_rate", "line_move_coverage", "avg_line_move"], 30),
    ]
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    logger = setup_logging("wnba_pick_direction_diagnostics")
    if not enabled():
        logger.info("WNBA pick-direction diagnostics skipped; set WNBA_ENABLE_PICK_DIRECTION_DIAGNOSTICS=1 to run.")
        return 0
    ledger = normalize_ledger(read_csv(LEDGER_PATH))
    if ledger.empty:
        raise FileNotFoundError(f"No ledger rows found at {LEDGER_PATH}")
    ledger = attach_line_movement(ledger)
    side_report = build_market_side_report(ledger)
    direction_report = build_pick_direction_report(ledger)
    threshold_report = build_edge_threshold_report(ledger, side_report)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    side_report.to_csv(MARKET_SIDE_REPORT_PATH, index=False)
    direction_report.to_csv(PICK_DIRECTION_REPORT_PATH, index=False)
    threshold_report.to_csv(EDGE_THRESHOLD_REPORT_PATH, index=False)
    write_summary(direction_report, side_report, threshold_report)
    logger.info(
        "WNBA pick-direction diagnostics complete | rows=%s | markets=%s",
        len(ledger),
        ledger["market"].nunique(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
