import os
import sys
import difflib
import math
import json
import pandas as pd

from nba_model.common import clean_name, find_col, normalize_columns, normalize_stat_name, safe_num
from nba_model.settings import (
    ALIASES_PATH,
    BEST_BETS_DIR,
    BEST_BETS_OUTPUT_PATH,
    CALIBRATION_FACTORS_PATH,
    HISTORY_PATH,
    LINES_PATH,
    MATCH_AUDIT_PATH,
    PROJECTIONS_PATH,
    TEAMS_TODAY_PATH,
    UNMATCHED_PLAYERS_PATH,
    UNMATCHED_STATS_PATH,
)

TOP_N_BETS = 7
MAX_UNDERS_IN_TOP = 1
UNDER_MIN_HIT_RATE = 0.73
UNDER_MIN_EDGE = 5.0
ELITE_UNDER_HIT_RATE = 0.78
ELITE_UNDER_EDGE = 6.5


def ensure_output_dirs():
    os.makedirs(BEST_BETS_DIR, exist_ok=True)


def load_csv(path, label):
    if not os.path.exists(path):
        print(f"ERROR: Missing {label} file: {path}")
        sys.exit(1)

    df = pd.read_csv(path)
    if df.empty:
        print(f"ERROR: {label} file is empty: {path}")
        sys.exit(1)

    return normalize_columns(df)


def load_aliases():
    if not os.path.exists(ALIASES_PATH):
        return {}

    try:
        aliases = pd.read_csv(ALIASES_PATH)
        aliases = normalize_columns(aliases)

        from_col = find_col(aliases, ["FROM_NAME", "FROM", "LINES_NAME"])
        to_col = find_col(aliases, ["TO_NAME", "TO", "PROJECTION_NAME"])

        alias_map = {}
        for _, row in aliases.iterrows():
            from_name = clean_name(row[from_col])
            to_name = clean_name(row[to_col])
            if from_name and to_name:
                alias_map[from_name] = to_name
        return alias_map
    except Exception as e:
        print(f"WARNING: Could not load aliases file: {e}")
        return {}


def first_existing_value(row, candidates):
    for c in candidates:
        if c in row.index:
            val = safe_num(row[c])
            if pd.notna(val):
                return float(val)
    return None


def get_projection_components(row):
    pts = first_existing_value(row, ["PTS_PROJ", "PTS", "PROJECTED_PTS"])
    reb = first_existing_value(row, ["REB_PROJ", "REB", "PROJECTED_REB"])
    ast = first_existing_value(row, ["AST_PROJ", "AST", "PROJECTED_AST"])
    stl = first_existing_value(row, ["STL_PROJ", "STL", "PROJECTED_STL"])
    blk = first_existing_value(row, ["BLK_PROJ", "BLK", "PROJECTED_BLK"])
    fg3m = first_existing_value(row, ["FG3M_PROJ", "FG3M", "3PM_PROJ", "THREES_PROJ"])
    tov = first_existing_value(row, ["TOV_PROJ", "TO_PROJ", "TOV", "TO"])
    fantasy = first_existing_value(row, ["FANTASY_PROJ", "FANTASY"])
    ftm = first_existing_value(row, ["FTM_PROJ", "FTM"])
    fta = first_existing_value(row, ["FTA_PROJ", "FTA"])
    fgm = first_existing_value(row, ["FGM_PROJ", "FGM"])
    fga = first_existing_value(row, ["FGA_PROJ", "FGA"])
    fg2m = first_existing_value(row, ["FG2M_PROJ", "FG2M"])
    fg2a = first_existing_value(row, ["FG2A_PROJ", "FG2A"])
    oreb = first_existing_value(row, ["OREB_PROJ", "OREB"])
    dreb = first_existing_value(row, ["DREB_PROJ", "DREB"])
    pf = first_existing_value(row, ["PF_PROJ", "PF"])
    dd = first_existing_value(row, ["DD_PROJ", "DD"])
    td = first_existing_value(row, ["TD_PROJ", "TD"])
    pts_3m = first_existing_value(row, ["PTS_3M_PROJ", "PTS_3M"])
    ast_3m = first_existing_value(row, ["AST_3M_PROJ", "AST_3M"])
    reb_3m = first_existing_value(row, ["REB_3M_PROJ", "REB_3M"])
    q3p = first_existing_value(row, ["Q3P_PROJ", "Q3P"])
    q5p = first_existing_value(row, ["Q5P_PROJ", "Q5P"])
    dunks = first_existing_value(row, ["DUNKS_PROJ", "DUNKS"])

    return {
        "PTS": pts,
        "REB": reb,
        "AST": ast,
        "STL": stl,
        "BLK": blk,
        "FG3M": fg3m,
        "TOV": tov,
        "FANTASY": fantasy,
        "FTM": ftm,
        "FTA": fta,
        "FGM": fgm,
        "FGA": fga,
        "FG2M": fg2m,
        "FG2A": fg2a,
        "OREB": oreb,
        "DREB": dreb,
        "PF": pf,
        "DD": dd,
        "TD": td,
        "PTS_3M": pts_3m,
        "AST_3M": ast_3m,
        "REB_3M": reb_3m,
        "Q3P": q3p,
        "Q5P": q5p,
        "DUNKS": dunks,
    }


