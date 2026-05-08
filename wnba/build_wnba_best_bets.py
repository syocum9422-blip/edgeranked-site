from __future__ import annotations

import numpy as np
import pandas as pd

from wnba_model_config import (
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


def rank_bets(simulation_detail: pd.DataFrame) -> pd.DataFrame:
    if simulation_detail.empty:
        return simulation_detail

    rows = []
    for _, row in simulation_detail.iterrows():
        over_implied = american_odds_to_implied_probability(row["over_odds"])
        under_implied = american_odds_to_implied_probability(row["under_odds"])
        over_edge = row["over_hit_rate"] - over_implied if not np.isnan(over_implied) else np.nan
        under_edge = row["under_hit_rate"] - under_implied if not np.isnan(under_implied) else np.nan

        if np.isnan(over_edge) and np.isnan(under_edge):
            continue
        if np.nanmax([over_edge, under_edge]) == over_edge:
            side = "over"
            hit_rate = row["over_hit_rate"]
            edge = over_edge
            odds = row["over_odds"]
        else:
            side = "under"
            hit_rate = row["under_hit_rate"]
            edge = under_edge
            odds = row["under_odds"]

        bet_date = today_timestamp().date().isoformat()
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
    if ranked.empty:
        return ranked
    ranked = ranked[(ranked["edge"] >= MIN_EDGE) & (ranked["hit_rate"] >= MIN_HIT_RATE)].copy()
    if ranked.empty:
        return ranked
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
                }
            )

    write_df(UNMATCHED_PLAYERS_PATH, pd.DataFrame(unmatched_players).drop_duplicates(), unmatched_player_columns)
    write_df(UNMATCHED_STATS_PATH, pd.DataFrame(unmatched_stats).drop_duplicates(), unmatched_stat_columns)
    write_df(MATCH_AUDIT_PATH, pd.DataFrame(match_audit).drop_duplicates(), match_audit_columns)


def append_history(best_bets: pd.DataFrame) -> None:
    if best_bets.empty:
        return
    if BETTING_RECORD_PATH.exists():
        history = pd.read_csv(BETTING_RECORD_PATH)
        combined = pd.concat([history, best_bets], ignore_index=True)
        combined = combined.drop_duplicates(
            subset=["bet_date", "player_name", "stat", "line", "side", "sportsbook"], keep="last"
        )
    else:
        combined = best_bets.copy()
    combined.to_csv(BETTING_RECORD_PATH, index=False)


def main() -> None:
    logger = setup_logging("build_wnba_best_bets")
    simulation_detail = pd.read_csv(SIMULATION_DETAIL_PATH)
    build_diagnostics(simulation_detail)
    best_bets = rank_bets(simulation_detail)
    best_bets.to_csv(BEST_BETS_PATH, index=False)
    best_bets.to_csv(BEST_BETS_ARCHIVE_PATH, index=False)
    archive_dataframe(best_bets, BEST_BETS_ARCHIVE_DIR_DATED, "wnba_best_bets")
    append_history(best_bets)
    logger.info("Saved %s best bets to %s", len(best_bets), BEST_BETS_PATH)


if __name__ == "__main__":
    main()
