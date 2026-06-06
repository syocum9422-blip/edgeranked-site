from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from wnba_model_config import (
    BEST_BETS_DIR,
    BEST_BETS_ARCHIVE_DIR_DATED,
    BEST_BETS_ARCHIVE_PATH,
    BEST_BETS_PATH,
    BETTING_RECORD_PATH,
    CANONICAL_SPORTSBOOK_LINES_PATH,
    MATCH_AUDIT_PATH,
    PROJECTIONS_PATH,
    SIMULATION_DETAIL_PATH,
    STAT_ALIASES,
    UNMATCHED_PLAYERS_PATH,
    UNMATCHED_STATS_PATH,
)
from wnba_model_utils import (
    american_odds_to_implied_probability,
    archive_dataframe,
    canonicalize_name,
    confidence_to_score,
    setup_logging,
    today_timestamp,
)


MIN_EDGE = 0.04
MIN_HIT_RATE = 0.56
MAX_BETS_TOTAL = 25
MAX_BETS_PER_PLAYER = 2
MAX_BETS_PER_STAT = 6
CALIBRATION_FACTORS_PATH = BEST_BETS_DIR / "calibration_factors.json"
CALIBRATION_MAX_AGE_DAYS = 45
BEST_BET_COLUMNS = [
    "DATE",
    "PLAYER",
    "TEAM",
    "MATCHUP",
    "STAT",
    "RAW_STAT",
    "BET",
    "LINE",
    "PROJECTION",
    "EDGE",
    "ABS_EDGE",
    "STDDEV",
    "HIT_RATE",
    "MODEL_CONFIDENCE",
    "BET_CONFIDENCE",
    "CONFIDENCE_LABEL",
    "RESULT",
    "ACTUAL",
    "bet_date",
    "player_name",
    "team",
    "opponent",
    "stat",
    "line",
    "side",
    "sportsbook",
    "odds",
    "hit_rate",
    "edge",
    "projection_mean",
    "projection_median",
    "floor",
    "ceiling",
    "projected_minutes",
    "confidence",
    "confidence_score",
    "line_delta",
    "actual_value",
    "bet_result",
    "bet_quality_score",
    "empty_state_reason",
    "candidate_count",
    "qualified_count",
]


APP_STAT_NAMES = {stat: alias.upper() for stat, alias in STAT_ALIASES.items()}
APP_STAT_NAMES["threes_made"] = "FG3M"


def app_stat_name(stat: object) -> str:
    return APP_STAT_NAMES.get(str(stat), str(stat).upper())


def matchup_label(team: object, opponent: object) -> str:
    team_value = str(team).strip().upper()
    opponent_value = str(opponent).strip().upper()
    if team_value and opponent_value:
        return f"{team_value} vs {opponent_value}"
    return team_value or opponent_value


def side_label(side: str, stat: object) -> str:
    return f"{str(side).upper()} {app_stat_name(stat)}"


def estimated_std(row: pd.Series) -> float:
    stddev = pd.to_numeric(row.get("stddev"), errors="coerce")
    if pd.notna(stddev) and stddev > 0:
        return float(stddev)
    floor = pd.to_numeric(row.get("floor"), errors="coerce")
    ceiling = pd.to_numeric(row.get("ceiling"), errors="coerce")
    if pd.notna(floor) and pd.notna(ceiling) and ceiling >= floor:
        return float((ceiling - floor) / 2.563)
    return np.nan


def implied_probability_or_even(odds: object) -> float:
    implied = american_odds_to_implied_probability(pd.to_numeric(odds, errors="coerce"))
    if pd.isna(implied):
        return 0.5
    return float(implied)


def resolved_bet_date() -> str:
    projections = load_optional_csv(PROJECTIONS_PATH)
    for candidate in ["game_date", "GAME_DATE", "DATE", "bet_date"]:
        if candidate not in projections.columns:
            continue
        dates = pd.to_datetime(projections[candidate], errors="coerce").dropna()
        if not dates.empty:
            return dates.min().date().isoformat()
    return today_timestamp().date().isoformat()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def bucket_hit_rate(value: object) -> str | None:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return None
    if number < 0.55:
        return "50-55%"
    if number < 0.60:
        return "55-60%"
    if number < 0.65:
        return "60-65%"
    if number < 0.70:
        return "65-70%"
    if number < 0.75:
        return "70-75%"
    if number < 0.80:
        return "75-80%"
    return "80-100%+"