def get_stddev_components(row):
    def first_std(candidates):
        return first_existing_value(row, candidates)

    return {
        "PTS": first_std(["SIM_PTS_STD", "PTS_STD"]),
        "REB": first_std(["SIM_REB_STD", "REB_STD"]),
        "AST": first_std(["SIM_AST_STD", "AST_STD"]),
        "STL": first_std(["SIM_STL_STD", "STL_STD"]),
        "BLK": first_std(["SIM_BLK_STD", "BLK_STD"]),
        "FG3M": first_std(["SIM_FG3M_STD", "FG3M_STD"]),
        "FG3A": first_std(["SIM_FG3A_STD", "FG3A_STD"]),
        "TOV": first_std(["SIM_TOV_STD", "TOV_STD"]),
        "FANTASY": first_std(["SIM_FANTASY_STD", "FANTASY_STD"]),
        "FTM": first_std(["SIM_FTM_STD", "FTM_STD"]),
        "FTA": first_std(["SIM_FTA_STD", "FTA_STD"]),
        "FGM": first_std(["SIM_FGM_STD", "FGM_STD"]),
        "FGA": first_std(["SIM_FGA_STD", "FGA_STD"]),
        "FG2M": first_std(["SIM_FG2M_STD", "FG2M_STD"]),
        "FG2A": first_std(["SIM_FG2A_STD", "FG2A_STD"]),
        "OREB": first_std(["SIM_OREB_STD", "OREB_STD"]),
        "DREB": first_std(["SIM_DREB_STD", "DREB_STD"]),
        "PF": first_std(["SIM_PF_STD", "PF_STD"]),
        "DD": first_std(["SIM_DD_STD", "DD_STD"]),
        "TD": first_std(["SIM_TD_STD", "TD_STD"]),
        "PTS_3M": first_std(["SIM_PTS_3M_STD", "PTS_3M_STD"]),
        "AST_3M": first_std(["SIM_AST_3M_STD", "AST_3M_STD"]),
        "REB_3M": first_std(["SIM_REB_3M_STD", "REB_3M_STD"]),
        "Q3P": first_std(["SIM_Q3P_STD", "Q3P_STD"]),
        "Q5P": first_std(["SIM_Q5P_STD", "Q5P_STD"]),
        "DUNKS": first_std(["SIM_DUNKS_STD", "DUNKS_STD"]),
    }


