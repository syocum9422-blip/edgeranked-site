from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

from wnba_model_config import DATASET_PATH, RAW_SPORTSBOOK_LINES_PATH, TODAY_FEATURES_PATH
from wnba_model_utils import canonicalize_name, load_inputs_for_pipeline, setup_logging, standardize_team_abbrev, today_timestamp


SLATE_TEAM_AUDIT_PATH = TODAY_FEATURES_PATH.parent / "wnba_slate_team_audit.csv"
PLAYER_COVERAGE_AUDIT_PATH = TODAY_FEATURES_PATH.parent / "wnba_player_coverage_audit.csv"


def build_today_team_map(schedule_today: pd.DataFrame) -> pd.DataFrame:
    if schedule_today.empty:
        return pd.DataFrame(columns=["game_date", "game_id", "team", "opponent", "is_home", "home_away"])

    schedule_today = schedule_today.drop_duplicates(subset=["game_date", "home_team", "away_team", "game_id"]).copy()
    schedule_today["home_team"] = schedule_today["home_team"].map(standardize_team_abbrev)
    schedule_today["away_team"] = schedule_today["away_team"].map(standardize_team_abbrev)
    home = schedule_today[["game_date", "game_id", "home_team", "away_team"]].copy()
    home["team"] = home["home_team"]
    home["opponent"] = home["away_team"]
    home["is_home"] = 1
    home["home_away"] = "H"

    away = schedule_today[["game_date", "game_id", "home_team", "away_team"]].copy()
    away["team"] = away["away_team"]
    away["opponent"] = away["home_team"]
    away["is_home"] = 0
    away["home_away"] = "A"
    return pd.concat([home, away], ignore_index=True)[["game_date", "game_id", "team", "opponent", "is_home", "home_away"]]


def fetch_espn_scoreboard_team_map(game_date: pd.Timestamp, logger) -> pd.DataFrame:
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={game_date.strftime('%Y%m%d')}"
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning("Could not fetch ESPN date scoreboard for WNBA slate expansion: %s", exc)
        return pd.DataFrame(columns=["game_date", "game_id", "team", "opponent", "is_home", "home_away"])

    rows = []
    for event in payload.get("events", []) or []:
        competition = (event.get("competitions") or [{}])[0]
        competitors = competition.get("competitors", []) or []
        home = next((item for item in competitors if item.get("homeAway") == "home"), None)
        away = next((item for item in competitors if item.get("homeAway") == "away"), None)
        if not home or not away:
            continue

        home_team = standardize_team_abbrev((home.get("team") or {}).get("abbreviation"))
        away_team = standardize_team_abbrev((away.get("team") or {}).get("abbreviation"))
        if not home_team or not away_team:
            continue

        rows.extend(
            [
                {
                    "game_date": game_date,
                    "game_id": event.get("id", f"{game_date.strftime('%Y%m%d')}_{away_team}_{home_team}"),
                    "team": home_team,
                    "opponent": away_team,
                    "is_home": 1,
                    "home_away": "H",
                },
                {
                    "game_date": game_date,
                    "game_id": event.get("id", f"{game_date.strftime('%Y%m%d')}_{away_team}_{home_team}"),
                    "team": away_team,
                    "opponent": home_team,
                    "is_home": 0,
                    "home_away": "A",
                },
            ]
        )
    return pd.DataFrame(rows, columns=["game_date", "game_id", "team", "opponent", "is_home", "home_away"])


def load_prizepicks_lines_raw(logger) -> pd.DataFrame:
    if not RAW_SPORTSBOOK_LINES_PATH.exists():
        logger.warning("Raw sportsbook lines file missing: %s", RAW_SPORTSBOOK_LINES_PATH)
        return pd.DataFrame()

    lines = pd.read_csv(RAW_SPORTSBOOK_LINES_PATH)
    if lines.empty or "team" not in lines.columns or "player_name" not in lines.columns:
        return pd.DataFrame()

    source = lines.get("_data_source", pd.Series("", index=lines.index)).fillna("").astype(str).str.lower()
    live_prizepicks = lines[source.eq("api:prizepicks")].copy()
    if live_prizepicks.empty:
        return pd.DataFrame()

    live_prizepicks["team"] = live_prizepicks["team"].map(standardize_team_abbrev)
    live_prizepicks["player_key"] = live_prizepicks["player_name"].map(canonicalize_name)
    if "opponent" in live_prizepicks.columns:
        live_prizepicks["opponent"] = live_prizepicks["opponent"].map(standardize_team_abbrev)
    return live_prizepicks