def calibration_factor_rate(factor: object) -> tuple[float | None, int]:
    if not isinstance(factor, dict):
        return None, 0
    rate = pd.to_numeric(factor.get("win_rate"), errors="coerce")
    bets = int(pd.to_numeric(factor.get("bets"), errors="coerce") or 0)
    if pd.isna(rate) or bets <= 0:
        return None, 0
    return float(rate), bets


def calibration_file_is_stale(metadata: dict, path) -> bool:
    created_at = metadata.get("created_at_utc")
    if created_at:
        try:
            created_dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            age_days = (utc_now() - created_dt.astimezone(timezone.utc)).days
            return age_days > CALIBRATION_MAX_AGE_DAYS
        except Exception:
            return True
    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except Exception:
        return True
    return (utc_now() - modified_at).days > CALIBRATION_MAX_AGE_DAYS


def load_calibration_factors(logger) -> tuple[dict | None, str]:
    path = CALIBRATION_FACTORS_PATH
    if not path.exists():
        return None, f"skipped: missing calibration file at {path}"

    try:
        factors = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"skipped: could not parse calibration JSON ({exc})"

    if not isinstance(factors, dict) or not factors:
        return None, "skipped: calibration payload is empty or invalid"

    metadata = factors.get("metadata")
    if not isinstance(metadata, dict):
        return None, "skipped: calibration metadata is missing"

    graded_bets = int(pd.to_numeric(metadata.get("graded_bets"), errors="coerce") or 0)
    if graded_bets <= 0:
        return None, "skipped: calibration metadata reports zero graded bets"

    if calibration_file_is_stale(metadata, path):
        return None, f"skipped: calibration file is stale (> {CALIBRATION_MAX_AGE_DAYS} days old)"

    has_supported_sections = any(
        isinstance(factors.get(section), dict) and factors.get(section)
        for section in ["stat_side_confidence_bucket", "stat_side", "side", "global"]
    )
    if not has_supported_sections:
        return None, "skipped: calibration file is incomplete for WNBA best-bet usage"

    logger.info(
        "Loaded WNBA calibration factors from %s | graded_bets=%s",
        path,
        graded_bets,
    )
    return factors, "applied"


def apply_calibrated_hit_rate(raw_hit_rate: object, stat: object, side: str, confidence_label: object, factors: dict | None) -> tuple[float, bool, list[str]]:
    hit_rate = float(pd.to_numeric(raw_hit_rate, errors="coerce"))
    if factors is None:
        return hit_rate, False, []

    side_key = str(side).upper()
    stat_key = str(stat).upper()
    confidence_key = str(confidence_label).title()
    bucket_key = bucket_hit_rate(hit_rate)
    calibrated = hit_rate
    applied_steps: list[str] = []

    factor_specs = [
        (
            factors.get("stat_side_confidence_bucket", {}).get(
                f"{stat_key}::{side_key}::{confidence_key}::{bucket_key}"
            )
            if bucket_key
            else None,
            5,
            0.18,
            0.05,
            0.005,
            "stat+side+confidence+bucket",
        ),
        (
            factors.get("stat_side", {}).get(f"{stat_key}::{side_key}"),
            5,
            0.14,
            0.04,
            0.004,
            "stat+side",
        ),
        (
            factors.get("side", {}).get(side_key),
            8,
            0.10,
            0.03,
            0.003,
            "side",
        ),
        (
            factors.get("global", {}).get("ALL"),
            10,
            0.08,
            0.02,
            0.002,
            "global",
        ),
    ]

    for factor, min_bets, max_weight, base_weight, per_bet, label in factor_specs:
        rate, bets = calibration_factor_rate(factor)
        if rate is None or bets < min_bets:
            continue
        weight = min(max_weight, base_weight + (per_bet * bets))
        calibrated = ((1.0 - weight) * calibrated) + (weight * rate)
        applied_steps.append(f"{label}:{bets}")

    calibrated = max(0.01, min(calibrated, 0.99))
    return calibrated, bool(applied_steps), applied_steps