def get_projection_for_stat(row, stat):
    comps = get_projection_components(row)

    pts = comps["PTS"]
    reb = comps["REB"]
    ast = comps["AST"]
    stl = comps["STL"]
    blk = comps["BLK"]
    fg3m = comps["FG3M"]
    tov = comps["TOV"] if comps["TOV"] is not None else 0.0

    if stat == "PTS":
        return pts
    if stat == "REB":
        return reb
    if stat == "AST":
        return ast
    if stat == "STL":
        return stl
    if stat == "BLK":
        return blk
    if stat == "FG3M":
        return fg3m
    if stat == "FG3A":
        return first_existing_value(row, ["FG3A_PROJ", "FG3A"])
    if stat == "TOV":
        return tov
    if stat == "FANTASY":
        return comps["FANTASY"]
    if stat == "FTM":
        return comps["FTM"]
    if stat == "FTA":
        return comps["FTA"]
    if stat == "FGM":
        return comps["FGM"]
    if stat == "FGA":
        return comps["FGA"]
    if stat == "FG2M":
        return comps["FG2M"]
    if stat == "FG2A":
        return comps["FG2A"]
    if stat == "OREB":
        return comps["OREB"]
    if stat == "DREB":
        return comps["DREB"]
    if stat == "PF":
        return comps["PF"]
    if stat == "DD":
        return comps["DD"]
    if stat == "TD":
        return comps["TD"]
    if stat == "PTS_3M":
        return comps["PTS_3M"]
    if stat == "AST_3M":
        return comps["AST_3M"]
    if stat == "REB_3M":
        return comps["REB_3M"]
    if stat == "Q3P":
        return comps["Q3P"]
    if stat == "Q5P":
        return comps["Q5P"]
    if stat == "DUNKS":
        return comps["DUNKS"]
    if stat == "PR" and pts is not None and reb is not None:
        return pts + reb
    if stat == "PA" and pts is not None and ast is not None:
        return pts + ast
    if stat == "RA" and reb is not None and ast is not None:
        return reb + ast
    if stat == "PRA" and pts is not None and reb is not None and ast is not None:
        return pts + reb + ast
    if stat == "SB" and stl is not None and blk is not None:
        return stl + blk
    if stat == "FANTASY":
        if None not in (pts, reb, ast, stl, blk, fg3m):
            return (
                pts * 1.0
                + reb * 1.2
                + ast * 1.5
                + stl * 3.0
                + blk * 3.0
                + fg3m * 0.5
                - tov * 1.0
            )
    return None


def get_stddev_for_stat(row, stat):
    comps = get_stddev_components(row)

    if stat in comps and comps[stat] is not None:
        return float(comps[stat])

    if stat in {"PR", "PA", "RA", "PRA", "SB"}:
        combo_parts = {
            "PR": ["PTS", "REB"],
            "PA": ["PTS", "AST"],
            "RA": ["REB", "AST"],
            "PRA": ["PTS", "REB", "AST"],
            "SB": ["STL", "BLK"],
        }[stat]
        part_vars = []
        for part in combo_parts:
            std = comps.get(part)
            if std is None:
                return None
            part_vars.append(float(std) ** 2)
        return math.sqrt(sum(part_vars))

    return None


def normal_cdf(value, mean, std):
    if std is None or std <= 0:
        return 1.0 if value >= mean else 0.0
    z = (value - mean) / (std * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def estimate_side_probability(projection, line_value, stddev, side):
    if projection is None or pd.isna(projection):
        return None
    if stddev is None or stddev <= 0:
        if side == "OVER":
            return 1.0 if projection > line_value else 0.0
        return 1.0 if projection < line_value else 0.0

    over_prob = 1.0 - normal_cdf(line_value, projection, stddev)
    over_prob = max(0.0, min(over_prob, 1.0))
    if side == "OVER":
        return over_prob
    return 1.0 - over_prob


def confidence_from_probability(probability, abs_edge):
    if probability is None:
        if abs_edge >= 5:
            return "HIGH", "High"
        if abs_edge >= 3:
            return "MEDIUM", "Medium"
        return "LOW", "Low"

    if probability >= 0.66:
        return "HIGH", "High"
    if probability >= 0.58:
        return "MEDIUM", "Medium"
    return "LOW", "Low"


def write_df(path, rows, columns):
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)


def load_today_slate_teams():
    if not os.path.exists(TEAMS_TODAY_PATH):
        return set()

    try:
        teams_df = pd.read_csv(TEAMS_TODAY_PATH)
    except Exception:
        return set()

    teams_df = normalize_columns(teams_df)
    team_col = find_col(teams_df, ["TEAM", "TEAM_ABBREVIATION"], required=False)
    if not team_col:
        return set()

    return {
        str(team).strip().upper()
        for team in teams_df[team_col].dropna().tolist()
        if str(team).strip()
    }