def selected_game_date(schedule_today: pd.DataFrame) -> pd.Timestamp:
    if not schedule_today.empty and "game_date" in schedule_today.columns:
        dates = pd.to_datetime(schedule_today["game_date"], errors="coerce").dropna()
        if not dates.empty:
            return dates.min().normalize()
    return today_timestamp()


def prizepicks_metadata_team_map(prizepicks_lines: pd.DataFrame, game_date: pd.Timestamp) -> pd.DataFrame:
    if prizepicks_lines.empty or "opponent" not in prizepicks_lines.columns:
        return pd.DataFrame(columns=["game_date", "game_id", "team", "opponent", "is_home", "home_away"])

    rows = []
    for team, group in prizepicks_lines.groupby("team", dropna=True):
        opponents = group["opponent"].dropna().astype(str)
        opponents = opponents[(opponents != "") & (opponents.str.upper() != "NAN")]
        if opponents.empty:
            continue
        opponent = standardize_team_abbrev(opponents.iloc[0])
        if not opponent:
            continue
        rows.append(
            {
                "game_date": game_date,
                "game_id": f"{game_date.strftime('%Y%m%d')}_{team}_{opponent}_PRIZEPICKS",
                "team": team,
                "opponent": opponent,
                "is_home": 0,
                "home_away": "N",
            }
        )
    return pd.DataFrame(rows, columns=["game_date", "game_id", "team", "opponent", "is_home", "home_away"])