def rank_bets(simulation_detail: pd.DataFrame, logger) -> pd.DataFrame:
    if simulation_detail.empty:
        return pd.DataFrame(columns=BEST_BET_COLUMNS)

    calibration_factors, calibration_status = load_calibration_factors(logger)
    if calibration_factors is None:
        logger.info("WNBA calibration %s; raw simulation hit rates will be used.", calibration_status)
    applied_count = 0
    skipped_count = 0
    applied_examples: list[str] = []
    rows = []
    for _, row in simulation_detail.iterrows():
        over_implied = implied_probability_or_even(row["over_odds"])
        under_implied = implied_probability_or_even(row["under_odds"])
        over_raw_hit_rate = float(row["over_hit_rate"])
        under_raw_hit_rate = float(row["under_hit_rate"])
        over_hit_rate, over_applied, over_steps = apply_calibrated_hit_rate(
            over_raw_hit_rate,
            row["stat"],
            "over",
            row.get("confidence_label", row.get("confidence")),
            calibration_factors,
        )
        under_hit_rate, under_applied, under_steps = apply_calibrated_hit_rate(
            under_raw_hit_rate,
            row["stat"],
            "under",
            row.get("confidence_label", row.get("confidence")),
            calibration_factors,
        )
        over_edge = over_hit_rate - over_implied
        under_edge = under_hit_rate - under_implied

        if np.nanmax([over_edge, under_edge]) == over_edge:
            side = "over"
            hit_rate = over_hit_rate
            raw_hit_rate = over_raw_hit_rate
            edge = over_edge
            odds = row["over_odds"]
            calibration_applied = over_applied
            calibration_steps = over_steps
        else:
            side = "under"
            hit_rate = under_hit_rate
            raw_hit_rate = under_raw_hit_rate
            edge = under_edge
            odds = row["under_odds"]
            calibration_applied = under_applied
            calibration_steps = under_steps

        if calibration_applied:
            applied_count += 1
            if len(applied_examples) < 5:
                applied_examples.append(
                    f"{row['player_name']} {row['stat']} {side}: {raw_hit_rate:.4f}->{hit_rate:.4f} ({','.join(calibration_steps)})"
                )
        else:
            skipped_count += 1

        bet_date = resolved_bet_date()
        line_delta = float(row.get("line_delta", row["mean"] - row["line"]))
        stat_name = app_stat_name(row["stat"])
        confidence = row["confidence"]
        confidence_score = confidence_to_score(confidence)
        rows.append(
            {
                "DATE": bet_date,
                "PLAYER": row["player_name"],
                "TEAM": row["team"],
                "MATCHUP": matchup_label(row["team"], row["opponent"]),
                "STAT": stat_name,
                "RAW_STAT": row["stat"],
                "BET": side_label(side, row["stat"]),
                "LINE": row["line"],
                "PROJECTION": row["mean"],
                "EDGE": line_delta,
                "ABS_EDGE": abs(line_delta),
                "STDDEV": estimated_std(row),
                "HIT_RATE": hit_rate,
                "MODEL_CONFIDENCE": str(confidence).upper(),
                "BET_CONFIDENCE": max(0.0, (float(hit_rate) - 0.5) * 100.0),
                "CONFIDENCE_LABEL": str(confidence).title(),
                "RESULT": "",
                "ACTUAL": np.nan,
                "bet_date": today_timestamp().date().isoformat(),
                "player_name": row["player_name"],
                "team": row["team"],
                "opponent": row["opponent"],
                "stat": row["stat"],
                "line": row["line"],
                "side": side,
                "sportsbook": row["sportsbook"],
                "odds": odds,
                "hit_rate": hit_rate,
                "edge": edge,
                "projection_mean": row["mean"],
                "projection_median": row["median"],
                "floor": row["floor"],
                "ceiling": row["ceiling"],
                "projected_minutes": row["projected_minutes"],
                "confidence": confidence,
                "confidence_score": confidence_score,
                "line_delta": line_delta,
                "actual_value": np.nan,
                "bet_result": "",
            }
        )
    ranked = pd.DataFrame(rows)
    if calibration_factors is not None:
        logger.info(
            "WNBA calibration applied to %s candidate sides; %s candidate sides used raw hit rates.",
            applied_count,
            skipped_count,
        )
        for message in applied_examples:
            logger.info("Calibration sample | %s", message)
    if ranked.empty:
        return pd.DataFrame(columns=BEST_BET_COLUMNS)
    ranked = ranked[(ranked["edge"] >= MIN_EDGE) & (ranked["hit_rate"] >= MIN_HIT_RATE)].copy()
    if ranked.empty:
        return pd.DataFrame(columns=BEST_BET_COLUMNS)
    ranked["bet_quality_score"] = (
        100 * ranked["edge"]
        + 25 * (ranked["hit_rate"] - 0.5)
        + 2.0 * ranked["confidence_score"]
        + 0.03 * ranked["projected_minutes"].clip(lower=0)
        + ranked["line_delta"].abs().fillna(0)
    )
    ranked = ranked.sort_values(
        ["bet_quality_score", "edge", "hit_rate", "confidence_score"],
        ascending=[False, False, False, False],
    )
    ranked = ranked.groupby("player_name", group_keys=False).head(MAX_BETS_PER_PLAYER)
    ranked = ranked.groupby("stat", group_keys=False).head(MAX_BETS_PER_STAT)
    ranked = ranked.head(MAX_BETS_TOTAL).reset_index(drop=True)
    return ranked