def load_calibration_priors():
    if not os.path.exists(HISTORY_PATH):
        return {"side": {}, "stat_side": {}}

    try:
        history = pd.read_csv(HISTORY_PATH)
    except Exception:
        return {"side": {}, "stat_side": {}}

    if history.empty:
        return {"side": {}, "stat_side": {}}

    history.columns = [str(c).strip().lower() for c in history.columns]
    if "result" not in history.columns:
        return {"side": {}, "stat_side": {}}

    history = history[history["result"].isin(["WIN", "LOSS"])].copy()
    if history.empty:
        return {"side": {}, "stat_side": {}}

    if "prediction" not in history.columns:
        history["prediction"] = history.get("bet", "").astype(str).str.upper().map(
            lambda x: "OVER" if "OVER" in x else ("UNDER" if "UNDER" in x else "")
        )

    priors = {"side": {}, "stat_side": {}}

    for side, group in history.groupby("prediction"):
        if not side:
            continue
        wins = int((group["result"] == "WIN").sum())
        losses = int((group["result"] == "LOSS").sum())
        sample = wins + losses
        if sample == 0:
            continue
        # Beta prior shrinks tiny samples back toward 50%.
        rate = (wins + 5) / (sample + 10)
        priors["side"][side] = {"rate": rate, "sample": sample}

    if "stat" in history.columns:
        for (stat, side), group in history.groupby(["stat", "prediction"]):
            if not side:
                continue
            wins = int((group["result"] == "WIN").sum())
            losses = int((group["result"] == "LOSS").sum())
            sample = wins + losses
            if sample == 0:
                continue
            rate = (wins + 3) / (sample + 6)
            priors["stat_side"][(str(stat).upper(), side)] = {"rate": rate, "sample": sample}

    return priors