def build_slate_team_audit(schedule_team_map: pd.DataFrame, prizepicks_lines: pd.DataFrame, slate_team_map: pd.DataFrame) -> pd.DataFrame:
    schedule_teams = set(schedule_team_map["team"].dropna().astype(str)) if not schedule_team_map.empty else set()
    prizepicks_teams = set(prizepicks_lines["team"].dropna().astype(str)) if not prizepicks_lines.empty else set()
    included_teams = set(slate_team_map["team"].dropna().astype(str)) if not slate_team_map.empty else set()
    teams = sorted(schedule_teams | prizepicks_teams | included_teams)

    rows = []
    for team in teams:
        source_schedule = team in schedule_teams
        source_prizepicks = team in prizepicks_teams
        included = team in included_teams
        if source_schedule and source_prizepicks:
            reason = "scheduled_and_live_prizepicks"
        elif source_schedule:
            reason = "scheduled"
        elif source_prizepicks and included:
            reason = "included_with_resolved_matchup"
        elif source_prizepicks:
            reason = "excluded_not_on_canonical_slate"
        else:
            reason = "not_included"
        rows.append(
            {
                "team": team,
                "source_schedule": source_schedule,
                "source_prizepicks": source_prizepicks,
                "included": included,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows, columns=["team", "source_schedule", "source_prizepicks", "included", "reason"])


def build_expanded_slate_team_map(schedule_today: pd.DataFrame, prizepicks_lines: pd.DataFrame, logger) -> pd.DataFrame:
    game_date = selected_game_date(schedule_today)
    schedule_team_map = build_today_team_map(schedule_today)
    if schedule_team_map.empty:
        schedule_team_map = fetch_espn_scoreboard_team_map(game_date, logger)
    schedule_team_map = schedule_team_map.dropna(subset=["team", "opponent"])
    schedule_team_map = schedule_team_map[schedule_team_map["opponent"].astype(str).str.upper() != "UNKNOWN"]
    schedule_team_map = schedule_team_map.drop_duplicates(subset=["team"], keep="last").reset_index(drop=True)

    if schedule_team_map.empty:
        raise ValueError("Unable to build WNBA canonical slate with resolved opponents.")

    slate_team_map = schedule_team_map.copy()
    unresolved_prizepicks_teams = sorted(set(prizepicks_lines["team"].dropna().astype(str)) - set(slate_team_map["team"].astype(str)))
    if unresolved_prizepicks_teams:
        logger.info(
            "excluded_not_on_canonical_slate=%s",
            ", ".join(unresolved_prizepicks_teams),
        )

    audit = build_slate_team_audit(schedule_team_map, prizepicks_lines, slate_team_map)
    SLATE_TEAM_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(SLATE_TEAM_AUDIT_PATH, index=False)

    if (slate_team_map["opponent"].astype(str).str.upper() == "UNKNOWN").any():
        raise ValueError("WNBA canonical slate contains UNKNOWN opponent rows.")
    return slate_team_map


def latest_player_rows(dataset: pd.DataFrame) -> pd.DataFrame:
    latest = (
        dataset.sort_values(["player_key", "game_date"])
        .groupby("player_key", as_index=False)
        .tail(1)
        .copy()
    )
    latest["last_game_date"] = latest["game_date"]
    return latest


def build_live_line_team_map(sportsbook_lines: pd.DataFrame) -> pd.DataFrame:
    if sportsbook_lines.empty or "player_key" not in sportsbook_lines.columns or "team" not in sportsbook_lines.columns:
        return pd.DataFrame(columns=["player_key", "team"])

    live_teams = sportsbook_lines[["player_key", "team"]].dropna().copy()
    live_teams["team"] = live_teams["team"].map(standardize_team_abbrev)
    return live_teams.drop_duplicates("player_key")


def latest_backfill_status_lookup() -> dict[str, str]:
    raw_dir = RAW_SPORTSBOOK_LINES_PATH.parent
    reports = sorted(Path(raw_dir).glob("wnba_history_backfill_report_*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not reports:
        return {}
    try:
        report = pd.read_csv(reports[0])
    except Exception:
        return {}
    required = {"player_name", "resolution_status"}
    if report.empty or not required.issubset(report.columns):
        return {}
    report = report.copy()
    report["player_key"] = report["player_name"].map(canonicalize_name)
    return report.dropna(subset=["player_key"]).drop_duplicates("player_key", keep="last").set_index("player_key")["resolution_status"].astype(str).to_dict()


def apply_live_line_teams(latest: pd.DataFrame, live_line_teams: pd.DataFrame) -> pd.DataFrame:
    if live_line_teams.empty:
        return latest

    updated = latest.merge(live_line_teams, on="player_key", how="left", suffixes=("", "_live_line"))
    updated["team"] = updated["team_live_line"].combine_first(updated["team"])
    return updated.drop(columns=["team_live_line"])


def apply_status_filter(frame: pd.DataFrame, player_status: pd.DataFrame) -> pd.DataFrame:
    if player_status.empty:
        return frame
    merged = frame.merge(player_status[["player_key", "status"]], on="player_key", how="left")
    excluded = {"out", "doubtful", "inactive", "suspended"}
    merged = merged[~merged["status"].fillna("available").isin(excluded)].copy()
    return merged.drop(columns=["status"])


def apply_recency_filter(frame: pd.DataFrame, sportsbook_lines: pd.DataFrame, logger) -> pd.DataFrame:
    recent = frame[frame["days_since_last_game"].fillna(999) <= 30].copy()
    if not recent.empty:
        return recent

    if not sportsbook_lines.empty and "player_key" in sportsbook_lines.columns:
        live_player_keys = set(sportsbook_lines["player_key"].dropna().astype(str))
        live_backed = frame[frame["player_key"].astype(str).isin(live_player_keys)].copy()
        if not live_backed.empty:
            frame_teams = set(frame["team"].dropna().astype(str))
            live_backed_teams = set(live_backed["team"].dropna().astype(str))
            missing_teams = sorted(frame_teams - live_backed_teams)
            if missing_teams:
                logger.warning(
                    "Live-line recency fallback would drop canonical slate teams %s; keeping %d canonical-slate players instead.",
                    missing_teams,
                    len(frame),
                )
                return frame.copy()
            logger.warning(
                "No players passed the 30-day recency filter; keeping %d live-line-backed players for opening slate.",
                len(live_backed),
            )
            return live_backed

    logger.warning(
        "No players passed the 30-day recency filter and no canonical live-line-backed players were available; keeping %d canonical-slate players.",
        len(frame),
    )
    return frame.copy()


def build_player_coverage_audit(
    prizepicks_lines: pd.DataFrame,
    latest: pd.DataFrame,
    today_features: pd.DataFrame,
    team_map: pd.DataFrame,
) -> pd.DataFrame:
    columns = ["player_name", "team", "opponent", "has_live_line", "has_history", "history_source", "included", "reason"]
    if prizepicks_lines.empty:
        return pd.DataFrame(columns=columns)

    live_players = prizepicks_lines[["player_name", "player_key", "team"]].drop_duplicates().copy()
    slate_lookup = team_map.set_index("team")["opponent"].to_dict()
    history_sources = latest.set_index("player_key")["_data_source"].to_dict() if "_data_source" in latest.columns else {}
    history_keys = set(latest["player_key"].dropna().astype(str))
    included_keys = set(today_features["player_key"].dropna().astype(str))
    backfill_status = latest_backfill_status_lookup()

    rows = []
    for _, row in live_players.sort_values(["team", "player_name"]).iterrows():
        key = str(row["player_key"])
        team = str(row["team"])
        opponent = slate_lookup.get(team, "")
        has_history = key in history_keys
        included = key in included_keys
        if included:
            reason = "included"
        elif team not in slate_lookup:
            reason = "excluded_not_on_canonical_slate"
        elif not has_history:
            reason = "api_error" if backfill_status.get(key) == "api_error" else "no_history_found"
        else:
            reason = "excluded_by_status_or_filter"
        rows.append(
            {
                "player_name": row["player_name"],
                "team": team,
                "opponent": opponent,
                "has_live_line": True,
                "has_history": has_history,
                "history_source": history_sources.get(key, ""),
                "included": included,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows, columns=columns)



# Per-player exclusion reasons that are tolerated: the player is dropped and the slate
# continues (slate/team-level integrity is still enforced by the checks below). A
# recency/status-filtered player (`excluded_by_status_or_filter`) is tolerated the same way
# a no-history player is — dropping one lined player must not fail an otherwise-valid slate.
TOLERATED_PLAYER_EXCLUSION_REASONS = {
    "excluded_not_on_canonical_slate",
    "no_history_found",
    "api_error",
    "excluded_by_status_or_filter",
}


def validate_today_features(today_features: pd.DataFrame, team_map: pd.DataFrame, player_audit: pd.DataFrame, logger=None) -> None:
    canonical_slate_teams = set(team_map["team"].dropna().astype(str))
    canonical_live_players = player_audit[player_audit["team"].astype(str).isin(canonical_slate_teams)].copy()

    # Slate-level integrity (NOT relaxed): empty projections, UNKNOWN opponents, placeholder
    # rows, and any missing canonical team all remain fatal / fail-closed.
    if today_features.empty:
        raise ValueError("WNBA today features are empty.")
    if (today_features["opponent"].astype(str).str.upper() == "UNKNOWN").any():
        raise ValueError("WNBA today features contain UNKNOWN opponents.")
    if "_data_source" in today_features.columns and (today_features["_data_source"].astype(str) == "baseline_live_line").any():
        raise ValueError("WNBA today features contain baseline_live_line rows.")

    feature_teams = set(today_features["team"].dropna().astype(str))
    missing_canonical_teams = sorted(canonical_slate_teams - feature_teams)
    if missing_canonical_teams:
        raise ValueError(f"WNBA today features are missing canonical slate teams: {missing_canonical_teams}")

    # Per-player exclusions: log every excluded canonical-slate lined player with whether the
    # exclusion was tolerated, then fail closed only for non-tolerated reasons.
    excluded_live = canonical_live_players[~canonical_live_players["included"].astype(bool)]
    for rec in excluded_live[["player_name", "team", "reason"]].to_dict("records"):
        tolerated = str(rec["reason"]) in TOLERATED_PLAYER_EXCLUSION_REASONS
        message = (
            "WNBA canonical-slate lined player excluded: "
            f"player={rec['player_name']} team={rec['team']} reason={rec['reason']} "
            f"tolerated={'yes' if tolerated else 'no'}"
        )
        if logger is not None:
            (logger.warning if not tolerated else logger.info)(message)
        else:
            print(message)

    fatal_excluded = excluded_live[
        ~excluded_live["reason"].astype(str).isin(TOLERATED_PLAYER_EXCLUSION_REASONS)
    ]
    if not fatal_excluded.empty:
        details = fatal_excluded[["player_name", "team", "reason"]].to_dict("records")
        raise ValueError(f"WNBA canonical-slate live-line players were excluded for non-tolerated reasons: {details}")

def latest_team_snapshot(dataset: pd.DataFrame) -> pd.DataFrame:
    columns = ["team", "pace_last_10", "off_rating_last_10", "def_rating_last_10", "team_points_last_10", "opp_points_last_10"]
    return (
        dataset.sort_values(["team", "game_date"])
        .groupby("team", as_index=False)
        .tail(1)[columns]
        .drop_duplicates("team")
    )


def latest_opponent_snapshot(dataset: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "opponent",
        "opponent_points_allowed_last_10",
        "opponent_rebounds_allowed_last_10",
        "opponent_assists_allowed_last_10",
        "opponent_threes_made_allowed_last_10",
        "opponent_steals_allowed_last_10",
        "opponent_blocks_allowed_last_10",
    ]
    return (
        dataset.sort_values(["opponent", "game_date"])
        .groupby("opponent", as_index=False)
        .tail(1)[columns]
        .drop_duplicates("opponent")
    )


def latest_position_snapshot(dataset: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "opponent",
        "position",
        "pos_points_allowed_last_10",
        "pos_rebounds_allowed_last_10",
        "pos_assists_allowed_last_10",
        "pos_threes_made_allowed_last_10",
        "pos_steals_allowed_last_10",
        "pos_blocks_allowed_last_10",
    ]
    return (
        dataset.sort_values(["opponent", "position", "game_date"])
        .groupby(["opponent", "position"], as_index=False)
        .tail(1)[columns]
        .drop_duplicates(["opponent", "position"])
    )


def main() -> None:
    logger = setup_logging("build_wnba_features_today")
    dataset = pd.read_csv(DATASET_PATH, parse_dates=["game_date"])
    _, _, schedule_today, sportsbook_lines, _, player_status = load_inputs_for_pipeline(logger)
    prizepicks_lines = load_prizepicks_lines_raw(logger)
    if schedule_today.empty and prizepicks_lines.empty:
        raise ValueError("Today's schedule is empty and no live PrizePicks lines are available.")

    team_map = build_expanded_slate_team_map(schedule_today, prizepicks_lines, logger)
    live_line_teams = build_live_line_team_map(sportsbook_lines)
    latest = apply_live_line_teams(latest_player_rows(dataset), live_line_teams)
    today_features = latest.merge(team_map, on="team", how="inner", suffixes=("", "_today"))
    today_features["game_date"] = pd.to_datetime(today_features["game_date_today"]).dt.normalize()
    today_features["opponent"] = today_features["opponent_today"]
    today_features["is_home"] = today_features["is_home_today"]
    if "home_away_today" in today_features.columns:
        today_features["home_away"] = today_features["home_away_today"]
    today_features["days_since_last_game"] = (today_features["game_date"] - pd.to_datetime(today_features["last_game_date"])).dt.days
    today_features["rest_days"] = today_features["days_since_last_game"].sub(1).fillna(3).clip(lower=0, upper=7)
    today_features["is_back_to_back"] = (today_features["rest_days"] <= 0).astype(int)

    # Use historical rolling features from the latest completed game as the input state for today's matchup.
    drop_cols = [column for column in today_features.columns if column.endswith("_today")]
    today_features = today_features.drop(columns=drop_cols)
    today_features = today_features.merge(latest_team_snapshot(dataset), on="team", how="left", suffixes=("", "_team_latest"))
    today_features = today_features.merge(latest_opponent_snapshot(dataset), on="opponent", how="left", suffixes=("", "_opp_latest"))
    today_features = today_features.merge(latest_position_snapshot(dataset), on=["opponent", "position"], how="left")
    for column in [
        "pace_last_10",
        "off_rating_last_10",
        "def_rating_last_10",
        "team_points_last_10",
        "opp_points_last_10",
        "opponent_points_allowed_last_10",
        "opponent_rebounds_allowed_last_10",
        "opponent_assists_allowed_last_10",
        "opponent_threes_made_allowed_last_10",
        "opponent_steals_allowed_last_10",
        "opponent_blocks_allowed_last_10",
    ]:
        latest_column = f"{column}_opp_latest" if f"{column}_opp_latest" in today_features.columns else f"{column}_team_latest"
        if latest_column in today_features.columns:
            today_features[column] = today_features[latest_column].combine_first(today_features[column])
    drop_snapshot_cols = [
        column
        for column in today_features.columns
        if column.endswith("_team_latest") or column.endswith("_opp_latest")
    ]
    today_features = today_features.drop(columns=drop_snapshot_cols)
    today_features = apply_status_filter(today_features, player_status)
    today_features = apply_recency_filter(today_features, sportsbook_lines, logger)
    today_features = today_features.drop_duplicates(subset=["player_key", "team", "opponent", "game_date"])

    numeric_fill_cols = [
        "minutes",
        "minutes_rolling_mean_3",
        "minutes_rolling_mean_5",
        "minutes_rolling_mean_10",
        "season_avg_minutes",
    ]
    for column in numeric_fill_cols:
        if column in today_features.columns:
            today_features[column] = today_features[column].fillna(today_features["season_avg_minutes"])

    player_audit = build_player_coverage_audit(prizepicks_lines, latest, today_features, team_map)
    player_audit.to_csv(PLAYER_COVERAGE_AUDIT_PATH, index=False)
    validate_today_features(today_features, team_map, player_audit, logger)

    today_features.to_csv(TODAY_FEATURES_PATH, index=False)
    logger.info("Saved today's features to %s for %s players", TODAY_FEATURES_PATH, len(today_features))


if __name__ == "__main__":
    main()