def empty_state_best_bets(reason: str, candidate_count: int, qualified_count: int = 0) -> pd.DataFrame:
    row = {column: np.nan for column in BEST_BET_COLUMNS}
    bet_date = resolved_bet_date()
    row.update(
        {
            "DATE": bet_date,
            "bet_date": bet_date,
            "empty_state_reason": reason,
            "candidate_count": candidate_count,
            "qualified_count": qualified_count,
        }
    )
    return pd.DataFrame([row], columns=BEST_BET_COLUMNS)


def write_df(path, df: pd.DataFrame, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        pd.DataFrame(columns=columns).to_csv(path, index=False)
    else:
        df.reindex(columns=columns).to_csv(path, index=False)


def load_optional_csv(path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def stable_history_key_columns(frame: pd.DataFrame) -> list[str]:
    columns = []
    for candidate in ["bet_date", "DATE"]:
        if candidate in frame.columns:
            columns.append(candidate)
            break
    for candidate in ["player_name", "PLAYER"]:
        if candidate in frame.columns:
            columns.append(candidate)
            break
    for candidate in ["stat", "RAW_STAT", "STAT"]:
        if candidate in frame.columns:
            columns.append(candidate)
            break
    for candidate in ["side", "BET"]:
        if candidate in frame.columns:
            columns.append(candidate)
            break
    for candidate in ["line", "LINE"]:
        if candidate in frame.columns:
            columns.append(candidate)
            break
    return columns


def build_diagnostics(simulation_detail: pd.DataFrame) -> None:
    lines = load_optional_csv(CANONICAL_SPORTSBOOK_LINES_PATH)
    projections = load_optional_csv(PROJECTIONS_PATH)

    unmatched_player_columns = ["LINES_PLAYER", "PLAYER_KEY", "CLOSE_MATCH_1", "CLOSE_MATCH_2", "CLOSE_MATCH_3"]
    unmatched_stat_columns = ["PLAYER", "RAW_STAT", "NORMALIZED_STAT"]
    match_audit_columns = [
        "LINES_PLAYER",
        "PROJECTION_PLAYER",
        "PLAYER_KEY",
        "RAW_STAT",
        "NORMALIZED_STAT",
        "LINE",
        "PROJECTION",
        "SPORTSBOOK",
        "OVER_ODDS",
        "UNDER_ODDS",
        "OVER_HIT_RATE",
        "UNDER_HIT_RATE",
        "BEST_SIDE",
        "BEST_EDGE",
        "QUALIFIES",
        "REASON",
    ]

    if lines.empty:
        write_df(UNMATCHED_PLAYERS_PATH, pd.DataFrame(), unmatched_player_columns)
        write_df(UNMATCHED_STATS_PATH, pd.DataFrame(), unmatched_stat_columns)
        write_df(MATCH_AUDIT_PATH, pd.DataFrame(), match_audit_columns)
        return

    lines = lines.copy()
    if "player_key" not in lines.columns:
        lines["player_key"] = lines["player_name"].map(canonicalize_name)

    projection_keys: set[str] = set()
    projection_names: dict[str, str] = {}
    if not projections.empty and "player_name" in projections.columns:
        for name in projections["player_name"].dropna().tolist():
            key = canonicalize_name(name)
            projection_keys.add(key)
            projection_names[key] = str(name)
    if not simulation_detail.empty:
        for _, row in simulation_detail.iterrows():
            key = str(row.get("player_key") or canonicalize_name(row.get("player_name"))).strip()
            if key:
                projection_keys.add(key)
                projection_names.setdefault(key, str(row.get("player_name", "")))

    line_keys = set(lines["player_key"].dropna().astype(str).tolist())
    close_pool = sorted(projection_keys)
    unmatched_players = []
    for key in sorted(line_keys - projection_keys):
        raw_name = lines.loc[lines["player_key"] == key, "player_name"].iloc[0]
        close_matches = []
        if close_pool:
            import difflib

            close_matches = difflib.get_close_matches(key, close_pool, n=3, cutoff=0.75)
        unmatched_players.append(
            {
                "LINES_PLAYER": raw_name,
                "PLAYER_KEY": key,
                "CLOSE_MATCH_1": close_matches[0] if len(close_matches) > 0 else "",
                "CLOSE_MATCH_2": close_matches[1] if len(close_matches) > 1 else "",
                "CLOSE_MATCH_3": close_matches[2] if len(close_matches) > 2 else "",
            }
        )

    matched_pairs = set()
    if not simulation_detail.empty:
        matched_pairs = {
            (
                str(row.get("player_key") or canonicalize_name(row.get("player_name"))),
                str(row.get("stat")),
                float(row.get("line")),
            )
            for _, row in simulation_detail.iterrows()
            if pd.notna(row.get("line"))
        }

    unmatched_stats = []
    for _, line in lines.iterrows():
        key = str(line.get("player_key", ""))
        stat = str(line.get("stat", ""))
        line_value = pd.to_numeric(line.get("line"), errors="coerce")
        if key not in projection_keys or pd.isna(line_value):
            continue
        if (key, stat, float(line_value)) not in matched_pairs:
            unmatched_stats.append(
                {
                    "PLAYER": line.get("player_name"),
                    "RAW_STAT": stat,
                    "NORMALIZED_STAT": app_stat_name(stat),
                }
            )

    match_audit = []
    if not simulation_detail.empty:
        for _, row in simulation_detail.iterrows():
            key = str(row.get("player_key") or canonicalize_name(row.get("player_name"))).strip()
            match_audit.append(
                {
                    "LINES_PLAYER": row.get("player_name"),
                    "PROJECTION_PLAYER": projection_names.get(key, row.get("player_name")),
                    "PLAYER_KEY": key,
                    "RAW_STAT": row.get("stat"),
                    "NORMALIZED_STAT": app_stat_name(row.get("stat")),
                    "LINE": row.get("line"),
                    "PROJECTION": row.get("mean"),
                    "SPORTSBOOK": row.get("sportsbook"),
                    "OVER_ODDS": row.get("over_odds"),
                    "UNDER_ODDS": row.get("under_odds"),
                    "OVER_HIT_RATE": row.get("over_hit_rate"),
                    "UNDER_HIT_RATE": row.get("under_hit_rate"),
                    "BEST_SIDE": "",
                    "BEST_EDGE": np.nan,
                    "QUALIFIES": False,
                    "REASON": "",
                }
            )

    if match_audit:
        audit_df = pd.DataFrame(match_audit)
        for idx, row in audit_df.iterrows():
            detail = simulation_detail.iloc[idx]
            over_edge = float(detail.get("over_hit_rate", np.nan)) - implied_probability_or_even(detail.get("over_odds"))
            under_edge = float(detail.get("under_hit_rate", np.nan)) - implied_probability_or_even(detail.get("under_odds"))
            if over_edge >= under_edge:
                side = "over"
                edge = over_edge
                hit_rate = float(detail.get("over_hit_rate", np.nan))
            else:
                side = "under"
                edge = under_edge
                hit_rate = float(detail.get("under_hit_rate", np.nan))
            reasons = []
            if edge < MIN_EDGE:
                reasons.append(f"edge<{MIN_EDGE}")
            if hit_rate < MIN_HIT_RATE:
                reasons.append(f"hit_rate<{MIN_HIT_RATE}")
            audit_df.at[idx, "BEST_SIDE"] = side
            audit_df.at[idx, "BEST_EDGE"] = edge
            audit_df.at[idx, "QUALIFIES"] = not reasons
            audit_df.at[idx, "REASON"] = ";".join(reasons) if reasons else "qualified"
    else:
        audit_df = pd.DataFrame()

    write_df(UNMATCHED_PLAYERS_PATH, pd.DataFrame(unmatched_players).drop_duplicates(), unmatched_player_columns)
    write_df(UNMATCHED_STATS_PATH, pd.DataFrame(unmatched_stats).drop_duplicates(), unmatched_stat_columns)
    write_df(MATCH_AUDIT_PATH, audit_df.drop_duplicates(), match_audit_columns)


def append_history(best_bets: pd.DataFrame, logger) -> None:
    if best_bets.empty:
        return
    history_key_columns = stable_history_key_columns(best_bets)
    if len(history_key_columns) < 5:
        logger.warning(
            "Skipping WNBA history append because stable dedupe keys are incomplete: %s",
            history_key_columns,
        )
        return
    non_empty_bets = best_bets.copy()
    if "player_name" in non_empty_bets.columns:
        non_empty_bets = non_empty_bets[non_empty_bets["player_name"].fillna("").astype(str).str.strip() != ""]
    if non_empty_bets.empty:
        logger.info("Skipping WNBA history append because there are no player rows to record.")
        return
    if BETTING_RECORD_PATH.exists():
        history = pd.read_csv(BETTING_RECORD_PATH)
        combined = pd.concat([history, non_empty_bets], ignore_index=True)
        before_count = len(combined)
        combined = combined.drop_duplicates(subset=history_key_columns, keep="last")
        logger.info(
            "WNBA history dedupe complete | keys=%s | before=%s | after=%s",
            history_key_columns,
            before_count,
            len(combined),
        )
    else:
        combined = non_empty_bets.copy()
    combined.to_csv(BETTING_RECORD_PATH, index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build WNBA best bets.")
    parser.add_argument("--dry-run", action="store_true", help="Build outputs without appending to bet history.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logger = setup_logging("build_wnba_best_bets")
    simulation_detail = pd.read_csv(SIMULATION_DETAIL_PATH)
    build_diagnostics(simulation_detail)
    best_bets = rank_bets(simulation_detail, logger)
    if best_bets.empty:
        reason = "no_simulation_rows" if simulation_detail.empty else "no_candidates_met_edge_and_hit_rate_thresholds"
        best_bets = empty_state_best_bets(reason, len(simulation_detail), 0)
    best_bets.to_csv(BEST_BETS_PATH, index=False)
    best_bets.to_csv(BEST_BETS_ARCHIVE_PATH, index=False)
    archive_dataframe(best_bets, BEST_BETS_ARCHIVE_DIR_DATED, "wnba_best_bets")
    if args.dry_run:
        logger.info("WNBA best bets dry-run enabled; skipping history append.")
    else:
        append_history(best_bets, logger)
    logger.info("Saved %s best bets to %s", len(best_bets), BEST_BETS_PATH)


if __name__ == "__main__":
    main()