def load_calibration_factors():
    if not os.path.exists(CALIBRATION_FACTORS_PATH):
        return {}
    try:
        with open(CALIBRATION_FACTORS_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def bucket_hit_rate(value):
    if value is None or pd.isna(value):
        return None
    if value <= 0.55:
        return "<=55%"
    if value <= 0.60:
        return "55-60%"
    if value <= 0.65:
        return "60-65%"
    if value <= 0.70:
        return "65-70%"
    return "70%+"


def apply_calibration(hit_rate, stat, side, priors, factors=None):
    if hit_rate is None:
        return None

    calibrated = float(hit_rate)
    stat_key = (str(stat).upper(), side)
    stat_prior = priors["stat_side"].get(stat_key)
    side_prior = priors["side"].get(side)

    if stat_prior and stat_prior["sample"] >= 5:
        weight = min(0.22, 0.06 + (stat_prior["sample"] * 0.01))
        calibrated = ((1.0 - weight) * calibrated) + (weight * stat_prior["rate"])

    if side_prior and side_prior["sample"] >= 8:
        weight = min(0.18, 0.05 + (side_prior["sample"] * 0.005))
        calibrated = ((1.0 - weight) * calibrated) + (weight * side_prior["rate"])

    if factors:
        stat_side = factors.get("stat_side", {}).get(f"{str(stat).upper()}::{side}")
        if stat_side and stat_side.get("bets", 0) >= 5:
            weight = min(0.16, 0.04 + (0.008 * stat_side["bets"]))
            calibrated = ((1.0 - weight) * calibrated) + (weight * float(stat_side["win_rate"]))

        side_factor = factors.get("side", {}).get(side)
        if side_factor and side_factor.get("bets", 0) >= 8:
            weight = min(0.12, 0.03 + (0.004 * side_factor["bets"]))
            calibrated = ((1.0 - weight) * calibrated) + (weight * float(side_factor["win_rate"]))

        bucket = bucket_hit_rate(calibrated)
        bucket_factor = factors.get("hit_rate_bucket", {}).get(bucket)
        if bucket_factor and bucket_factor.get("bets", 0) >= 6:
            weight = min(0.10, 0.03 + (0.003 * bucket_factor["bets"]))
            calibrated = ((1.0 - weight) * calibrated) + (weight * float(bucket_factor["win_rate"]))

    return max(0.01, min(calibrated, 0.99))


def stat_priority(stat):
    preferred = {
        "PTS": 100,
        "REB": 96,
        "AST": 96,
        "PRA": 94,
        "PR": 92,
        "PA": 92,
        "RA": 90,
        "FG3M": 84,
        "STL": 76,
        "BLK": 76,
        "SB": 70,
        "FANTASY": 40,
    }
    return preferred.get(stat, 50)


def build_best_bets():
    ensure_output_dirs()
    alias_map = load_aliases()
    calibration_priors = load_calibration_priors()
    calibration_factors = load_calibration_factors()
    slate_teams = load_today_slate_teams()

    projections = load_csv(PROJECTIONS_PATH, "projections")
    lines = load_csv(LINES_PATH, "lines")

    player_col_proj = find_col(projections, ["PLAYER", "PLAYER_NAME", "NAME"])
    team_col_proj = find_col(projections, ["TEAM", "TEAM_ABBREVIATION"], required=False)
    matchup_col_proj = find_col(projections, ["MATCHUP", "GAME"], required=False)
    date_col_proj = find_col(projections, ["DATE", "GAME_DATE"], required=False)

    player_col_lines = find_col(lines, ["PLAYER", "PLAYER_NAME", "NAME"])
    team_col_lines = find_col(lines, ["TEAM", "TEAM_ABBREVIATION"], required=False)
    stat_col_lines = find_col(lines, ["STAT", "MARKET", "PROP"])
    line_col_lines = find_col(lines, ["LINE", "SPORTSBOOK_LINE"])
    start_time_col_lines = find_col(lines, ["START_TIME_ET", "GAME_TIME_ET", "START_TIME"], required=False)

    model_conf_col = find_col(projections, ["MODEL_CONFIDENCE"], required=False)
    bet_conf_col = find_col(projections, ["BET_CONFIDENCE", "CONFIDENCE"], required=False)
    conf_label_col = find_col(projections, ["CONFIDENCE_LABEL"], required=False)
    injury_status_col = find_col(projections, ["INJURY_STATUS"], required=False)
    active_prob_col = find_col(projections, ["ACTIVE_PROB"], required=False)

    if slate_teams and team_col_proj:
        projections = projections[
            projections[team_col_proj].astype(str).str.strip().str.upper().isin(slate_teams)
        ].copy()

    # TEMP: disable strict line-team slate filter because current lines board team values
    # are not aligning with slate_teams and it is zeroing out all lines.
    if slate_teams and team_col_lines:
        pass

    if start_time_col_lines and start_time_col_lines in lines.columns:
        start_times = pd.to_datetime(lines[start_time_col_lines], errors="coerce")
        valid_dates = start_times.dt.strftime("%Y-%m-%d")
        lines = lines[
            valid_dates.isna() | (valid_dates == pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d"))
        ].copy()

    projections["_PLAYER_KEY"] = projections[player_col_proj].apply(lambda x: clean_name(x, alias_map))
    lines["_PLAYER_KEY"] = lines[player_col_lines].apply(lambda x: clean_name(x, alias_map))
    lines["_STAT_KEY"] = lines[stat_col_lines].apply(normalize_stat_name)

    projection_player_keys = set(projections["_PLAYER_KEY"].dropna().tolist())

    rows = []
    unmatched_players = []
    unmatched_stats = []
    match_audit = []

    for _, line_row in lines.iterrows():
        player_key = line_row["_PLAYER_KEY"]
        raw_player = line_row[player_col_lines]
        raw_stat = line_row[stat_col_lines]
        stat = line_row["_STAT_KEY"]
        line_value = safe_num(line_row[line_col_lines])

        if pd.isna(line_value):
            continue

        if player_key not in projection_player_keys:
            close_matches = difflib.get_close_matches(
                player_key,
                list(projection_player_keys),
                n=3,
                cutoff=0.75
            )
            unmatched_players.append({
                "LINES_PLAYER": raw_player,
                "PLAYER_KEY": player_key,
                "CLOSE_MATCH_1": close_matches[0] if len(close_matches) > 0 else "",
                "CLOSE_MATCH_2": close_matches[1] if len(close_matches) > 1 else "",
                "CLOSE_MATCH_3": close_matches[2] if len(close_matches) > 2 else "",
            })
            continue

        proj_matches = projections[projections["_PLAYER_KEY"] == player_key]
        if proj_matches.empty:
            continue

        proj_row = proj_matches.iloc[0]
        injury_status = str(proj_row.get(injury_status_col, "")).strip().upper() if injury_status_col else ""
        active_prob = safe_num(proj_row.get(active_prob_col)) if active_prob_col else None

        # Skip stale book lines for players your injury file marks as essentially unavailable.
        if injury_status in {"OUT", "DOUBTFUL"}:
            continue
        if active_prob is not None and not pd.isna(active_prob) and float(active_prob) < 0.35:
            continue

        projection = get_projection_for_stat(proj_row, stat)
        stddev = get_stddev_for_stat(proj_row, stat)

        if projection is None or pd.isna(projection):
            unmatched_stats.append({
                "PLAYER": raw_player,
                "RAW_STAT": raw_stat,
                "NORMALIZED_STAT": stat
            })
            continue

        edge = round(float(projection) - float(line_value), 2)
        bet_side = "OVER" if edge > 0 else "UNDER"
        abs_edge = abs(edge)
        hit_rate = estimate_side_probability(projection, float(line_value), stddev, bet_side)
        hit_rate = apply_calibration(hit_rate, stat, bet_side, calibration_priors, calibration_factors)
        model_confidence, confidence_label = confidence_from_probability(hit_rate, abs_edge)

        if hit_rate is None and conf_label_col and pd.notna(proj_row.get(conf_label_col)):
            confidence_label = str(proj_row.get(conf_label_col)).strip().title()

        if hit_rate is None and model_conf_col and pd.notna(proj_row.get(model_conf_col)):
            model_confidence = str(proj_row.get(model_conf_col)).strip().upper()

        if bet_conf_col and pd.notna(proj_row.get(bet_conf_col)):
            bet_confidence = safe_num(proj_row.get(bet_conf_col))
            if pd.isna(bet_confidence):
                bet_confidence = round(abs_edge, 2)
        else:
            bet_confidence = round(abs_edge, 2)

        if hit_rate is not None:
            bet_confidence = round(max(float(bet_confidence), (hit_rate - 0.5) * 100.0), 2)

        # Make unders earn their way onto the board instead of flooding it.
        if bet_side == "UNDER":
            under_hit_rate = float(hit_rate) if hit_rate is not None else 0.0
            if under_hit_rate < UNDER_MIN_HIT_RATE or abs_edge < UNDER_MIN_EDGE:
                continue
            elite_under = int(
                under_hit_rate >= ELITE_UNDER_HIT_RATE and abs_edge >= ELITE_UNDER_EDGE
            )
        else:
            elite_under = 0

        if date_col_proj and pd.notna(proj_row.get(date_col_proj)):
            date_val = str(proj_row.get(date_col_proj))[:10]
        else:
            date_val = pd.Timestamp.today().strftime("%Y-%m-%d")

        rows.append({
            "DATE": date_val,
            "PLAYER": proj_row[player_col_proj],
            "TEAM": proj_row[team_col_proj] if team_col_proj else "",
            "MATCHUP": proj_row[matchup_col_proj] if matchup_col_proj else "",
            "STAT": stat,
            "RAW_STAT": raw_stat,
            "BET": f"{bet_side} {stat}",
            "SIDE": bet_side,
            "LINE": round(float(line_value), 2),
            "PROJECTION": round(float(projection), 2),
            "EDGE": round(edge, 2),
            "ABS_EDGE": round(abs_edge, 2),
            "STDDEV": round(float(stddev), 2) if stddev is not None else "",
            "HIT_RATE": round(float(hit_rate), 4) if hit_rate is not None else "",
            "STAT_PRIORITY": stat_priority(stat),
            "OVER_BONUS": 1 if bet_side == "OVER" else 0,
            "UNDER_FLAG": 1 if bet_side == "UNDER" else 0,
            "ELITE_UNDER": elite_under,
            "FANTASY_PENALTY": 0 if stat != "FANTASY" else 1,
            "MODEL_CONFIDENCE": model_confidence,
            "BET_CONFIDENCE": round(float(bet_confidence), 2),
            "CONFIDENCE_LABEL": confidence_label,
            "RESULT": "",
            "ACTUAL": ""
        })

        match_audit.append({
            "LINES_PLAYER": raw_player,
            "PROJECTION_PLAYER": proj_row[player_col_proj],
            "PLAYER_KEY": player_key,
            "RAW_STAT": raw_stat,
            "NORMALIZED_STAT": stat,
            "LINE": round(float(line_value), 2),
            "PROJECTION": round(float(projection), 2),
        })

    final_columns = [
        "DATE", "PLAYER", "TEAM", "MATCHUP", "STAT", "RAW_STAT", "BET", "LINE",
        "PROJECTION", "EDGE", "ABS_EDGE", "STDDEV", "HIT_RATE", "MODEL_CONFIDENCE", "BET_CONFIDENCE",
        "CONFIDENCE_LABEL", "RESULT", "ACTUAL"
    ]
    unmatched_player_columns = ["LINES_PLAYER", "PLAYER_KEY", "CLOSE_MATCH_1", "CLOSE_MATCH_2", "CLOSE_MATCH_3"]
    unmatched_stat_columns = ["PLAYER", "RAW_STAT", "NORMALIZED_STAT"]
    match_audit_columns = ["LINES_PLAYER", "PROJECTION_PLAYER", "PLAYER_KEY", "RAW_STAT", "NORMALIZED_STAT", "LINE", "PROJECTION"]

    best_bets = pd.DataFrame(rows)

    if not best_bets.empty:
        best_bets = best_bets.sort_values(
            by=[
                "STAT_PRIORITY",
                "HIT_RATE",
                "OVER_BONUS",
                "ELITE_UNDER",
                "FANTASY_PENALTY",
                "ABS_EDGE",
                "BET_CONFIDENCE"
            ],
            ascending=[False, False, False, False, True, False, False]
        ).copy()

        selected_rows = []
        under_count = 0
        for _, candidate in best_bets.iterrows():
            is_under = int(candidate.get("UNDER_FLAG", 0)) == 1
            is_elite_under = int(candidate.get("ELITE_UNDER", 0)) == 1

            if is_under and under_count >= MAX_UNDERS_IN_TOP and not is_elite_under:
                continue

            selected_rows.append(candidate.to_dict())
            if is_under:
                under_count += 1

            if len(selected_rows) >= TOP_N_BETS:
                break

        best_bets = pd.DataFrame(selected_rows if selected_rows else [], columns=best_bets.columns)
        best_bets = best_bets[final_columns]
    else:
        best_bets = pd.DataFrame(columns=final_columns)

    best_bets.to_csv(BEST_BETS_OUTPUT_PATH, index=False)

    write_df(
        UNMATCHED_PLAYERS_PATH,
        pd.DataFrame(unmatched_players).drop_duplicates().to_dict("records") if unmatched_players else [],
        unmatched_player_columns
    )
    write_df(
        UNMATCHED_STATS_PATH,
        pd.DataFrame(unmatched_stats).drop_duplicates().to_dict("records") if unmatched_stats else [],
        unmatched_stat_columns
    )
    write_df(
        MATCH_AUDIT_PATH,
        pd.DataFrame(match_audit).drop_duplicates().to_dict("records") if match_audit else [],
        match_audit_columns
    )

    print("\nDEBUG SUMMARY")
    print(f"Projection rows: {len(projections)}")
    print(f"Lines rows: {len(lines)}")
    print(f"Matched bets before trim: {len(rows)}")
    print(f"Final top bets saved: {len(best_bets)}")
    print(f"Unmatched players: {len(unmatched_players)}")
    print(f"Unmatched stats: {len(unmatched_stats)}")

    print(f"\nSaved best bets file: {BEST_BETS_OUTPUT_PATH}")

    if not best_bets.empty:
        print("\nTop bets:")
        print(
            best_bets[
                ["PLAYER", "STAT", "BET", "LINE", "PROJECTION", "EDGE", "MODEL_CONFIDENCE"]
            ].to_string(index=False)
        )
    else:
        print("\nNo matched bets found.")


if __name__ == "__main__":
    build_best_bets()
