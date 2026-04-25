import os
from datetime import datetime

import joblib
import numpy as np
import pandas as pd

from nba_model.common import build_projection_app_view, clean_name, find_player_col, normalize_stat_name
from nba_model.settings import (
    BASE_DIR,
    GAME_LINES_PATH,
    INJURY_CSV_PATH,
    INJURY_TXT_PATH,
    LINES_PATH,
    PROJECTIONS_APP_VIEW_PATH,
    PROJECTIONS_PATH,
    RAW_GAMES_PATH,
    ROTATION_TEMPLATES_PATH,
    TEAMS_TODAY_PATH,
)

SIMULATION_RUNS = 5000
MODEL_FEATURES = [
    "HOME",
    "REST_DAYS",
    "B2B",
    "LOW_MIN_ROLE",
    "VOLATILE_MINUTES",
    "PTS_LAST3",
    "PTS_LAST5",
    "PTS_LAST10",
    "REB_LAST3",
    "REB_LAST5",
    "REB_LAST10",
    "AST_LAST3",
    "AST_LAST5",
    "AST_LAST10",
    "STL_LAST3",
    "STL_LAST5",
    "STL_LAST10",
    "BLK_LAST3",
    "BLK_LAST5",
    "BLK_LAST10",
    "FG3M_LAST3",
    "FG3M_LAST5",
    "FG3M_LAST10",
    "MIN_LAST3",
    "MIN_LAST5",
    "MIN_LAST10",
    "MIN_STD5",
    "PTS_STD5",
    "REB_STD5",
    "AST_STD5",
    "PTS_TREND",
    "MIN_TREND",
    "OPP_PTS_ALLOWED",
    "OPP_REB_ALLOWED",
    "OPP_AST_ALLOWED",
]
MINUTES_FEATURES = [
    "HOME",
    "REST_DAYS",
    "B2B",
    "LOW_MIN_ROLE",
    "VOLATILE_MINUTES",
    "MIN_LAST3",
    "MIN_LAST5",
    "MIN_LAST10",
    "MIN_STD5",
    "MIN_TREND",
    "OPP_PTS_ALLOWED",
    "OPP_REB_ALLOWED",
    "OPP_AST_ALLOWED",
]
STAT_TARGETS = ["PTS", "REB", "AST", "STL", "BLK", "FG3M"]
COMBO_TARGETS = {
    "PRA": ["PTS", "REB", "AST"],
    "PR": ["PTS", "REB"],
    "PA": ["PTS", "AST"],
    "RA": ["REB", "AST"],
    "SB": ["STL", "BLK"],
}
SUPPLEMENTAL_STATS = ["TOV", "FANTASY", "FTM", "FTA", "FGM", "FGA", "FG2M", "FG2A", "FG3A", "OREB", "DREB", "PF", "DD", "TD"]
RECENT_WEIGHTS = {
    "PTS": (0.55, 0.30, 0.15),
    "REB": (0.50, 0.32, 0.18),
    "AST": (0.52, 0.30, 0.18),
    "STL": (0.45, 0.35, 0.20),
    "BLK": (0.45, 0.35, 0.20),
    "FG3M": (0.50, 0.32, 0.18),
}
STATUS_AVAILABILITY = {
    "ACTIVE": 1.00,
    "PROBABLE": 0.96,
    "QUESTIONABLE": 0.78,
    "DOUBTFUL": 0.30,
    "OUT": 0.00,
    "UNKNOWN": 0.94,
}
STATUS_MINUTES_MULTIPLIER = {
    "ACTIVE": 1.00,
    "PROBABLE": 0.99,
    "QUESTIONABLE": 0.92,
    "DOUBTFUL": 0.72,
    "OUT": 0.00,
    "UNKNOWN": 0.98,
}
USAGE_COEFFICIENT = {
    "PTS": 0.12,
    "REB": 0.08,
    "AST": 0.11,
    "STL": 0.06,
    "BLK": 0.06,
    "FG3M": 0.10,
}
INJURY_IMPACT_WEIGHT = {
    "OUT": 1.00,
    "DOUBTFUL": 0.70,
    "QUESTIONABLE": 0.30,
    "PROBABLE": 0.12,
}
ROLE_KEYS = ["SCORER", "PLAYMAKER", "REBOUNDER", "RIM", "SHOOTER"]
HOME_COURT_EDGE = 2.3
DEFAULT_MARGIN_STD = 12.0
BLOWOUT_THRESHOLD = 18.0
PLAYOFF_COMPETITIVE_ABS_MARGIN = 8.0
PLAYOFF_BLOWOUT_MARGIN = BLOWOUT_THRESHOLD + 5.0
PLAYOFF_BLOWOUT_PENALTY_SCALE = 0.48
# Pull Phase 7 lineup/matchup multipliers toward 1.0 to limit stacking with stat/shot concentration.
PLAYOFF_LINEUP_MATCHUP_DAMP = 0.72
# Soft audit thresholds (warnings only; do not alter projections).
PLAYOFF_GUARD_IMPLIED_PTS_MAX_RATIO = 1.20
PLAYOFF_GUARD_IMPLIED_PTS_MIN_RATIO = 0.80
PLAYOFF_GUARD_FRINGE_PTS_PER_MIN = 1.10
PLAYOFF_GUARD_ENGINE_PTS_PER_MIN = 1.36
PLAYOFF_GUARD_FRINGE_MINUTES = 22.0
PLAYOFF_GUARD_TEAM_AST_SUM = 38.0
PLAYOFF_GUARD_TEAM_REB_SUM = 58.0
OT_MINUTE_CAP_FOR_FEATURES = 46.0
MARKET_SPREAD_BLEND = 0.72
MARKET_TOTAL_BLEND = 0.55
TEAM_TOTAL_BLEND = 0.65
MIN_EXPECTED_SLATE_TEAMS = 4
PUBLISHED_TEAM_MINUTE_TARGET = 246.0
PUBLISHED_MIN_TEAM_PLAYERS = 8
TEAM_REGULATION_MINUTES = 240.0

# Strict playoff minute pipeline debug trace targets
_TRACE_KEYS = {
    "daniss jenkins",
    "jalen williams",
    "franz wagner",
    "shai gilgeous alexander",
    "paolo banchero",
    "cade cunningham",
}


def normalize_injury_status(status):
    s = str(status).strip().upper()

    if s in {"OUT", "O", "INACTIVE", "SUSPENDED", "DNP", "IR"}:
        return "OUT"
    if "OUT" in s or "INACTIVE" in s or "SUSPENDED" in s:
        return "OUT"
    if s in {"DOUBTFUL", "D"} or "DOUBTFUL" in s:
        return "DOUBTFUL"
    if s in {"QUESTIONABLE", "Q"} or "QUESTIONABLE" in s:
        return "QUESTIONABLE"
    if s in {"PROBABLE", "P"} or "PROBABLE" in s:
        return "PROBABLE"
    if "GTD" in s or "GAME TIME DECISION" in s or "GAMETIME DECISION" in s:
        return "QUESTIONABLE"
    if s in {"AVAILABLE", "ACTIVE", "HEALTHY"}:
        return "ACTIVE"
    if s == "" or s == "NAN" or s == "NONE":
        return "UNKNOWN"

    return s


def is_combo_player_name(name):
    s = str(name)
    return " + " in s or "&" in s or "/" in s


def current_projection_date():
    return datetime.now().strftime("%Y-%m-%d")


def matchup_key(team, opponent):
    return " vs ".join(sorted([str(team).strip().upper(), str(opponent).strip().upper()]))


def load_lines_df():
    if not os.path.exists(LINES_PATH):
        raise FileNotFoundError(f"Missing lines file: {LINES_PATH}")

    df = pd.read_csv(LINES_PATH)
    if df.empty:
        raise ValueError("lines_today.csv is empty")

    df.columns = [str(c).strip().upper() for c in df.columns]
    player_col = find_player_col(df)

    if "STAT" not in df.columns:
        for alt in ["MARKET", "PROP"]:
            if alt in df.columns:
                df["STAT"] = df[alt]
                break

    if "LINE" not in df.columns:
        for alt in ["SPORTSBOOK_LINE"]:
            if alt in df.columns:
                df["LINE"] = df[alt]
                break

    if "STAT" not in df.columns or "LINE" not in df.columns:
        raise ValueError(f"lines_today.csv missing STAT or LINE columns. Found: {list(df.columns)}")

    if "TEAM" not in df.columns:
        df["TEAM"] = ""

    df["PLAYER_NAME"] = df[player_col].astype(str).str.strip()
    df["PLAYER_KEY"] = df["PLAYER_NAME"].map(clean_name)
    df["STAT_KEY"] = df["STAT"].map(normalize_stat_name)
    df["LINE"] = pd.to_numeric(df["LINE"], errors="coerce")
    return df


def load_injuries():
    injuries = {}

    csv_paths = [INJURY_CSV_PATH]
    txt_paths = [INJURY_TXT_PATH]

    for csv_path in csv_paths:
        if not os.path.exists(csv_path):
            continue
        try:
            df = pd.read_csv(csv_path)
            if not df.empty:
                df.columns = [str(c).strip().upper() for c in df.columns]

                name_col = None
                status_col = None

                for col in ["PLAYER_NAME", "PLAYER", "NAME"]:
                    if col in df.columns:
                        name_col = col
                        break

                for col in ["STATUS", "INJURY_STATUS", "REPORT_STATUS"]:
                    if col in df.columns:
                        status_col = col
                        break

                if name_col:
                    for _, row in df.iterrows():
                        name_key = clean_name(row[name_col])
                        if not name_key:
                            continue
                        raw_status = row[status_col] if status_col else "OUT"
                        injuries[name_key] = normalize_injury_status(raw_status)
        except Exception as exc:
            print(f"WARNING: Could not read injury csv {csv_path}: {exc}")

    for txt_path in txt_paths:
        if not os.path.exists(txt_path):
            continue
        try:
            with open(txt_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    raw = line.strip()
                    if not raw:
                        continue

                    if "|" in raw:
                        parts = [p.strip() for p in raw.split("|")]
                    elif "," in raw:
                        parts = [p.strip() for p in raw.split(",")]
                    else:
                        parts = [raw, "OUT"]

                    name = parts[0]
                    status = parts[1] if len(parts) > 1 else "OUT"
                    injuries[clean_name(name)] = normalize_injury_status(status)
        except Exception as exc:
            print(f"WARNING: Could not read injury txt {txt_path}: {exc}")

    return injuries


def _parse_starter_name_keys_cell(raw):
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    s = str(raw).strip()
    if not s or s.upper() in {"NAN", "NONE", ""}:
        return []
    parts = []
    for sep in ["|", ";"]:
        if sep in s:
            parts = [p.strip() for p in s.split(sep) if p.strip()]
            break
    if not parts and "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip()]
    if not parts:
        parts = [s]
    keys = []
    for p in parts:
        k = clean_name(p)
        if k:
            keys.append(k)
    return keys


def load_matchups():
    if not os.path.exists(TEAMS_TODAY_PATH):
        return {}

    try:
        df = pd.read_csv(TEAMS_TODAY_PATH)
        if df.empty or "TEAM_ABBREVIATION" not in df.columns:
            return {}
        df.columns = [str(c).strip().upper() for c in df.columns]
        starter_col = None
        for col in ["ANNOUNCED_STARTERS", "CONFIRMED_STARTERS", "PROJECTED_STARTERS", "STARTERS"]:
            if col in df.columns:
                starter_col = col
                break
        matchups = {}
        for _, row in df.iterrows():
            team = str(row.get("TEAM_ABBREVIATION", "")).strip().upper()
            if not team:
                continue
            phase = ""
            if "SEASON_PHASE" in df.columns:
                phase = str(row.get("SEASON_PHASE", "")).strip().upper()
            elim = ""
            if "ELIMINATION_TEAM" in df.columns:
                elim = str(row.get("ELIMINATION_TEAM", "")).strip().upper()
            leverage = 0.0
            if "MUST_WIN_LEVERAGE" in df.columns:
                leverage = float(pd.to_numeric(row.get("MUST_WIN_LEVERAGE"), errors="coerce") or 0.0)
            announced = set()
            if starter_col:
                announced = set(_parse_starter_name_keys_cell(row.get(starter_col)))
            matchups[team] = {
                "OPPONENT": str(row.get("OPPONENT", "")).strip().upper(),
                "MATCHUP": str(row.get("MATCHUP", "")).strip(),
                "SEASON_PHASE": phase,
                "ELIMINATION_TEAM": elim,
                "MUST_WIN_LEVERAGE": float(np.clip(leverage, 0.0, 1.0)),
                "ANNOUNCED_STARTER_KEYS": announced,
            }
        return matchups
    except Exception as exc:
        print(f"WARNING: Could not read teams_today.csv: {exc}")
        return {}


def playoff_slate_active(matchups):
    flag = os.environ.get("EDGERANKED_NBA_PLAYOFFS", "").strip().lower()
    if flag in {"1", "true", "yes", "y"}:
        return True
    for info in matchups.values():
        phase = str(info.get("SEASON_PHASE", "")).strip().upper()
        if phase in {"PLAYOFF", "PLAYOFFS", "POST", "POSTSEASON"}:
            return True
    return False


def load_today_slate_teams():
    if not os.path.exists(TEAMS_TODAY_PATH):
        return set()

    try:
        df = pd.read_csv(TEAMS_TODAY_PATH)
    except Exception as exc:
        print(f"WARNING: Could not read teams_today.csv for slate filter: {exc}")
        return set()

    if df.empty:
        return set()

    df.columns = [str(c).strip().upper() for c in df.columns]
    team_col = "TEAM_ABBREVIATION" if "TEAM_ABBREVIATION" in df.columns else None
    if not team_col and "TEAM" in df.columns:
        team_col = "TEAM"
    if not team_col:
        return set()

    teams = {
        str(team).strip().upper()
        for team in df[team_col].dropna().tolist()
        if str(team).strip()
    }
    if len(teams) < MIN_EXPECTED_SLATE_TEAMS:
        print(
            f"WARNING: teams_today.csv only has {len(teams)} teams. "
            "Ignoring slate-team filter for this projection run."
        )
        return set()
    return teams


def load_authoritative_slate_teams_enforcement():
    """
    Teams on today's slate from teams_today.csv only — no MIN_EXPECTED_SLATE_TEAMS
    skip. Use this for hard output filtering so a small (e.g. 4-team) playoff slate
    is still fully enforced; the legacy load_today_slate_teams() may return empty.
    """
    if not os.path.exists(TEAMS_TODAY_PATH):
        return set()
    try:
        df = pd.read_csv(TEAMS_TODAY_PATH)
    except Exception as exc:
        print(f"WARNING: Could not read teams_today.csv (authoritative enforcement): {exc}")
        return set()
    if df.empty:
        return set()
    df.columns = [str(c).strip().upper() for c in df.columns]
    team_col = "TEAM_ABBREVIATION" if "TEAM_ABBREVIATION" in df.columns else None
    if not team_col and "TEAM" in df.columns:
        team_col = "TEAM"
    if not team_col:
        return set()
    teams = {
        str(t).strip().upper()
        for t in df[team_col].dropna().tolist()
        if str(t).strip()
    }
    return teams


def authoritative_team_by_player_key(logs_df):
    """Current team = TEAM on most recent box score row per PLAYER_KEY in raw_games."""
    if logs_df is None or logs_df.empty:
        return {}
    w = (
        logs_df.sort_values("GAME_DATE", ascending=False)
        .dropna(subset=["PLAYER_KEY", "TEAM_ABBREVIATION"])
        .copy()
    )
    w["PLAYER_KEY"] = w["PLAYER_KEY"].astype(str).str.strip()
    latest = w.drop_duplicates(subset=["PLAYER_KEY"], keep="first")
    return {
        str(r["PLAYER_KEY"]).strip(): str(r["TEAM_ABBREVIATION"]).strip().upper()
        for _, r in latest.iterrows()
    }


def apply_final_slate_universe_enforcement(
    unique_players,
    logs_df,
    enforcement_slate,
    line_universe,
):
    """
    Drop any player whose current team in game logs is not on today's teams_today
    slate. lines_today TEAM is not trusted for inclusion — only for HAS_PROP_LINE
    downstream. Overwrites row TEAM with the authoritative log team for survivors.
    """
    if not enforcement_slate or unique_players is None or unique_players.empty:
        return unique_players, {}
    key_team = authoritative_team_by_player_key(logs_df)
    if line_universe is not None and not line_universe.empty and "PLAYER_KEY" in line_universe.columns:
        lu = line_universe.copy()
        lu["PLAYER_KEY"] = lu["PLAYER_KEY"].astype(str).str.strip()
        line_key_team = (
            lu.drop_duplicates(subset=["PLAYER_KEY"], keep="first")
            .set_index("PLAYER_KEY")["TEAM"]
            .astype(str)
            .str.strip()
            .str.upper()
            .to_dict()
        )
    else:
        line_key_team = {}

    before = len(unique_players)
    rows_keep = []
    off_slate = []
    unresolved = []
    line_mismatches = []

    for _, row in unique_players.iterrows():
        pk = str(row.get("PLAYER_KEY", "")).strip()
        if not pk:
            unresolved.append(("(empty PLAYER_KEY)", "missing_key"))
            continue
        auth = key_team.get(pk) or key_team.get(pk.strip())
        if not auth or str(auth).strip() == "" or str(auth).upper() in {"NAN", "NONE"}:
            name = str(row.get("PLAYER_NAME", "")).strip()
            unresolved.append((name, pk))
            continue
        auth = str(auth).strip().upper()
        if auth not in enforcement_slate:
            name = str(row.get("PLAYER_NAME", "")).strip()
            off_slate.append((name, pk, auth))
            continue
        if pk in line_key_team:
            lt = str(line_key_team.get(pk) or "").strip().upper()
            if lt and lt != auth:
                name = str(row.get("PLAYER_NAME", "")).strip()
                line_mismatches.append((name, pk, lt, auth))
        r = row.to_dict()
        r["TEAM"] = auth
        rows_keep.append(r)

    out = pd.DataFrame(rows_keep)
    if "PLAYER_KEY" in out.columns and not out.empty:
        out["PLAYER_KEY"] = out["PLAYER_KEY"].astype(str).str.strip()
    meta = {
        "before": before,
        "after": len(out),
        "dropped_off_slate": off_slate,
        "dropped_unresolved": unresolved,
        "line_team_not_authoritative": line_mismatches,
    }
    return out, meta


def log_final_slate_enforcement_report(meta, enforcement_slate):
    print("\n=== Final slate enforcement (authoritative log team vs teams_today) ===")
    print(f"Authoritative slate teams: {sorted(enforcement_slate)}")
    print(
        f"Projection universe row count: {meta.get('before', 0)} -> {meta.get('after', 0)} "
        "(pre-run filter: keep only PLAYER_KEY with log TEAM on today's slate; rows use log TEAM as TEAM column)"
    )
    if meta.get("dropped_unresolved"):
        print(
            f"Players dropped (no confident current team in raw_games for PLAYER_KEY; {len(meta['dropped_unresolved'])}):"
        )
        for item in meta["dropped_unresolved"][:40]:
            print(f"  - {item[0]}  key={item[1]}  (unresolved current team from raw_games)")
        if len(meta["dropped_unresolved"]) > 40:
            print(f"  ... and {len(meta['dropped_unresolved']) - 40} more")
    if meta.get("dropped_off_slate"):
        print(
            f"Players dropped (authoritative log team not on teams_today slate; {len(meta['dropped_off_slate'])}):"
        )
        for item in meta["dropped_off_slate"][:40]:
            print(f"  - {item[0]}  {item[2]}  (not in slate; key={item[1]})")
        if len(meta["dropped_off_slate"]) > 40:
            print(f"  ... and {len(meta['dropped_off_slate']) - 40} more")
    if meta.get("line_team_not_authoritative"):
        print(
            f"Line file TEAM != authoritative log team (kept; lines are eligibility signals only, not team truth; {len(meta['line_team_not_authoritative'])}):"
        )
        for item in meta["line_team_not_authoritative"][:25]:
            print(f"  - {item[0]}  line={item[2]}  logs={item[3]}  key={item[1]}")
        if len(meta["line_team_not_authoritative"]) > 25:
            print(f"  ... and {len(meta['line_team_not_authoritative']) - 25} more")
    print("=== End final slate enforcement ===\n")
    return meta


def filter_projections_dataframe_to_slate_enforcement(
    projections,
    enforcement_slate,
    label="projections",
):
    if projections is None or projections.empty or not enforcement_slate:
        return projections, 0
    if "TEAM_ABBREVIATION" not in projections.columns:
        return projections, 0
    tcol = projections["TEAM_ABBREVIATION"].astype(str).str.strip().str.upper()
    m = tcol.isin(set(enforcement_slate))
    dropped = int((~m).sum())
    if dropped:
        print(
            f"Final {label} hard filter: dropped {dropped} row(s) with TEAM_ABBREVIATION not in authoritative slate {sorted(enforcement_slate)}."
        )
    return projections[m].copy().reset_index(drop=True), dropped


def load_market_game_lines(matchups=None):
    if not os.path.exists(GAME_LINES_PATH):
        return {}

    try:
        df = pd.read_csv(GAME_LINES_PATH)
    except Exception as exc:
        print(f"WARNING: Could not read game_lines_today.csv: {exc}")
        return {}

    if df.empty:
        return {}

    required = {"HOME_TEAM", "AWAY_TEAM"}
    if not required.issubset(df.columns):
        print("WARNING: game_lines_today.csv is missing HOME_TEAM/AWAY_TEAM columns.")
        return {}

    slate_keys = set()
    if matchups:
        for team, info in matchups.items():
            opponent = str(info.get("OPPONENT", "")).strip().upper()
            if opponent:
                slate_keys.add(matchup_key(team, opponent))

    lookup = {}
    for _, row in df.iterrows():
        home_team = str(row.get("HOME_TEAM", "")).strip().upper()
        away_team = str(row.get("AWAY_TEAM", "")).strip().upper()
        if not home_team or not away_team:
            continue
        key = matchup_key(home_team, away_team)
        lookup[key] = {
            "HOME_TEAM": home_team,
            "AWAY_TEAM": away_team,
            "HOME_SPREAD": pd.to_numeric(row.get("HOME_SPREAD"), errors="coerce"),
            "AWAY_SPREAD": pd.to_numeric(row.get("AWAY_SPREAD"), errors="coerce"),
            "TOTAL": pd.to_numeric(row.get("TOTAL"), errors="coerce"),
            "HOME_MONEYLINE": pd.to_numeric(row.get("HOME_MONEYLINE"), errors="coerce"),
            "AWAY_MONEYLINE": pd.to_numeric(row.get("AWAY_MONEYLINE"), errors="coerce"),
        }
    if slate_keys:
        matched = {k: v for k, v in lookup.items() if k in slate_keys}
        missing = sorted(slate_keys - set(matched.keys()))
        stale_extra = sorted(set(lookup.keys()) - slate_keys)
        if missing:
            print(
                "WARNING: game_lines_today.csv does not match all current slate games; "
                f"missing={missing}. Conservative baseline guardrails will be used where market totals are unavailable."
            )
        if stale_extra and not matched:
            print(
                "WARNING: game_lines_today.csv appears stale or mismatched for this slate; "
                f"loaded_games={stale_extra}. Ignoring market lines for guardrails."
            )
        return matched
    return lookup


def load_rotation_templates(logs_df):
    if not os.path.exists(ROTATION_TEMPLATES_PATH):
        return {}

    try:
        df = pd.read_csv(ROTATION_TEMPLATES_PATH)
    except Exception as exc:
        print(f"WARNING: Could not read rotation_templates.csv: {exc}")
        return {}

    if df.empty or "PLAYER_ID" not in df.columns or "TEAM_ABBREVIATION" not in df.columns:
        return {}

    latest_rows = (
        logs_df.drop_duplicates(subset=["PLAYER_KEY"], keep="first")[["PLAYER_KEY", "PLAYER_ID", "TEAM_ABBREVIATION"]]
        .copy()
    )
    latest_rows["PLAYER_ID"] = latest_rows["PLAYER_ID"].astype(str).str.replace(r"\.0$", "", regex=True)
    latest_rows["TEAM_ABBREVIATION"] = latest_rows["TEAM_ABBREVIATION"].astype(str).str.strip().str.upper()

    df["PLAYER_ID"] = df["PLAYER_ID"].astype(str).str.replace(r"\.0$", "", regex=True)
    df["TEAM_ABBREVIATION"] = df["TEAM_ABBREVIATION"].astype(str).str.strip().str.upper()
    merged = df.merge(latest_rows, on=["TEAM_ABBREVIATION", "PLAYER_ID"], how="inner")
    if merged.empty:
        return {}

    templates = {}
    for _, row in merged.iterrows():
        q1 = float(pd.to_numeric(row.get("Q1_MINUTES"), errors="coerce") or 0.0)
        q2 = float(pd.to_numeric(row.get("Q2_MINUTES"), errors="coerce") or 0.0)
        q3 = float(pd.to_numeric(row.get("Q3_MINUTES"), errors="coerce") or 0.0)
        q4 = float(pd.to_numeric(row.get("Q4_MINUTES"), errors="coerce") or 0.0)
        total_minutes = float(pd.to_numeric(row.get("AVG_MINUTES_TOTAL"), errors="coerce") or 0.0)
        games_in_sample = float(pd.to_numeric(row.get("GAMES_IN_SAMPLE"), errors="coerce") or 0.0)
        quarter_total = max(q1 + q2 + q3 + q4, 1e-6)
        avg_quarter = max(quarter_total / 4.0, 1e-6)
        sample_weight = float(np.clip(games_in_sample / 5.0, 0.0, 1.0))

        starter_signal = float(np.clip((((q1 + q3) / max(2.0 * avg_quarter, 1e-6)) - 0.95) / 0.35, 0.0, 1.0))
        closer_signal = float(np.clip(((q4 / avg_quarter) - 0.95) / 0.40, 0.0, 1.0))
        second_unit_signal = float(np.clip((((q2 - q1) + (q2 - q3)) / max(avg_quarter, 1e-6)) / 1.2, 0.0, 1.0))
        garbage_signal = float(np.clip((18.0 - total_minutes) / 10.0, 0.0, 1.0) * np.clip(((q4 / avg_quarter) - 1.05) / 0.45, 0.0, 1.0))

        templates[row["PLAYER_KEY"]] = {
            "TEMPLATE_MINUTES": total_minutes,
            "TEMPLATE_GAMES": games_in_sample,
            "TEMPLATE_SAMPLE_WEIGHT": sample_weight,
            "TEMPLATE_Q1_SHARE": q1 / quarter_total,
            "TEMPLATE_Q2_SHARE": q2 / quarter_total,
            "TEMPLATE_Q3_SHARE": q3 / quarter_total,
            "TEMPLATE_Q4_SHARE": q4 / quarter_total,
            "TEMPLATE_STARTER": starter_signal,
            "TEMPLATE_CLOSER": closer_signal,
            "TEMPLATE_SECOND_UNIT": second_unit_signal,
            "TEMPLATE_GARBAGE_UNIT": garbage_signal,
        }

    return templates


def build_team_strength_ratings(logs_df, league_pace):
    team_games = (
        logs_df.groupby(["GAME_ID", "TEAM_ABBREVIATION", "OPP_TEAM_ABBREVIATION"], as_index=False)
        .agg(
            TEAM_POINTS=("PTS", "sum"),
            TEAM_PACE=("TEAM_POSS_PROXY", "mean"),
            HOME=("HOME", "max"),
        )
    )

    opponent_games = team_games.rename(
        columns={
            "TEAM_ABBREVIATION": "OPP_TEAM_ABBREVIATION",
            "OPP_TEAM_ABBREVIATION": "TEAM_ABBREVIATION",
            "TEAM_POINTS": "OPP_POINTS",
            "TEAM_PACE": "OPP_PACE",
            "HOME": "OPP_HOME",
        }
    )
    team_games = team_games.merge(
        opponent_games[["GAME_ID", "TEAM_ABBREVIATION", "OPP_POINTS", "OPP_PACE", "OPP_HOME"]],
        on=["GAME_ID", "TEAM_ABBREVIATION"],
        how="left",
    )

    team_games["MARGIN"] = team_games["TEAM_POINTS"] - team_games["OPP_POINTS"]
    team_games["GAME_TOTAL"] = team_games["TEAM_POINTS"] + team_games["OPP_POINTS"]
    team_games["PACE_ENV"] = (team_games["TEAM_PACE"] + team_games["OPP_PACE"]) / 2.0
    team_games["WIN"] = (team_games["MARGIN"] > 0).astype(float)

    strength = (
        team_games.groupby("TEAM_ABBREVIATION")
        .agg(
            AVG_MARGIN=("MARGIN", "mean"),
            MARGIN_STD=("MARGIN", "std"),
            WIN_RATE=("WIN", "mean"),
            AVG_PACE_ENV=("PACE_ENV", "mean"),
            AVG_POINTS_FOR=("TEAM_POINTS", "mean"),
            AVG_POINTS_AGAINST=("OPP_POINTS", "mean"),
        )
        .fillna(
            {
                "AVG_MARGIN": 0.0,
                "MARGIN_STD": DEFAULT_MARGIN_STD,
                "WIN_RATE": 0.5,
                "AVG_PACE_ENV": league_pace,
                "AVG_POINTS_FOR": 0.0,
                "AVG_POINTS_AGAINST": 0.0,
            }
        )
    )

    strength["NET_RATING_PROXY"] = strength["AVG_MARGIN"]
    strength["TEAM_QUALITY"] = (
        (0.75 * strength["NET_RATING_PROXY"])
        + (8.0 * (strength["WIN_RATE"] - 0.5))
    )
    league_game_total = float(team_games.drop_duplicates(subset=["GAME_ID"])["GAME_TOTAL"].mean())
    return strength, league_game_total


def load_historical_games():
    if not os.path.exists(RAW_GAMES_PATH):
        raise FileNotFoundError(f"Missing raw games file: {RAW_GAMES_PATH}")

    df = pd.read_csv(RAW_GAMES_PATH)
    if df.empty:
        raise ValueError("raw_games.csv is empty")

    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], errors="coerce")
    df = df.dropna(subset=["GAME_DATE", "PLAYER_ID"]).copy()

    num_cols = ["PTS", "REB", "AST", "STL", "BLK", "FG3M", "MIN", "TOV", "FGM", "FGA", "FG3A", "FTM", "FTA", "OREB", "DREB", "PF"]
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df["FG2M"] = (df["FGM"] - df["FG3M"]).clip(lower=0.0)
    df["FG2A"] = (df["FGA"] - df["FG3A"]).clip(lower=0.0)

    df["PLAYER_NAME"] = df["PLAYER_NAME"].astype(str)
    df["PLAYER_KEY"] = df["PLAYER_NAME"].map(clean_name)
    df["TEAM_ABBREVIATION"] = df["TEAM_ABBREVIATION"].astype(str).str.upper()
    df["MATCHUP"] = df["MATCHUP"].astype(str)
    df["HOME"] = df["MATCHUP"].str.contains("vs.", regex=False).astype(int)
    df["OPP_TEAM_ABBREVIATION"] = df["MATCHUP"].str.split().str[-1].str.upper()
    df["TEAM_POSS_PROXY"] = df["FGA"] + (0.44 * df["FTA"]) - df["OREB"] + df["TOV"]
    
    if "SEASON_TYPE" not in df.columns:
        df["SEASON_TYPE"] = "Regular Season"
        # Infer from GAME_ID: 004=Playoffs, 005=PlayIn
        game_id_str = df["GAME_ID"].astype(str)
        df.loc[game_id_str.str.startswith("004"), "SEASON_TYPE"] = "Playoffs"
        df.loc[game_id_str.str.startswith("005"), "SEASON_TYPE"] = "PlayIn"
        
    df = df.sort_values(["PLAYER_KEY", "GAME_DATE"], ascending=[True, False]).copy()

    opponent_defense = (
        df.groupby("OPP_TEAM_ABBREVIATION")[["PTS", "REB", "AST"]]
        .mean()
        .rename(
            columns={
                "PTS": "OPP_PTS_ALLOWED",
                "REB": "OPP_REB_ALLOWED",
                "AST": "OPP_AST_ALLOWED",
            }
        )
    )

    league_defaults = {
        "OPP_PTS_ALLOWED": float(df["PTS"].mean()),
        "OPP_REB_ALLOWED": float(df["REB"].mean()),
        "OPP_AST_ALLOWED": float(df["AST"].mean()),
    }
    team_pace = df.groupby("TEAM_ABBREVIATION")["TEAM_POSS_PROXY"].mean()
    league_pace = float(df["TEAM_POSS_PROXY"].mean())
    team_strength, league_game_total = build_team_strength_ratings(df, league_pace)
    return df, opponent_defense, league_defaults, team_pace, league_pace, team_strength, league_game_total


def load_models():
    models = {}
    for target in STAT_TARGETS + ["MIN"]:
        path = os.path.join(BASE_DIR, f"{target}_model.pkl")
        if os.path.exists(path):
            try:
                models[target] = joblib.load(path)
            except Exception as exc:
                print(f"WARNING: Could not load {path}: {exc}")
    return models


def safe_mean(series):
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return 0.0
    return float(numeric.mean())


def safe_std(series):
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if len(numeric) <= 1:
        return 0.0
    return float(numeric.std(ddof=1))


def rolling_mean(frame, col, n):
    return safe_mean(frame.head(n)[col])


def rolling_mean_minutes_capped(player_logs, n, cap=OT_MINUTE_CAP_FOR_FEATURES):
    sub = player_logs.head(n)
    if sub.empty or "MIN" not in sub.columns:
        return 0.0
    vals = pd.to_numeric(sub["MIN"], errors="coerce").fillna(0.0).clip(upper=cap)
    return float(vals.mean()) if len(vals) else 0.0


def rolling_std(frame, col, n):
    return safe_std(frame.head(n)[col])


def weighted_recent_mean(recent5, recent10, col, w5=0.55, w10=0.45):
    return (w5 * rolling_mean(recent5, col, 5)) + (w10 * rolling_mean(recent10, col, 10))


def safe_divide(a, b):
    return float(a) / float(b) if b else 0.0


def compute_recent_game_role_proxies(logs_df, lookback_games=12):
    if logs_df is None or logs_df.empty:
        return {}, {}
    df = logs_df
    top5_by_game = {}
    for (gid, team), grp in df.groupby(["GAME_ID", "TEAM_ABBREVIATION"]):
        if grp.empty:
            continue
        top5 = set(grp.nlargest(5, "MIN")["PLAYER_KEY"].astype(str).str.strip().tolist())
        top5_by_game[(gid, team)] = top5

    rates_start = {}
    rates_heavy = {}
    for pk in df["PLAYER_KEY"].dropna().unique():
        pk = str(pk).strip()
        px = df[df["PLAYER_KEY"].astype(str).str.strip() == pk].sort_values("GAME_DATE", ascending=False).head(lookback_games)
        if px.empty:
            rates_start[pk] = 0.0
            rates_heavy[pk] = 0.0
            continue
        hits = 0
        gcount = 0
        for _, row in px.iterrows():
            gid = row["GAME_ID"]
            team = row["TEAM_ABBREVIATION"]
            if pk in top5_by_game.get((gid, team), set()):
                hits += 1
            gcount += 1
        rates_start[pk] = hits / max(gcount, 1)
        mvals = pd.to_numeric(px["MIN"], errors="coerce")
        rates_heavy[pk] = float((mvals >= 26.0).sum()) / max(len(px), 1)
    return rates_start, rates_heavy


def build_player_features(player_logs, team, opponent, opponent_defense, league_defaults, team_pace, league_pace, playoff_mode=False):
    recent10 = player_logs.head(10).copy()
    recent5 = player_logs.head(5).copy()
    recent3 = player_logs.head(3).copy()

    last_game = recent10.iloc[0]
    prev_game_date = recent10.iloc[1]["GAME_DATE"] if len(recent10) > 1 else pd.NaT

    today = pd.Timestamp.now().normalize()
    rest_days = (today - last_game["GAME_DATE"].normalize()).days
    if pd.notna(prev_game_date):
        previous_gap = int((last_game["GAME_DATE"].normalize() - prev_game_date.normalize()).days)
    else:
        previous_gap = max(rest_days, 2)

    min_ref5 = rolling_mean_minutes_capped(player_logs, 5) if playoff_mode else rolling_mean(recent5, "MIN", 5)
    features = {
        "HOME": 1 if "vs." in str(last_game["MATCHUP"]) else 0,
        "REST_DAYS": max(0, min(rest_days, 5)),
        "B2B": 0 if playoff_mode else (1 if previous_gap == 1 else 0),
        "LOW_MIN_ROLE": 1 if min_ref5 < 20 else 0,
        "VOLATILE_MINUTES": 1 if rolling_std(recent5, "MIN", 5) > 6 else 0,
    }

    for stat in ["PTS", "REB", "AST", "STL", "BLK", "FG3M"]:
        features[f"{stat}_LAST3"] = rolling_mean(recent3, stat, 3)
        features[f"{stat}_LAST5"] = rolling_mean(recent5, stat, 5)
        features[f"{stat}_LAST10"] = rolling_mean(recent10, stat, 10)

    if playoff_mode:
        features["MIN_LAST3"] = rolling_mean_minutes_capped(player_logs, 3)
        features["MIN_LAST5"] = rolling_mean_minutes_capped(player_logs, 5)
        features["MIN_LAST10"] = rolling_mean_minutes_capped(player_logs, 10)
    else:
        features["MIN_LAST3"] = rolling_mean(recent3, "MIN", 3)
        features["MIN_LAST5"] = rolling_mean(recent5, "MIN", 5)
        features["MIN_LAST10"] = rolling_mean(recent10, "MIN", 10)

    features["MIN_STD5"] = rolling_std(recent5, "MIN", 5)
    features["PTS_STD5"] = rolling_std(recent5, "PTS", 5)
    features["REB_STD5"] = rolling_std(recent5, "REB", 5)
    features["AST_STD5"] = rolling_std(recent5, "AST", 5)
    features["PTS_TREND"] = features["PTS_LAST3"] - features["PTS_LAST10"]
    features["MIN_TREND"] = features["MIN_LAST3"] - features["MIN_LAST10"]

    defense = opponent_defense.loc[opponent].to_dict() if opponent in opponent_defense.index else league_defaults
    features["OPP_PTS_ALLOWED"] = float(defense["OPP_PTS_ALLOWED"])
    features["OPP_REB_ALLOWED"] = float(defense["OPP_REB_ALLOWED"])
    features["OPP_AST_ALLOWED"] = float(defense["OPP_AST_ALLOWED"])
    features["TEAM_PACE"] = float(team_pace.get(team, league_pace))
    features["OPP_PACE"] = float(team_pace.get(opponent, league_pace))
    features["EXPECTED_PACE"] = (features["TEAM_PACE"] + features["OPP_PACE"]) / 2.0

    return features


def enrich_lineup_signals_for_all_teams(profiles, team_rosters, rotation_templates=None, matchups=None):
    for team, roster in team_rosters.items():
        keys = [pk for pk, _ in roster]
        announced = set()
        if matchups and team in matchups:
            announced = set(matchups[team].get("ANNOUNCED_STARTER_KEYS") or [])
        if len(keys) < 2:
            for pk in keys:
                pr = profiles[pk]
                pr.setdefault("OPEN_LINEUP_SCORE", 0.5)
                pr.setdefault("CLOSE_LINEUP_SCORE", 0.5)
                pr.setdefault("LIKELY_STARTER", float(pr.get("STARTER", 0.0) >= 0.5))
                pr.setdefault("LIKELY_CLOSER", float(pr.get("CLOSER", 0.0) >= 0.5))
                pr.setdefault("FAKE_STARTER_RISK", 0.0)
                pr.setdefault("ROLE_STABILITY_SCORE", 0.75)
                pr["ANNOUNCED_STARTER"] = 1.0 if pk in announced else float(pr.get("ANNOUNCED_STARTER", 0.0))
            continue

        max_u = max(profiles[pk]["USAGE_LOAD"] for pk in keys) or 1.0
        max_m = max(profiles[pk]["MINUTES"] for pk in keys) or 1.0
        raw_open = {}
        raw_close = {}
        for pk in keys:
            pr = profiles[pk]
            tpl = (rotation_templates or {}).get(pk, {})
            t_q1 = float(tpl.get("TEMPLATE_Q1_SHARE", 0.25))
            t_q4 = float(tpl.get("TEMPLATE_Q4_SHARE", 0.25))
            t_st = float(tpl.get("TEMPLATE_STARTER", pr.get("STARTER", 0.0)))
            t_cl = float(tpl.get("TEMPLATE_CLOSER", pr.get("CLOSER", 0.0)))
            r_st = float(pr.get("RECENT_START_RATE", 0.0))
            r_hi = float(pr.get("RECENT_HEAVY_MIN_RATE", 0.0))
            raw_open[pk] = (
                0.30 * (pr["USAGE_LOAD"] / max_u)
                + 0.26 * (pr["MINUTES"] / max_m)
                + 0.20 * t_st
                + 0.12 * float(np.clip(t_q1 / 0.28, 0.0, 1.25))
                + 0.12 * r_st
            )
            raw_close[pk] = (
                0.32 * (pr["USAGE_LOAD"] / max_u)
                + 0.24 * (pr["MINUTES"] / max_m)
                + 0.20 * t_cl
                + 0.12 * float(np.clip(t_q4 / 0.28, 0.0, 1.25))
                + 0.12 * r_hi
            )
            if pk in announced:
                raw_open[pk] += 0.28
                raw_close[pk] += 0.06
            pr["ANNOUNCED_STARTER"] = 1.0 if pk in announced else 0.0

        max_o = max(raw_open.values()) or 1.0
        max_c = max(raw_close.values()) or 1.0
        sorted_open = sorted(keys, key=lambda k: raw_open[k], reverse=True)
        sorted_close = sorted(keys, key=lambda k: raw_close[k], reverse=True)
        top5o = set(sorted_open[:5])
        top5c = set(sorted_close[:5])

        for pk in keys:
            pr = profiles[pk]
            pr["OPEN_LINEUP_SCORE"] = float(raw_open[pk] / max_o)
            pr["CLOSE_LINEUP_SCORE"] = float(raw_close[pk] / max_c)
            t_st = float((rotation_templates or {}).get(pk, {}).get("TEMPLATE_STARTER", 0.0))
            t_cl = float((rotation_templates or {}).get(pk, {}).get("TEMPLATE_CLOSER", 0.0))
            r_st = float(pr.get("RECENT_START_RATE", 0.0))
            r_hi = float(pr.get("RECENT_HEAVY_MIN_RATE", 0.0))
            announced_starter = pk in announced
            open_confirmed = announced_starter or r_st >= 0.42 or t_st >= 0.48 or pr["OPEN_LINEUP_SCORE"] >= 0.70
            close_confirmed = r_hi >= 0.42 or t_cl >= 0.48 or pr["CLOSE_LINEUP_SCORE"] >= 0.72
            pr["LIKELY_STARTER"] = 1.0 if announced_starter else (0.72 if (pk in top5o and open_confirmed) else (0.42 if pk in top5o else 0.0))
            pr["LIKELY_CLOSER"] = 0.78 if (pk in top5c and close_confirmed) else (0.40 if pk in top5c else 0.0)
            nominal_starter = pr["MINUTE_RANK_TEAM"] <= 5
            low_min = pr["MINUTES"] < 24.0
            weak_open = pr["OPEN_LINEUP_SCORE"] < 0.42
            is_core = (pr["USAGE_RANK_TEAM"] <= 4 and pr["MINUTE_RANK_TEAM"] <= 4)
            star_proxy = (0.44 * pr.get("SCORER", 0.0) + 0.24 * pr.get("PLAYMAKER", 0.0) + 0.20 * pr.get("CORE_PLAYER", 0.0) + 0.12 * pr.get("CLOSER", 0.0))
            weak_evidence = not announced_starter and r_st < 0.35 and r_hi < 0.35 and max(t_st, t_cl) < 0.42
            pr["FAKE_STARTER_RISK"] = float(
                np.clip(
                    (0.40 if nominal_starter else 0.0)
                    + (0.38 if (nominal_starter and weak_open) else 0.0)
                    + (0.28 if (nominal_starter and low_min) else 0.0)
                    + (0.18 if (nominal_starter and weak_evidence) else 0.0)
                    - (0.60 if is_core else 0.0)
                    - (0.50 if star_proxy >= 0.60 else 0.0),
                    0.0,
                    1.0,
                )
            )
            pr["ROLE_STABILITY_SCORE"] = float(
                np.clip(
                    1.0
                    - 0.55 * pr["VOLATILITY"]
                    - 0.22 * pr["FAKE_STARTER_RISK"]
                    - (0.12 if weak_evidence else 0.0),
                    0.05,
                    1.0,
                )
            )


def build_player_archetypes(logs_df, rotation_templates=None, matchups=None):
    rates_start, rates_heavy = compute_recent_game_role_proxies(logs_df)
    latest_rows = logs_df.drop_duplicates(subset=["PLAYER_KEY"], keep="first").copy()
    latest_team = latest_rows.set_index("PLAYER_KEY")["TEAM_ABBREVIATION"].to_dict()
    profiles = {}

    for player_key in latest_rows["PLAYER_KEY"].tolist():
        player_logs = logs_df[logs_df["PLAYER_KEY"] == player_key].sort_values("GAME_DATE", ascending=False).copy()
        if player_logs.empty:
            continue

        if "SEASON_TYPE" not in player_logs.columns:
            game_id_str = player_logs["GAME_ID"].astype(str)
            player_logs["SEASON_TYPE"] = "Regular Season"
            player_logs.loc[game_id_str.str.startswith("004"), "SEASON_TYPE"] = "Playoffs"

        playoff_logs = player_logs[player_logs["SEASON_TYPE"] == "Playoffs"].copy()
        reg_logs = player_logs[player_logs["SEASON_TYPE"] != "Playoffs"].copy()
        
        has_playoffs = not playoff_logs.empty
        playoff_games = len(playoff_logs)
        
        if has_playoffs:
            # 1. Actual playoff games (highest priority)
            playoff_mins = pd.to_numeric(playoff_logs["MIN"], errors="coerce").fillna(0.0)
            mins = max(float(playoff_mins.mean()), 8.0)
            pts = float(pd.to_numeric(playoff_logs["PTS"], errors="coerce").fillna(0.0).mean())
            reb = float(pd.to_numeric(playoff_logs["REB"], errors="coerce").fillna(0.0).mean())
            ast = float(pd.to_numeric(playoff_logs["AST"], errors="coerce").fillna(0.0).mean())
            stl = float(pd.to_numeric(playoff_logs["STL"], errors="coerce").fillna(0.0).mean())
            blk = float(pd.to_numeric(playoff_logs["BLK"], errors="coerce").fillna(0.0).mean())
            fg3m = float(pd.to_numeric(playoff_logs["FG3M"], errors="coerce").fillna(0.0).mean())
            oreb = float(pd.to_numeric(playoff_logs["OREB"], errors="coerce").fillna(0.0).mean())
            dreb = float(pd.to_numeric(playoff_logs["DREB"], errors="coerce").fillna(0.0).mean())
            fga = float(pd.to_numeric(playoff_logs["FGA"], errors="coerce").fillna(0.0).mean())
            fta = float(pd.to_numeric(playoff_logs["FTA"], errors="coerce").fillna(0.0).mean())
            
            # If only 1 playoff game, blend with reg season so 1 foul-out doesn't ruin archetype
            if playoff_games == 1 and not reg_logs.empty:
                r_recent = reg_logs.head(20)
                r_mins = max(rolling_mean(r_recent, "MIN", 20), 8.0)
                mins = mins * 0.7 + r_mins * 0.3
                pts = pts * 0.7 + rolling_mean(r_recent, "PTS", 20) * 0.3
                reb = reb * 0.7 + rolling_mean(r_recent, "REB", 20) * 0.3
                ast = ast * 0.7 + rolling_mean(r_recent, "AST", 20) * 0.3
                stl = stl * 0.7 + rolling_mean(r_recent, "STL", 20) * 0.3
                blk = blk * 0.7 + rolling_mean(r_recent, "BLK", 20) * 0.3
                fg3m = fg3m * 0.7 + rolling_mean(r_recent, "FG3M", 20) * 0.3
                oreb = oreb * 0.7 + rolling_mean(r_recent, "OREB", 20) * 0.3
                dreb = dreb * 0.7 + rolling_mean(r_recent, "DREB", 20) * 0.3
                fga = fga * 0.7 + rolling_mean(r_recent, "FGA", 20) * 0.3
                fta = fta * 0.7 + rolling_mean(r_recent, "FTA", 20) * 0.3
        else:
            # Fallback: regular season hierarchy
            recent5 = reg_logs.head(5).copy()
            recent10 = reg_logs.head(10).copy()
            recent30 = reg_logs.head(30).copy()
            
            mins10 = max(weighted_recent_mean(recent5, recent10, "MIN"), 8.0)
            mins30 = rolling_mean(recent30, "MIN", 30)
            mins = mins10 * 0.55 + max(mins30, 8.0) * 0.45
    
            pts10 = weighted_recent_mean(recent5, recent10, "PTS")
            pts30 = rolling_mean(recent30, "PTS", 30)
            pts = pts10 * 0.55 + pts30 * 0.45
            
            reb10 = weighted_recent_mean(recent5, recent10, "REB")
            reb30 = rolling_mean(recent30, "REB", 30)
            reb = reb10 * 0.55 + reb30 * 0.45
            
            ast10 = weighted_recent_mean(recent5, recent10, "AST")
            ast30 = rolling_mean(recent30, "AST", 30)
            ast = ast10 * 0.55 + ast30 * 0.45
            
            stl10 = weighted_recent_mean(recent5, recent10, "STL")
            stl30 = rolling_mean(recent30, "STL", 30)
            stl = stl10 * 0.55 + stl30 * 0.45
            
            blk10 = weighted_recent_mean(recent5, recent10, "BLK")
            blk30 = rolling_mean(recent30, "BLK", 30)
            blk = blk10 * 0.55 + blk30 * 0.45
            
            fg3m10 = weighted_recent_mean(recent5, recent10, "FG3M")
            fg3m30 = rolling_mean(recent30, "FG3M", 30)
            fg3m = fg3m10 * 0.55 + fg3m30 * 0.45
            
            oreb10 = weighted_recent_mean(recent5, recent10, "OREB")
            oreb30 = rolling_mean(recent30, "OREB", 30)
            oreb = oreb10 * 0.55 + oreb30 * 0.45
            
            dreb10 = weighted_recent_mean(recent5, recent10, "DREB")
            dreb30 = rolling_mean(recent30, "DREB", 30)
            dreb = dreb10 * 0.55 + dreb30 * 0.45
            
            fga10 = weighted_recent_mean(recent5, recent10, "FGA")
            fga30 = rolling_mean(recent30, "FGA", 30)
            fga = fga10 * 0.55 + fga30 * 0.45
            
            fta10 = weighted_recent_mean(recent5, recent10, "FTA")
            fta30 = rolling_mean(recent30, "FTA", 30)
            fta = fta10 * 0.55 + fta30 * 0.45

        scoring_rate = safe_divide(pts, mins)
        assist_rate = safe_divide(ast, mins)
        rebound_rate = safe_divide(reb, mins)
        rim_rate = safe_divide(blk + (0.35 * oreb), mins)
        shooting_rate = safe_divide(fg3m + (0.20 * fga), mins)
        
        usage_load = pts + (1.35 * ast) + (0.75 * reb) + (0.20 * fga) + (0.15 * fta)
        
        playoff_starts = 0
        playoff_start_rate = 0.0
        if has_playoffs:
            # We don't have a reliable 'started' flag in simple logs usually, but we can proxy by minutes or check actual top 5 in min per game.
            # We'll calculate it across the team later or use recent_start_rate.
            pass

        profiles[player_key] = {
            "TEAM": latest_team.get(player_key, ""),
            "MINUTES": mins,
            "USAGE_LOAD": usage_load,
            "SCORER": min(1.0, (scoring_rate / 0.85) + safe_divide(fga, 18.0) * 0.35),
            "PLAYMAKER": min(1.0, (assist_rate / 0.23) + safe_divide(ast, max(pts + ast, 1.0)) * 0.25),
            "REBOUNDER": min(1.0, (rebound_rate / 0.24) + safe_divide(dreb + 1.5 * oreb, mins) * 0.30),
            "RIM": min(1.0, (rim_rate / 0.10) + safe_divide(blk, max(reb + 1.0, 1.0)) * 0.15),
            "SHOOTER": min(1.0, (shooting_rate / 0.22) + safe_divide(fg3m, max(fga, 1.0)) * 0.25),
            "POINTS_SHARE": safe_divide(pts, max(pts + ast + reb, 1.0)),
            "ASSISTS_SHARE": safe_divide(ast, max(pts + ast + reb, 1.0)),
            "REBOUNDS_SHARE": safe_divide(reb, max(pts + ast + reb, 1.0)),
            "VOLATILITY": min(1.0, rolling_std(player_logs.head(5), "MIN", 5) / 8.0),
            "RECENT_START_RATE": float(rates_start.get(str(player_key).strip(), 0.0)),
            "RECENT_HEAVY_MIN_RATE": float(rates_heavy.get(str(player_key).strip(), 0.0)),
            "ANNOUNCED_STARTER": 0.0,
            "PLAYOFF_GAMES": playoff_games,
            "PLAYOFF_MIN": mins if has_playoffs else 0.0,
            "PLAYOFF_USAGE": usage_load if has_playoffs else 0.0,
        }

    team_rosters = {}
    for player_key, profile in profiles.items():
        team = profile.get("TEAM", "")
        if not team:
            continue
        team_rosters.setdefault(team, []).append((player_key, profile))

    for team, roster in team_rosters.items():
        roster_by_minutes = sorted(roster, key=lambda item: item[1]["MINUTES"], reverse=True)
        roster_by_usage = sorted(roster, key=lambda item: item[1]["USAGE_LOAD"], reverse=True)
        minute_rank = {player_key: idx + 1 for idx, (player_key, _) in enumerate(roster_by_minutes)}
        usage_rank = {player_key: idx + 1 for idx, (player_key, _) in enumerate(roster_by_usage)}
        
        playoff_roster_by_usage = sorted(roster, key=lambda item: item[1].get("PLAYOFF_USAGE", 0.0), reverse=True)
        playoff_usage_rank = {player_key: idx + 1 for idx, (player_key, _) in enumerate(playoff_roster_by_usage)}

        closer_candidates = sorted(
            roster,
            key=lambda item: (
                (0.55 * item[1]["MINUTES"])
                + (0.30 * item[1]["USAGE_LOAD"])
                + (4.5 * item[1]["PLAYMAKER"])
                + (3.0 * item[1]["SCORER"])
            ),
            reverse=True,
        )
        starter_keys = {player_key for player_key, _ in roster_by_minutes[:5]}
        closer_keys = {player_key for player_key, _ in closer_candidates[:5]}
        second_unit_keys = {player_key for player_key, _ in roster_by_minutes[5:10]}

        for player_key, profile in roster:
            m_rank = minute_rank[player_key]
            u_rank = usage_rank[player_key]
            mins = profile["MINUTES"]

            if mins >= 31 or m_rank <= 5:
                rotation_tier = "CORE"
            elif mins >= 24 or m_rank <= 8:
                rotation_tier = "ROTATION"
            elif mins >= 16 or m_rank <= 10:
                rotation_tier = "BENCH"
            else:
                rotation_tier = "DEEP_BENCH"

            profile["MINUTE_RANK_TEAM"] = m_rank
            profile["USAGE_RANK_TEAM"] = u_rank
            profile["PLAYOFF_USAGE_RANK_TEAM"] = playoff_usage_rank.get(player_key, 99)
            profile["PLAYOFF_STARTS"] = 0  # In a real pipeline, count actual starter flags if available
            profile["PLAYOFF_START_RATE"] = 1.0 if profile["PLAYOFF_GAMES"] > 0 and m_rank <= 5 else 0.0
            profile["ROTATION_TIER"] = rotation_tier
            profile["CORE_PLAYER"] = 1.0 if rotation_tier == "CORE" else 0.0
            profile["BENCH_PLAYER"] = 1.0 if rotation_tier in {"BENCH", "DEEP_BENCH"} else 0.0
            profile["STARTER"] = 1.0 if player_key in starter_keys else 0.0
            profile["CLOSER"] = 1.0 if player_key in closer_keys else 0.0
            profile["SECOND_UNIT"] = 1.0 if player_key in second_unit_keys else 0.0
            profile["GARBAGE_UNIT"] = 1.0 if rotation_tier == "DEEP_BENCH" or (rotation_tier == "BENCH" and m_rank >= 8) else 0.0
            profile["GARBAGE_TIME_FIT"] = min(
                1.0,
                max(
                    0.0,
                    (0.55 * profile["BENCH_PLAYER"])
                    + (0.20 * profile["VOLATILITY"])
                    + (0.15 * profile["REBOUNDER"])
                    + (0.10 * (1.0 if u_rank > 6 else 0.0)),
                ),
            )

            template = (rotation_templates or {}).get(player_key)
            if template:
                template_weight = float(template.get("TEMPLATE_SAMPLE_WEIGHT", 0.0))
                if template_weight > 0:
                    profile["STARTER"] = float(
                        np.clip(((1.0 - template_weight) * profile["STARTER"]) + (template_weight * template.get("TEMPLATE_STARTER", 0.0)), 0.0, 1.0)
                    )
                    profile["CLOSER"] = float(
                        np.clip(((1.0 - template_weight) * profile["CLOSER"]) + (template_weight * template.get("TEMPLATE_CLOSER", 0.0)), 0.0, 1.0)
                    )
                    profile["SECOND_UNIT"] = float(
                        np.clip(((1.0 - template_weight) * profile["SECOND_UNIT"]) + (template_weight * template.get("TEMPLATE_SECOND_UNIT", 0.0)), 0.0, 1.0)
                    )
                    profile["GARBAGE_UNIT"] = float(
                        np.clip(((1.0 - template_weight) * profile["GARBAGE_UNIT"]) + (template_weight * template.get("TEMPLATE_GARBAGE_UNIT", 0.0)), 0.0, 1.0)
                    )
                    profile["GARBAGE_TIME_FIT"] = float(
                        np.clip(
                            ((1.0 - (0.70 * template_weight)) * profile["GARBAGE_TIME_FIT"])
                            + ((0.70 * template_weight) * max(template.get("TEMPLATE_GARBAGE_UNIT", 0.0), profile["GARBAGE_UNIT"])),
                            0.0,
                            1.0,
                        )
                    )
                profile["TEMPLATE_MINUTES"] = float(template.get("TEMPLATE_MINUTES", 0.0))
                profile["TEMPLATE_GAMES"] = float(template.get("TEMPLATE_GAMES", 0.0))
                profile["TEMPLATE_SAMPLE_WEIGHT"] = template_weight
                profile["TEMPLATE_Q1_SHARE"] = float(template.get("TEMPLATE_Q1_SHARE", 0.25))
                profile["TEMPLATE_Q2_SHARE"] = float(template.get("TEMPLATE_Q2_SHARE", 0.25))
                profile["TEMPLATE_Q3_SHARE"] = float(template.get("TEMPLATE_Q3_SHARE", 0.25))
                profile["TEMPLATE_Q4_SHARE"] = float(template.get("TEMPLATE_Q4_SHARE", 0.25))
            else:
                profile["TEMPLATE_MINUTES"] = 0.0
                profile["TEMPLATE_GAMES"] = 0.0
                profile["TEMPLATE_SAMPLE_WEIGHT"] = 0.0
                profile["TEMPLATE_Q1_SHARE"] = 0.25
                profile["TEMPLATE_Q2_SHARE"] = 0.25
                profile["TEMPLATE_Q3_SHARE"] = 0.25
                profile["TEMPLATE_Q4_SHARE"] = 0.25

    enrich_lineup_signals_for_all_teams(profiles, team_rosters, rotation_templates, matchups)
    return profiles


def build_playoff_rotation_expansion_rows(logs_df, injury_map, slate_teams, archetypes, existing_player_keys):
    if not slate_teams:
        return pd.DataFrame(columns=["PLAYER_NAME", "PLAYER_KEY", "TEAM"])
    exist = {str(k).strip() for k in existing_player_keys}
    rows = []
    for team in slate_teams:
        team_logs = logs_df[logs_df["TEAM_ABBREVIATION"].astype(str).str.strip().str.upper() == str(team).strip().upper()]
        if team_logs.empty:
            continue
        for pk in team_logs["PLAYER_KEY"].dropna().unique():
            pk = str(pk).strip()
            if not pk or pk in exist:
                continue
            if normalize_injury_status(injury_map.get(pk, "ACTIVE")) == "OUT":
                continue
            plog = team_logs[team_logs["PLAYER_KEY"].astype(str).str.strip() == pk].sort_values("GAME_DATE", ascending=False)
            if len(plog) < 3:
                continue
            avg10 = rolling_mean_minutes_capped(plog, 10) if len(plog) >= 5 else float(safe_mean(plog.head(10)["MIN"]))
            prof = archetypes.get(pk, {})
            mrank = int(prof.get("MINUTE_RANK_TEAM", 99))
            rrate = float(prof.get("RECENT_START_RATE", 0.0))
            heavy = float(prof.get("RECENT_HEAVY_MIN_RATE", 0.0))
            ann = float(prof.get("ANNOUNCED_STARTER", 0.0))
            rtier = str(prof.get("ROTATION_TIER", "")).upper()
            credible_rotation = (
                ann >= 0.5
                or heavy >= 0.25
                or rrate >= 0.35
                or mrank <= 9
                or (rtier in {"CORE", "ROTATION"} and avg10 >= 14.0)
                or avg10 >= 18.0
            )
            if credible_rotation:
                if avg10 < 8.0 and mrank > 10 and ann < 0.5 and heavy < 0.20:
                    continue
                name = str(plog.iloc[0]["PLAYER_NAME"]).strip()
                if name:
                    rows.append({"PLAYER_NAME": name, "PLAYER_KEY": pk, "TEAM": str(team).strip().upper()})
    if not rows:
        return pd.DataFrame(columns=["PLAYER_NAME", "PLAYER_KEY", "TEAM"])
    return pd.DataFrame(rows)


def filter_playoff_projection_universe(unique_players, logs_df, archetypes, line_universe, matchups):
    if unique_players is None or unique_players.empty:
        return unique_players
    line_keys = set()
    if line_universe is not None and not line_universe.empty and "PLAYER_KEY" in line_universe.columns:
        line_keys = set(line_universe["PLAYER_KEY"].dropna().astype(str).str.strip().tolist())
    announced = set()
    for info in (matchups or {}).values():
        announced |= set(info.get("ANNOUNCED_STARTER_KEYS") or [])

    latest = logs_df.sort_values("GAME_DATE", ascending=False).copy()
    latest["PLAYER_KEY"] = latest["PLAYER_KEY"].astype(str).str.strip()
    recent_avg = (
        latest.groupby("PLAYER_KEY")
        .head(10)
        .groupby("PLAYER_KEY")["MIN"]
        .mean()
        .to_dict()
    )

    rows = []
    dropped = []
    for _, row in unique_players.iterrows():
        pk = str(row.get("PLAYER_KEY", "")).strip()
        prof = archetypes.get(pk, {})
        avg10 = float(recent_avg.get(pk, 0.0) or 0.0)
        mrank = int(prof.get("MINUTE_RANK_TEAM", 99))
        rtier = str(prof.get("ROTATION_TIER", "")).upper()
        heavy = float(prof.get("RECENT_HEAVY_MIN_RATE", 0.0))
        rstart = float(prof.get("RECENT_START_RATE", 0.0))
        keep = (
            pk in line_keys
            or pk in announced
            or mrank <= 9
            or heavy >= 0.25
            or rstart >= 0.35
            or avg10 >= 18.0
            or (rtier == "CORE" and avg10 >= 14.0)
            or (rtier == "ROTATION" and avg10 >= 16.0)
        )
        if keep:
            rows.append(row.to_dict())
        else:
            dropped.append(str(row.get("PLAYER_NAME", pk)).strip())
    if dropped:
        print(
            f"Playoff universe realism filter: dropped {len(dropped)} weak fringe candidate(s) "
            "before team closure/stat distribution."
        )
    return pd.DataFrame(rows) if rows else unique_players.iloc[0:0].copy()


def build_lineup_injury_context(logs_df, injury_map, archetypes):
    latest_rows = logs_df.drop_duplicates(subset=["PLAYER_KEY"], keep="first").copy()
    team_players = latest_rows.groupby("TEAM_ABBREVIATION")["PLAYER_KEY"].apply(list).to_dict()
    team_baselines = (
        logs_df.groupby(
            ["GAME_ID", "TEAM_ABBREVIATION"],
            as_index=False,
        )[["PTS", "AST", "REB", "FG3M", "TOV", "FGM", "FGA", "FTA", "FTM"]]
        .sum()
        .groupby("TEAM_ABBREVIATION")[["PTS", "AST", "REB", "FG3M", "TOV", "FGM", "FGA", "FTA", "FTM"]]
        .mean()
        .to_dict("index")
    )
    team_context = {}

    for team, roster in team_players.items():
        role_losses = {key: 0.0 for key in ROLE_KEYS}
        usage_loss = 0.0
        points_weights = {}
        assist_weights = {}
        rebound_weights = {}
        fg3m_weights = {}
        tov_weights = {}
        fga_weights = {}
        fta_weights = {}

        for player_key in roster:
            status_norm = normalize_injury_status(injury_map.get(player_key, "ACTIVE"))
            weight = INJURY_IMPACT_WEIGHT.get(status_norm, 0.0)
            if weight <= 0:
                continue
            profile = archetypes.get(player_key)
            if not profile:
                continue
            for role_key in ROLE_KEYS:
                role_losses[role_key] += profile[role_key] * weight * min(1.0, profile["MINUTES"] / 32.0)
            usage_loss += min(1.0, profile["USAGE_LOAD"] / 34.0) * weight

        for player_key in roster:
            profile = archetypes.get(player_key)
            if not profile:
                continue
            status_norm = normalize_injury_status(injury_map.get(player_key, "ACTIVE"))
            availability = STATUS_AVAILABILITY.get(status_norm, STATUS_AVAILABILITY["UNKNOWN"])
            if availability <= 0:
                continue
            minute_weight = min(1.0, profile["MINUTES"] / 34.0)
            active_weight = availability * (
                0.60
                + (0.24 * minute_weight)
                + (0.08 * profile.get("STARTER", 0.0))
                + (0.08 * profile.get("CLOSER", 0.0))
            )
            points_weights[player_key] = active_weight * (
                (0.55 * profile["SCORER"])
                + (0.25 * profile["SHOOTER"])
                + (0.10 * profile.get("CLOSER", 0.0))
                + (0.10 * minute_weight)
            )
            assist_weights[player_key] = active_weight * (
                (0.62 * profile["PLAYMAKER"])
                + (0.18 * profile["SCORER"])
                + (0.08 * profile.get("CLOSER", 0.0))
                + (0.20 * minute_weight)
            )
            rebound_weights[player_key] = active_weight * (
                (0.58 * profile["REBOUNDER"])
                + (0.20 * profile["RIM"])
                + (0.22 * minute_weight)
            )
            fg3m_weights[player_key] = active_weight * (
                (0.60 * profile["SHOOTER"])
                + (0.20 * profile["SCORER"])
                + (0.08 * profile.get("CLOSER", 0.0))
                + (0.20 * minute_weight)
            )
            tov_weights[player_key] = active_weight * (
                (0.48 * profile["PLAYMAKER"])
                + (0.30 * profile["SCORER"])
                + (0.22 * minute_weight)
            )
            fga_weights[player_key] = active_weight * (
                (0.50 * profile["SCORER"])
                + (0.28 * profile["SHOOTER"])
                + (0.10 * profile.get("CLOSER", 0.0))
                + (0.22 * minute_weight)
            )
            fta_weights[player_key] = active_weight * (
                (0.44 * profile["SCORER"])
                + (0.22 * profile["RIM"])
                + (0.14 * profile["PLAYMAKER"])
                + (0.08 * profile.get("CLOSER", 0.0))
                + (0.20 * minute_weight)
            )

        points_total = max(sum(points_weights.values()), 1e-6)
        assist_total = max(sum(assist_weights.values()), 1e-6)
        rebound_total = max(sum(rebound_weights.values()), 1e-6)
        fg3m_total = max(sum(fg3m_weights.values()), 1e-6)
        tov_total = max(sum(tov_weights.values()), 1e-6)
        fga_total = max(sum(fga_weights.values()), 1e-6)
        fta_total = max(sum(fta_weights.values()), 1e-6)
        player_allocation = {}
        for player_key in roster:
            player_allocation[player_key] = {
                "PTS_SHARE": float(points_weights.get(player_key, 0.0) / points_total),
                "AST_SHARE": float(assist_weights.get(player_key, 0.0) / assist_total),
                "REB_SHARE": float(rebound_weights.get(player_key, 0.0) / rebound_total),
                "FG3M_SHARE": float(fg3m_weights.get(player_key, 0.0) / fg3m_total),
                "TOV_SHARE": float(tov_weights.get(player_key, 0.0) / tov_total),
                "FGA_SHARE": float(fga_weights.get(player_key, 0.0) / fga_total),
                "FTA_SHARE": float(fta_weights.get(player_key, 0.0) / fta_total),
            }

        baseline = team_baselines.get(team, {})

        team_context[team] = {
            "ROLE_LOSSES": {role: min(val, 1.5) for role, val in role_losses.items()},
            "USAGE_LOSS": min(usage_loss, 1.5),
            "BASELINE_TEAM_POINTS": float(baseline.get("PTS", np.nan)),
            "BASELINE_TEAM_AST": float(baseline.get("AST", np.nan)),
            "BASELINE_TEAM_REB": float(baseline.get("REB", np.nan)),
            "BASELINE_TEAM_FG3M": float(baseline.get("FG3M", np.nan)),
            "BASELINE_TEAM_TOV": float(baseline.get("TOV", np.nan)),
            "BASELINE_TEAM_FGM": float(baseline.get("FGM", np.nan)),
            "BASELINE_TEAM_FGA": float(baseline.get("FGA", np.nan)),
            "BASELINE_TEAM_FTA": float(baseline.get("FTA", np.nan)),
            "BASELINE_TEAM_FTM": float(baseline.get("FTM", np.nan)),
            "PLAYER_ALLOCATION": player_allocation,
        }

    return team_context


def build_game_sim_contexts(
    matchups,
    team_strength,
    lineup_injury_context,
    team_pace,
    league_pace,
    league_game_total,
    market_game_lines,
    playoff_slate=False,
):
    contexts = {}
    processed_matchups = set()

    for team, matchup_info in matchups.items():
        opponent = str(matchup_info.get("OPPONENT", "")).strip().upper()
        if not opponent:
            continue

        game_id = matchup_key(team, opponent)
        if game_id in processed_matchups:
            continue
        processed_matchups.add(game_id)

        team_home = 1 if "vs." in str(matchup_info.get("MATCHUP", "")) else 0
        opponent_home = 1 if team_home == 0 else 0

        team_strength_row = team_strength.loc[team] if team in team_strength.index else None
        opp_strength_row = team_strength.loc[opponent] if opponent in team_strength.index else None

        team_quality = float(team_strength_row["TEAM_QUALITY"]) if team_strength_row is not None else 0.0
        opp_quality = float(opp_strength_row["TEAM_QUALITY"]) if opp_strength_row is not None else 0.0
        team_margin_std = float(team_strength_row["MARGIN_STD"]) if team_strength_row is not None else DEFAULT_MARGIN_STD
        opp_margin_std = float(opp_strength_row["MARGIN_STD"]) if opp_strength_row is not None else DEFAULT_MARGIN_STD
        team_avg_pace = float(team_pace.get(team, league_pace))
        opp_avg_pace = float(team_pace.get(opponent, league_pace))

        team_context = lineup_injury_context.get(team, {"USAGE_LOSS": 0.0, "ROLE_LOSSES": {}})
        opp_context = lineup_injury_context.get(opponent, {"USAGE_LOSS": 0.0, "ROLE_LOSSES": {}})
        injury_margin_shift = 4.5 * (opp_context["USAGE_LOSS"] - team_context["USAGE_LOSS"])

        model_margin = (team_quality - opp_quality) + injury_margin_shift + (HOME_COURT_EDGE if team_home else -HOME_COURT_EDGE)
        market_line = market_game_lines.get(game_id, {})
        market_total = None
        market_margin = None
        if market_line:
            market_total = pd.to_numeric(market_line.get("TOTAL"), errors="coerce")
            if team == market_line.get("HOME_TEAM"):
                market_margin = -pd.to_numeric(market_line.get("HOME_SPREAD"), errors="coerce")
            elif team == market_line.get("AWAY_TEAM"):
                market_margin = -pd.to_numeric(market_line.get("AWAY_SPREAD"), errors="coerce")

        if market_margin is not None and not pd.isna(market_margin):
            expected_margin = (MARKET_SPREAD_BLEND * float(market_margin)) + ((1.0 - MARKET_SPREAD_BLEND) * model_margin)
            base_margin_std = 11.2 - min(abs(float(market_margin)), 16.0) * 0.18
        else:
            expected_margin = model_margin
            base_margin_std = np.sqrt((team_margin_std ** 2 + opp_margin_std ** 2) / 2.0)

        margin_std = max(7.5, min(16.0, float(base_margin_std)))
        expected_pace = (team_avg_pace + opp_avg_pace) / 2.0
        market_total_factor = 1.0
        implied_team_total = np.nan
        implied_opp_total = np.nan
        if market_total is not None and not pd.isna(market_total) and league_game_total > 0:
            total_delta = (float(market_total) - float(league_game_total)) / max(float(league_game_total), 1.0)
            market_total_factor = float(np.clip(1.0 + (MARKET_TOTAL_BLEND * total_delta), 0.94, 1.07))
            implied_team_total = (float(market_total) / 2.0) + (float(expected_margin) / 2.0)
            implied_opp_total = float(market_total) - implied_team_total

        rng_seed = abs(hash((game_id, current_projection_date(), "game_context"))) % (2 ** 32)
        rng = np.random.default_rng(rng_seed)
        margin_draws = rng.normal(expected_margin, margin_std, SIMULATION_RUNS)
        if playoff_slate:
            competitive_mask = np.abs(margin_draws) <= PLAYOFF_COMPETITIVE_ABS_MARGIN
            blowout_mask = np.abs(margin_draws) >= PLAYOFF_BLOWOUT_MARGIN
        else:
            competitive_mask = np.abs(margin_draws) <= 6.0
            blowout_mask = np.abs(margin_draws) >= BLOWOUT_THRESHOLD
        pace_noise = rng.normal(0.0, 0.018, SIMULATION_RUNS)
        pace_script = np.clip((1.0 + ((expected_pace - league_pace) / max(league_pace, 1.0)) + pace_noise) * market_total_factor, 0.93, 1.10)

        market_guardrail_mode = "market" if not pd.isna(implied_team_total) and market_total is not None and not pd.isna(market_total) else "baseline_fallback"
        team_points_target = implied_team_total if not pd.isna(implied_team_total) else float(team_context.get("BASELINE_TEAM_POINTS", 110.0))
        opp_points_target = implied_opp_total if not pd.isna(implied_opp_total) else float(opp_context.get("BASELINE_TEAM_POINTS", 110.0))
        if market_guardrail_mode != "market":
            team_points_target = float(np.clip(team_points_target, 92.0, 128.0))
            opp_points_target = float(np.clip(opp_points_target, 92.0, 128.0))
            implied_team_total = team_points_target
            implied_opp_total = opp_points_target
        team_points_ratio = team_points_target / max(float(team_context.get("BASELINE_TEAM_POINTS", team_points_target)), 1.0)
        opp_points_ratio = opp_points_target / max(float(opp_context.get("BASELINE_TEAM_POINTS", opp_points_target)), 1.0)

        def team_event_draws(side_context, points_target, points_ratio):
            base_ast = float(side_context.get("BASELINE_TEAM_AST", 24.0))
            base_reb = float(side_context.get("BASELINE_TEAM_REB", 44.0))
            base_fg3m = float(side_context.get("BASELINE_TEAM_FG3M", 13.0))
            base_tov = float(side_context.get("BASELINE_TEAM_TOV", 13.5))
            base_fgm = float(side_context.get("BASELINE_TEAM_FGM", 40.0))
            base_fga = float(side_context.get("BASELINE_TEAM_FGA", 88.0))
            base_fta = float(side_context.get("BASELINE_TEAM_FTA", 24.0))
            base_ftm = float(side_context.get("BASELINE_TEAM_FTM", 19.0))
            ast_target = base_ast * min(1.12, max(0.88, 0.96 + (0.55 * (points_ratio - 1.0))))
            reb_target = base_reb * min(1.08, max(0.94, 0.99 + (0.18 * (points_ratio - 1.0))))
            fg3m_target = base_fg3m * min(1.18, max(0.82, 0.94 + (0.75 * (points_ratio - 1.0))))
            tov_target = base_tov * min(1.12, max(0.90, 0.98 + (0.30 * (points_ratio - 1.0))))
            fga_target = base_fga * min(1.12, max(0.90, 0.98 + (0.55 * (points_ratio - 1.0))))
            fta_target = base_fta * min(1.15, max(0.88, 0.98 + (0.70 * (points_ratio - 1.0))))
            fgm_target = base_fgm * min(1.12, max(0.90, 0.98 + (0.52 * (points_ratio - 1.0))))
            ftm_target = base_ftm * min(1.15, max(0.88, 0.98 + (0.68 * (points_ratio - 1.0))))
            ast_target = min(ast_target, fgm_target * 0.82)
            fgm_target = min(fgm_target, fga_target * 0.68)
            ftm_target = min(ftm_target, fta_target * 0.90)
            return {
                "TEAM_POINTS_DRAWS": np.clip(rng.normal(points_target, max(5.5, 0.07 * points_target), SIMULATION_RUNS), 75.0, 165.0),
                "TEAM_AST_DRAWS": np.clip(rng.normal(ast_target, max(3.0, 0.11 * ast_target), SIMULATION_RUNS), 10.0, 45.0),
                "TEAM_REB_DRAWS": np.clip(rng.normal(reb_target, max(4.0, 0.10 * reb_target), SIMULATION_RUNS), 28.0, 70.0),
                "TEAM_FG3M_DRAWS": np.clip(rng.normal(fg3m_target, max(1.8, 0.16 * fg3m_target), SIMULATION_RUNS), 3.0, 30.0),
                "TEAM_TOV_DRAWS": np.clip(rng.normal(tov_target, max(1.8, 0.14 * tov_target), SIMULATION_RUNS), 6.0, 24.0),
                "TEAM_FGM_DRAWS": np.clip(rng.normal(fgm_target, max(2.8, 0.09 * fgm_target), SIMULATION_RUNS), 24.0, 65.0),
                "TEAM_FGA_DRAWS": np.clip(rng.normal(fga_target, max(4.0, 0.08 * fga_target), SIMULATION_RUNS), 60.0, 120.0),
                "TEAM_FTA_DRAWS": np.clip(rng.normal(fta_target, max(2.6, 0.12 * fta_target), SIMULATION_RUNS), 10.0, 45.0),
                "TEAM_FTM_DRAWS": np.clip(rng.normal(ftm_target, max(2.2, 0.10 * ftm_target), SIMULATION_RUNS), 8.0, 38.0),
            }

        team_event_pools = team_event_draws(team_context, team_points_target, team_points_ratio)
        opp_event_pools = team_event_draws(opp_context, opp_points_target, opp_points_ratio)

        elim_raw = str(matchup_info.get("ELIMINATION_TEAM", "")).strip().upper()
        team_faces_elim = bool(elim_raw and elim_raw == team)
        opp_faces_elim = bool(elim_raw and elim_raw == opponent)
        blowout_penalty_scale = PLAYOFF_BLOWOUT_PENALTY_SCALE if playoff_slate else 1.0
        close_game_bonus_scale = 1.14 if playoff_slate else 1.0

        game_context = {
            "GAME_ID": game_id,
            "EXPECTED_MARGIN": float(expected_margin),
            "MARGIN_STD": float(margin_std),
            "EXPECTED_PACE": float(expected_pace),
            "MARKET_SPREAD": float(market_margin) if market_margin is not None and not pd.isna(market_margin) else np.nan,
            "MARKET_TOTAL": float(market_total) if market_total is not None and not pd.isna(market_total) else np.nan,
            "IMPLIED_TEAM_TOTAL": float(implied_team_total) if not pd.isna(implied_team_total) else np.nan,
            "IMPLIED_OPP_TOTAL": float(implied_opp_total) if not pd.isna(implied_opp_total) else np.nan,
            "MARKET_GUARDRAIL_MODE": market_guardrail_mode,
            "PACE_SCRIPT": pace_script,
            "TEAM_MARGIN_DRAWS": margin_draws,
            "COMPETITIVE_MASK": competitive_mask,
            "BLOWOUT_MASK": blowout_mask,
            "PLAYOFF_MODE": bool(playoff_slate),
            "TEAM_FACES_ELIMINATION": team_faces_elim,
            "BLOWOUT_PENALTY_SCALE": float(blowout_penalty_scale),
            "CLOSE_GAME_BONUS_SCALE": float(close_game_bonus_scale),
            **team_event_pools,
        }
        contexts[team] = game_context
        contexts[opponent] = {
            **game_context,
            "EXPECTED_MARGIN": float(-expected_margin),
            "MARKET_SPREAD": float(-market_margin) if market_margin is not None and not pd.isna(market_margin) else np.nan,
            "IMPLIED_TEAM_TOTAL": float(implied_opp_total) if not pd.isna(implied_opp_total) else np.nan,
            "IMPLIED_OPP_TOTAL": float(implied_team_total) if not pd.isna(implied_team_total) else np.nan,
            "TEAM_MARGIN_DRAWS": -margin_draws,
            "TEAM_FACES_ELIMINATION": opp_faces_elim,
            **opp_event_pools,
        }

    return contexts


def predict_with_model(model, feature_values, feature_order):
    if model is None:
        return None
    frame = pd.DataFrame([{col: float(feature_values.get(col, 0.0)) for col in feature_order}])
    try:
        pred = model.predict(frame)[0]
        return float(pred)
    except Exception:
        return None


def blended_stat_projection(stat, model_pred, features, playoff_mode=False):
    last3 = features[f"{stat}_LAST3"]
    last5 = features[f"{stat}_LAST5"]
    last10 = features[f"{stat}_LAST10"]
    weights = RECENT_WEIGHTS[stat]
    recent_blend = (weights[0] * last5) + (weights[1] * last10) + (weights[2] * last3)

    if model_pred is None:
        return max(0.0, recent_blend)

    if playoff_mode and stat in {"PTS", "REB", "AST"}:
        model_weight = 0.48
    elif playoff_mode and stat in {"STL", "BLK", "FG3M"}:
        model_weight = 0.44
    else:
        model_weight = 0.60 if stat in {"PTS", "REB", "AST"} else 0.52
    recent_weight = 1.0 - model_weight
    return max(0.0, (model_weight * model_pred) + (recent_weight * recent_blend))


def minutes_projection(model_pred, features, playoff_mode=False):
    if playoff_mode:
        recent_component = (0.52 * features["MIN_LAST5"]) + (0.34 * features["MIN_LAST3"]) + (0.14 * features["MIN_LAST10"])
        if model_pred is None:
            return max(0.0, recent_component)
        return max(0.0, (0.26 * model_pred) + (0.74 * recent_component))
    recent_component = (0.50 * features["MIN_LAST5"]) + (0.30 * features["MIN_LAST10"]) + (0.20 * features["MIN_LAST3"])
    if model_pred is None:
        return max(0.0, recent_component)
    return max(0.0, (0.62 * model_pred) + (0.38 * recent_component))


def build_playoff_minute_anchor(player_logs, player_profile, features):
    if "SEASON_TYPE" not in player_logs.columns:
        return 0.0, "no_season_type", 0

    playoff_logs = player_logs[player_logs["SEASON_TYPE"] == "Playoffs"]
    if playoff_logs.empty:
        return 0.0, "fallback_heuristic", 0
        
    p_len = len(playoff_logs)
    p_recent = playoff_logs.head(3)
    p_mins = pd.to_numeric(playoff_logs["MIN"], errors="coerce").fillna(0.0)
    p_recent_mins = pd.to_numeric(p_recent["MIN"], errors="coerce").fillna(0.0)
    
    avg_recent = float(p_recent_mins.mean())
    avg_all = float(p_mins.mean())
    season_mins = float((player_profile or {}).get("MINUTES", features.get("MIN_LAST10", 0.0)))
    
    if p_len == 1:
        anchor = (0.65 * avg_all) + (0.35 * season_mins)
        return anchor, "1_game_blend", p_len
    elif p_len <= 3:
        anchor = (0.80 * avg_all) + (0.20 * season_mins)
        return anchor, "2_3_game_blend", p_len
    else:
        anchor = (0.65 * avg_recent) + (0.35 * avg_all)
        return anchor, "4_plus_playoff", p_len


def compute_locked_playoff_minutes_prior(player_logs, player_profile, features):
    """
    Hard playoff minutes prior. Recent REAL playoff minutes are the primary source of truth.
    When no playoff games exist, falls back to the last 8 meaningful games.
    """
    has_season_type = "SEASON_TYPE" in player_logs.columns
    playoff_logs = player_logs[player_logs["SEASON_TYPE"] == "Playoffs"].copy() if has_season_type else player_logs.iloc[0:0].copy()
    p_len = len(playoff_logs)
    season_mins = float((player_profile or {}).get("MINUTES", features.get("MIN_LAST10", 0.0)))

    if p_len >= 1:
        p_mins = pd.to_numeric(playoff_logs["MIN"], errors="coerce").fillna(0.0)
        if not p_mins.empty and p_mins.sum() > 0:
            avg_all = float(p_mins.mean())
            if p_len == 1:
                return {
                    "minutes": (0.65 * avg_all) + (0.35 * max(season_mins, 8.0)),
                    "kind": "true_playoff",
                    "source": "1_game_playoff_blend",
                    "games_used": p_len,
                    "confidence": "medium",
                }
            if p_len <= 3:
                return {
                    "minutes": (0.80 * avg_all) + (0.20 * max(season_mins, 8.0)),
                    "kind": "true_playoff",
                    "source": "2_3_game_playoff_blend",
                    "games_used": p_len,
                    "confidence": "high",
                }
            p_recent = playoff_logs.head(3)
            p_recent_mins = pd.to_numeric(p_recent["MIN"], errors="coerce").fillna(0.0)
            avg_recent = float(p_recent_mins.mean())
            return {
                "minutes": (0.70 * avg_recent) + (0.30 * avg_all),
                "kind": "true_playoff",
                "source": "4_plus_playoff",
                "games_used": p_len,
                "confidence": "high",
            }

    # 0 playoff games: fallback to last 8 meaningful games (MIN > 0)
    meaningful = player_logs[pd.to_numeric(player_logs["MIN"], errors="coerce").fillna(0.0) > 0].head(8)
    if len(meaningful) >= 3:
        return {
            "minutes": float(pd.to_numeric(meaningful["MIN"], errors="coerce").fillna(0.0).mean()),
            "kind": "rs_fallback",
            "source": "recent_regular_season_fallback",
            "games_used": 0,
            "confidence": "low",
        }
    return {
        "minutes": float(features.get("MIN_LAST10", season_mins)),
        "kind": "rs_fallback",
        "source": "feature_regular_season_fallback",
        "games_used": 0,
        "confidence": "low",
    }


def protect_core_minutes(mean_minutes, player_logs, features, role_fit, playoff_mode=False, player_profile=None, playoff_minutes_prior=0.0):
    if features["LOW_MIN_ROLE"] or role_fit.get("BENCH_PLAYER", 0.0) >= 0.5:
        return mean_minutes, 0.0

    star_signal = (
        (0.44 * role_fit.get("SCORER", 0.0))
        + (0.24 * role_fit.get("PLAYMAKER", 0.0))
        + (0.20 * role_fit.get("CORE_PLAYER", 0.0))
        + (0.12 * role_fit.get("CLOSER", 0.0))
    )
    starter = float(role_fit.get("STARTER", 0.0))
    core_player = float(role_fit.get("CORE_PLAYER", 0.0))

    if playoff_mode:
        if star_signal < 0.38 and starter < 0.40:
            return mean_minutes, 0.0
            
        pp = player_profile or {}
        ur = int(pp.get("USAGE_RANK_TEAM", 99))
        mr = int(pp.get("MINUTE_RANK_TEAM", 99))
        fake_risk = float(pp.get("FAKE_STARTER_RISK", 0.0))
        stab = float(pp.get("ROLE_STABILITY_SCORE", 0.75))
        
        engine = False
        if player_profile is not None:
            engine = playoff_high_minute_engine_eligible({"role_fit": role_fit, "player_profile": player_profile})
            
        role_floor = 0.0
        cap = 48.0
        
        # If an explicit playoff-minutes prior exists, trust it over re-deriving from logs.
        # This guarantees the prior controls the floor/cap even when SEASON_TYPE detection
        # is inconsistent or missing.
        if playoff_minutes_prior > 0.0:
            anchor = float(playoff_minutes_prior)
            source = "playoff_minutes_prior"
            games_used = int(pp.get("PLAYOFF_GAMES", 0))
        else:
            anchor, source, games_used = build_playoff_minute_anchor(player_logs, pp, features)
        if player_profile is not None and not (
            playoff_minutes_prior <= 0.0 and str(pp.get("playoff_prior_kind", "")) == "rs_fallback"
        ):
            player_profile["playoff_minute_anchor"] = round(float(anchor), 2)
            player_profile["playoff_anchor_source"] = source
            player_profile["playoff_anchor_games_used"] = games_used
            
        if anchor > 0.0:
            role_floor = anchor * 0.88
            cap = anchor * 1.12
            
            # Star overrides still apply: if the anchor isn't quite at the band, pull it up
            if engine and ur <= 3:
                role_floor = max(role_floor, 37.0)
                cap = max(cap, 42.0)
            elif star_signal >= 0.58 and ur <= 4 and mr <= 5:
                role_floor = max(role_floor, 33.0)
                cap = max(cap, 39.0)
                
            # If the player is a role player who spiked to 38 mins, the role overrides below will naturally squash them.
        else:
            # 1. Primary Engines / Alpha Stars (37-40)
            # Trust core usage rank over recent volatility/fake_risk.
            if engine and ur <= 3:
                role_floor = 37.0
                cap = 42.0
                
            # 2. Secondary Stars / Strong Core Starters (33-37)
            elif star_signal >= 0.58 and ur <= 4 and mr <= 5:
                role_floor = 33.0
                cap = 39.0
                
            # 3. Role Starters / Strong Closers (26-33)
            elif (starter >= 0.5 or role_fit.get("CLOSER", 0.0) >= 0.5) and mr <= 7 and fake_risk < 0.65:
                role_floor = 26.0
                cap = 34.0
                
            # 4. Bench Rotation (10-24)
            elif mr <= 9:
                role_floor = 12.0
                cap = 25.0
                
            # 5. Fringe (0-10)
            else:
                role_floor = 0.0
                cap = 12.0
            
        # Safety overrides for role inflation (stop Duncan/Jenkins/Ajay Mitchell)
        # DISABLED when a real playoff prior exists — actual playoff minutes outrank
        # regular-season heuristic guesses.
        if playoff_minutes_prior <= 0.0:
            if (fake_risk >= 0.60 or stab < 0.55 or ur >= 5) and ur > 3:
                role_floor = min(role_floor, 24.0)
                if ur >= 6:
                    cap = min(cap, 22.0)
                elif ur >= 5:
                    cap = min(cap, 28.0)
                else:
                    cap = min(cap, 32.0)
            if mr <= 5 and not engine and ur >= 5:
                role_floor = min(role_floor, 26.0)
                cap = min(cap, 30.0)

        protected_minutes = float(role_floor)
        mean_minutes = float(np.clip(mean_minutes, role_floor, cap))

        return max(mean_minutes, protected_minutes), protected_minutes

    if star_signal < 0.52:
        return mean_minutes, 0.0

    recent20 = rolling_mean(player_logs.head(20), "MIN", 20)
    recent30 = rolling_mean(player_logs.head(30), "MIN", 30)
    durable_anchor = max(features["MIN_LAST10"], 0.92 * recent20, 0.86 * recent30)
    if durable_anchor < 24.0:
        return mean_minutes, 0.0

    protected_minutes = min(34.5, durable_anchor * (0.96 + (0.05 * star_signal)))
    return max(mean_minutes, protected_minutes), protected_minutes


def apply_playoff_rotation_tightening(mean_minutes, role_fit, player_profile, playoff_mode):
    if not playoff_mode:
        return mean_minutes
    tier = str(player_profile.get("ROTATION_TIER", "")).strip().upper()
    starter = float(role_fit.get("STARTER", 0.0))
    if tier == "DEEP_BENCH":
        return mean_minutes * 0.52
    if tier == "BENCH":
        return mean_minutes * 0.70
    if tier == "ROTATION" and starter < 0.38:
        return mean_minutes * 0.86
    return mean_minutes


def _clamp_playoff_minutes_to_prior(group):
    """
    Hard clamp post-closure minutes so no player drifts more than tier-allowed
    delta from their real playoff prior.
    """
    for c in group:
        prior = float(c.get("playoff_minutes_prior", 0.0))
        if prior <= 0 or str(c.get("playoff_prior_kind", "")) != "true_playoff":
            continue
        tier = playoff_closure_priority_tier(c)
        if tier == 1:
            max_delta = 2.5
        elif tier == 2:
            max_delta = 3.0
        elif tier == 3:
            max_delta = 4.0
        else:
            max_delta = 5.0
        old_m = float(c["mean_minutes"])
        new_m = float(np.clip(old_m, prior - max_delta, prior + max_delta))
        c["mean_minutes"] = new_m
        if c["player_key"] in _TRACE_KEYS and old_m != new_m:
            print(
                f"[TRACE:CLAMP] {c['player_key']} | "
                f"prior={round(prior, 2)} | old={round(old_m, 2)} | new={round(new_m, 2)} | tier={tier}"
            )


def _enforce_playoff_prior_hierarchy(group):
    """
    If player A's playoff prior exceeds player B's by 8+ minutes,
    closure can never invert their final minute ordering.
    """
    n = len(group)
    for i in range(n):
        for j in range(i + 1, n):
            pi = float(group[i].get("playoff_minutes_prior", 0.0))
            pj = float(group[j].get("playoff_minutes_prior", 0.0))
            if str(group[i].get("playoff_prior_kind", "")) != "true_playoff":
                pi = 0.0
            if str(group[j].get("playoff_prior_kind", "")) != "true_playoff":
                pj = 0.0
            if abs(pi - pj) < 8:
                continue
            mi = float(group[i]["mean_minutes"])
            mj = float(group[j]["mean_minutes"])
            if pi > pj and mi < mj:
                group[j]["mean_minutes"] = max(0.0, min(mj, mi - 0.1))
            elif pj > pi and mj < mi:
                group[i]["mean_minutes"] = max(0.0, min(mi, mj - 0.1))


def spot_stability_bucket(features, injury_status, role_fit, playoff_mode, player_profile):
    tier = str(player_profile.get("ROTATION_TIER", "")).strip().upper()
    if injury_status == "DOUBTFUL":
        return "risky"
    if injury_status == "QUESTIONABLE":
        return "risky" if features["MIN_STD5"] > 6.0 else "volatile"
    if features["MIN_STD5"] > 9.0:
        return "risky"
    if features["MIN_STD5"] > 6.5 or features["VOLATILE_MINUTES"]:
        return "volatile"
    if playoff_mode and tier in {"BENCH", "DEEP_BENCH"}:
        return "risky"
    if float(role_fit.get("STARTER", 0.0)) >= 0.5 and float(role_fit.get("CORE_PLAYER", 0.0)) >= 0.5 and tier == "CORE":
        return "stable"
    if tier == "ROTATION" and float(role_fit.get("STARTER", 0.0)) >= 0.45:
        return "volatile"
    return "volatile"


def star_signal_from_role_fit(role_fit):
    return (
        0.44 * float(role_fit.get("SCORER", 0.0))
        + 0.24 * float(role_fit.get("PLAYMAKER", 0.0))
        + 0.20 * float(role_fit.get("CORE_PLAYER", 0.0))
        + 0.12 * float(role_fit.get("CLOSER", 0.0))
    )


def playoff_closure_priority_tier(core):
    rf = core["role_fit"]
    pp = core["player_profile"]
    star = star_signal_from_role_fit(rf)
    ls = float(pp.get("LIKELY_STARTER", 0.0))
    lc = float(pp.get("LIKELY_CLOSER", 0.0))
    ann = float(pp.get("ANNOUNCED_STARTER", 0.0))
    rs = float(pp.get("RECENT_START_RATE", 0.0))
    os_ = float(pp.get("OPEN_LINEUP_SCORE", 0.0))
    cs_ = float(pp.get("CLOSE_LINEUP_SCORE", 0.0))
    tier_s = str(pp.get("ROTATION_TIER", "")).upper()
    stab = float(pp.get("ROLE_STABILITY_SCORE", 0.75))
    fake_risk = float(pp.get("FAKE_STARTER_RISK", 0.0))
    u_rank = int(pp.get("USAGE_RANK_TEAM", 99))
    
    # Penalize fake starters and pure role players from outranking stars
    # True offensive focal points (u_rank <= 3) are exempt from stability/fake_risk overrides
    if (fake_risk >= 0.50 or stab < 0.60 or u_rank >= 5) and u_rank > 3:
        if star >= 0.65:
            return 3  # Downrank fake stars and 5th-option role players out of T1/T2
            
    if star >= 0.68 and u_rank <= 3 and (ls >= 0.5 or lc >= 0.5 or ann >= 0.5) and fake_risk < 0.45:
        return 1
    if star >= 0.605 and u_rank <= 4 and (ls >= 0.5 or ann >= 0.5 or rs >= 0.42) and fake_risk < 0.55:
        return 2
    if tier_s == "CORE" and u_rank <= 4 and (os_ >= 0.62 or ann >= 0.5) and fake_risk < 0.55:
        return 2
    if tier_s == "CORE" and u_rank <= 5 and (lc >= 0.5 or cs_ >= 0.55) and fake_risk < 0.60:
        return 2
    if tier_s == "CORE":
        return 3 if fake_risk < 0.70 else 4
    if lc >= 0.5 or cs_ >= 0.58 or rs >= 0.50:
        return 3 if fake_risk < 0.70 else 4
    if tier_s == "ROTATION":
        return 4
    if tier_s in {"BENCH", "DEEP_BENCH"}:
        return 5
    return 4


def playoff_primary_usage_hierarchy(role_fit):
    """On-ball / scoring load — spacing specialists stay lower without playmaking pull."""
    rf = role_fit or {}
    return (
        0.40 * float(rf.get("SCORER", 0.0))
        + 0.36 * float(rf.get("PLAYMAKER", 0.0))
        + 0.24 * float(rf.get("CORE_PLAYER", 0.0))
    )


def playoff_high_minute_engine_eligible(core):
    """
    True only for alpha / primary playoff engines allowed to sit 37–40+ after closure.
    Secondary guards, wings, and specialists are capped lower via playoff_tier_cap.
    """
    rf = core.get("role_fit") or {}
    pp = core.get("player_profile") or {}
    star = star_signal_from_role_fit(rf)
    t = playoff_closure_priority_tier(core)
    ur = int(pp.get("MINUTE_RANK_TEAM", 99))
    hier = playoff_primary_usage_hierarchy(rf)
    mt = str(pp.get("ROTATION_TIER", "")).upper()
    closer_only = float(rf.get("CLOSER", 0.0)) >= 0.48 and float(rf.get("SCORER", 0.0)) < 0.52
    if t > 2:
        return False
    if ur > 5 and not (star >= 0.685 and t <= 2):
        return False
    if closer_only and star < 0.70:
        return False
    if mt not in {"CORE", ""} and star < 0.68:
        return False
    if star < 0.635:
        return False
    if star >= 0.675 and hier >= 0.38 and ur <= 3:
        return True
    if star >= 0.655 and hier >= 0.42 and ur <= 3:
        return True
    if star >= 0.645 and hier >= 0.45 and ur <= 4:
        return True
    return False


def assign_playoff_role_label(core):
    pp = core["player_profile"]
    t = playoff_closure_priority_tier(core)
    star = star_signal_from_role_fit(core["role_fit"])
    ls = float(pp.get("LIKELY_STARTER", 0.0))
    lc = float(pp.get("LIKELY_CLOSER", 0.0))
    ann = float(pp.get("ANNOUNCED_STARTER", 0.0))
    pre = float(core.get("mean_minutes_pre_closure") or pp.get("MINUTES", 0) or 0)
    mrank = int(pp.get("MINUTE_RANK_TEAM", 99))

    if star >= 0.67 and t <= 2:
        return "playoff_engine"
    if ann >= 0.5 or (ls >= 0.5 and t <= 3):
        return "core_starter"
    if lc >= 0.5 and ls < 0.5 and t <= 4:
        return "core_closer"
    if t == 5 or (mrank >= 12 and pre < 6.0):
        return "emergency_only" if pre < 3.5 else "fringe"
    if t == 4 or (pre >= 10.0 and mrank <= 10):
        return "rotation"
    if t <= 3:
        return "rotation"
    return "fringe"


def apply_playoff_counting_stat_calibration(stat_means, role_fit, playoff_role_label, closed_minutes):
    load = max(0.0, (closed_minutes / 36.0) - 1.0)
    rf = role_fit
    role = playoff_role_label or ""
    if role == "playoff_engine":
        stat_means["PTS"] *= 1.0 + 0.032 + 0.042 * load
        stat_means["AST"] *= 1.0 + (0.022 + 0.032 * load) * float(rf.get("PLAYMAKER", 0.0))
        stat_means["REB"] *= 1.0 + (0.018 + 0.028 * load) * float(rf.get("REBOUNDER", 0.0))
        stat_means["STL"] *= 1.0 + 0.026 + 0.024 * load
        stat_means["BLK"] *= 1.0 + (0.022 + 0.024 * load) * float(rf.get("RIM", 0.0))
        stat_means["FG3M"] *= 1.0 + (0.022 + 0.024 * load) * float(rf.get("SHOOTER", 0.0))
    elif role == "core_starter":
        stat_means["PTS"] *= 1.0 + 0.024 + 0.038 * load
        stat_means["AST"] *= 1.0 + 0.015 * float(rf.get("PLAYMAKER", 0.0))
        stat_means["REB"] *= 1.0 + 0.013 * float(rf.get("REBOUNDER", 0.0))
        stat_means["STL"] *= 1.0 + 0.019
        stat_means["BLK"] *= 1.0 + 0.015 * float(rf.get("RIM", 0.0))
        stat_means["FG3M"] *= 1.0 + 0.018 * float(rf.get("SHOOTER", 0.0))
    elif role == "core_closer":
        stat_means["PTS"] *= 1.0 + 0.018 + 0.042 * load
        stat_means["FG3M"] *= 1.0 + 0.015 * float(rf.get("SHOOTER", 0.0))
        stat_means["STL"] *= 1.0 + 0.015
    elif role in {"fringe", "emergency_only"}:
        stat_means["PTS"] *= 0.985
        stat_means["FG3M"] *= 0.98


PLAYOFF_ROLE_STAT_SHARE_BASE = {
    "playoff_engine": {"PTS": 1.095, "AST": 1.065, "REB": 1.055, "FG3M": 1.085, "STL": 1.06, "BLK": 1.055},
    "core_starter": {"PTS": 1.055, "AST": 1.04, "REB": 1.035, "FG3M": 1.048, "STL": 1.028, "BLK": 1.028},
    "core_closer": {"PTS": 1.075, "AST": 0.965, "REB": 1.025, "FG3M": 1.085, "STL": 1.04, "BLK": 1.02},
    "rotation": {"PTS": 1.01, "AST": 1.01, "REB": 1.01, "FG3M": 1.01, "STL": 1.0, "BLK": 1.0},
    "fringe": {"PTS": 0.83, "AST": 0.84, "REB": 0.87, "FG3M": 0.78, "STL": 0.91, "BLK": 0.89},
    "emergency_only": {"PTS": 0.70, "AST": 0.72, "REB": 0.76, "FG3M": 0.65, "STL": 0.87, "BLK": 0.84},
}


def _playoff_injury_opportunity_factor(role, factor_if_eligible):
    if role in {"fringe", "emergency_only"}:
        return 1.0
    return float(factor_if_eligible)


def playoff_stat_share_multiplier_for_core(core, stat):
    role = str(core.get("playoff_role_label") or "rotation").strip()
    base_map = PLAYOFF_ROLE_STAT_SHARE_BASE.get(role, PLAYOFF_ROLE_STAT_SHARE_BASE["rotation"])
    m = float(base_map.get(stat, 1.0))
    rf = core.get("role_fit") or {}
    tc = core.get("team_context") or {}
    rl = tc.get("ROLE_LOSSES") or {}
    u = float(min(float(tc.get("USAGE_LOSS", 0.0) or 0.0), 1.55))

    if stat == "PTS":
        m *= 1.0 + min(0.11, 0.048 * u)
        m *= _playoff_injury_opportunity_factor(
            role,
            1.0 + min(0.10, 0.036 * float(rl.get("SCORER", 0.0))) * float(rf.get("SCORER", 0.0)),
        )
    elif stat == "AST":
        creator_gate = 0.32 + 0.68 * float(rf.get("PLAYMAKER", 0.0))
        m *= 1.0 + min(0.10, 0.045 * u) * creator_gate
        m *= _playoff_injury_opportunity_factor(
            role,
            1.0 + min(0.10, 0.042 * float(rl.get("PLAYMAKER", 0.0))) * float(rf.get("PLAYMAKER", 0.0)),
        )
    elif stat == "REB":
        m *= _playoff_injury_opportunity_factor(
            role,
            1.0 + min(0.11, 0.038 * float(rl.get("REBOUNDER", 0.0))) * float(rf.get("REBOUNDER", 0.0)),
        )
    elif stat == "FG3M":
        m *= 1.0 + min(0.095, 0.038 * u) * (0.38 + 0.62 * float(rf.get("SHOOTER", 0.0)))
        m *= _playoff_injury_opportunity_factor(
            role,
            1.0 + min(0.085, 0.032 * float(rl.get("SHOOTER", 0.0))) * float(rf.get("SHOOTER", 0.0)),
        )
    elif stat == "STL":
        if role in {"playoff_engine", "core_closer"}:
            m *= 1.0 + min(0.05, 0.022 * u)
        elif role in {"fringe", "emergency_only"}:
            m *= 0.93
    elif stat == "BLK":
        m *= _playoff_injury_opportunity_factor(
            role,
            1.0 + min(0.09, 0.032 * float(rl.get("RIM", 0.0))) * float(rf.get("RIM", 0.0)),
        )
        if role in {"fringe", "emergency_only"}:
            m *= 0.92

    return max(0.04, float(m))


def _redistribute_team_stat_preserving_total(group, stat_key):
    vals = np.array([max(0.0, float(c["stat_means"].get(stat_key, 0.0))) for c in group], dtype=float)
    total = float(np.sum(vals))
    if total < 1e-9:
        return
    mults = np.array([playoff_stat_share_multiplier_for_core(c, stat_key) for c in group], dtype=float)
    adj = vals * mults
    s = float(np.sum(adj))
    if s < 1e-12:
        return
    adj = adj * (total / s)
    for i, c in enumerate(group):
        c["stat_means"][stat_key] = float(adj[i])


def apply_playoff_team_stat_share_redistribution(group):
    if not group:
        return
    for stat_key in STAT_TARGETS:
        _redistribute_team_stat_preserving_total(group, stat_key)


PLAYOFF_ROLE_SHOT_VOLUME_BASE = {
    "playoff_engine": {"FGA": 1.095, "FGM": 1.09, "FTA": 1.12, "FTM": 1.105},
    "core_starter": {"FGA": 1.052, "FGM": 1.048, "FTA": 1.075, "FTM": 1.062},
    "core_closer": {"FGA": 1.072, "FGM": 1.065, "FTA": 1.10, "FTM": 1.085},
    "rotation": {"FGA": 1.01, "FGM": 1.01, "FTA": 1.02, "FTM": 1.02},
    "fringe": {"FGA": 0.80, "FGM": 0.79, "FTA": 0.76, "FTM": 0.76},
    "emergency_only": {"FGA": 0.66, "FGM": 0.65, "FTA": 0.60, "FTM": 0.60},
}


def _playoff_shot_injury_factor(role, factor_if_eligible):
    if role in {"fringe", "emergency_only"}:
        return 1.0
    return float(factor_if_eligible)


def playoff_shot_volume_multiplier_for_core(core, key):
    role = str(core.get("playoff_role_label") or "rotation").strip()
    base_map = PLAYOFF_ROLE_SHOT_VOLUME_BASE.get(role, PLAYOFF_ROLE_SHOT_VOLUME_BASE["rotation"])
    m = float(base_map.get(key, 1.0))
    rf = core.get("role_fit") or {}
    tc = core.get("team_context") or {}
    rl = tc.get("ROLE_LOSSES") or {}
    u = float(min(float(tc.get("USAGE_LOSS", 0.0) or 0.0), 1.55))

    if key == "FGA":
        m *= 1.0 + min(0.11, 0.046 * u)
        m *= _playoff_shot_injury_factor(
            role,
            1.0 + min(0.11, 0.042 * float(rl.get("SCORER", 0.0))) * float(rf.get("SCORER", 0.0)),
        )
        m *= _playoff_shot_injury_factor(
            role,
            1.0 + min(0.075, 0.03 * float(rl.get("SHOOTER", 0.0))) * float(rf.get("SHOOTER", 0.0)),
        )
    elif key == "FGM":
        m *= 1.0 + min(0.10, 0.042 * u)
        m *= _playoff_shot_injury_factor(
            role,
            1.0 + min(0.10, 0.04 * float(rl.get("SCORER", 0.0))) * float(rf.get("SCORER", 0.0)),
        )
    elif key == "FTA":
        m *= 1.0 + min(0.13, 0.052 * u) * (0.45 + 0.55 * float(rf.get("SCORER", 0.0)))
        m *= _playoff_shot_injury_factor(
            role,
            1.0 + min(0.095, 0.036 * float(rl.get("SCORER", 0.0))) * float(rf.get("SCORER", 0.0)),
        )
        m *= _playoff_shot_injury_factor(
            role,
            1.0 + min(0.075, 0.03 * float(rl.get("RIM", 0.0))) * float(rf.get("RIM", 0.0)),
        )
    elif key == "FTM":
        m *= 1.0 + min(0.12, 0.048 * u) * (0.42 + 0.58 * float(rf.get("SCORER", 0.0)))
        m *= _playoff_shot_injury_factor(
            role,
            1.0 + min(0.085, 0.034 * float(rl.get("SCORER", 0.0))) * float(rf.get("SCORER", 0.0)),
        )

    return max(0.04, float(m))


def _redistribute_team_rate_preserving_total_fn(group, key, multiplier_fn):
    if not group or not all(c.get("rate_means") for c in group):
        return
    vals = np.array([max(0.0, float(c["rate_means"].get(key, 0.0))) for c in group], dtype=float)
    total = float(np.sum(vals))
    if total < 1e-12:
        return
    mults = np.array([max(0.04, float(multiplier_fn(c))) for c in group], dtype=float)
    adj = vals * mults
    s = float(np.sum(adj))
    if s < 1e-12:
        return
    adj = adj * (total / s)
    for i, c in enumerate(group):
        c["rate_means"][key] = float(adj[i])


def _repair_fgm_within_fga_team(group, eps=0.04, max_iter=32):
    fga = np.array([max(0.0, float(c["rate_means"]["FGA"])) for c in group], dtype=float)
    fgm = np.array([max(0.0, float(c["rate_means"]["FGM"])) for c in group], dtype=float)
    target = float(np.sum(fgm))
    cap_max = np.maximum(fga - eps, 0.0)
    new = np.minimum(fgm, cap_max)
    for _ in range(max_iter):
        deficit = target - float(np.sum(new))
        if deficit <= 1e-9:
            break
        headroom = np.maximum(0.0, cap_max - new)
        hsum = float(np.sum(headroom))
        if hsum < 1e-12:
            break
        new = new + deficit * (headroom / hsum)
        new = np.minimum(new, cap_max)
    for i, c in enumerate(group):
        c["rate_means"]["FGM"] = float(max(0.0, new[i]))


def _repair_ftm_within_fta_team(group, eps=0.035, max_iter=32):
    fta = np.array([max(0.0, float(c["rate_means"]["FTA"])) for c in group], dtype=float)
    ftm = np.array([max(0.0, float(c["rate_means"]["FTM"])) for c in group], dtype=float)
    target = float(np.sum(ftm))
    cap_max = np.maximum(fta - eps, 0.0)
    new = np.minimum(ftm, cap_max)
    for _ in range(max_iter):
        deficit = target - float(np.sum(new))
        if deficit <= 1e-9:
            break
        headroom = np.maximum(0.0, cap_max - new)
        hsum = float(np.sum(headroom))
        if hsum < 1e-12:
            break
        new = new + deficit * (headroom / hsum)
        new = np.minimum(new, cap_max)
    for i, c in enumerate(group):
        c["rate_means"]["FTM"] = float(max(0.0, new[i]))


def apply_playoff_team_shot_volume_redistribution(group):
    if not group or not all(c.get("rate_means") for c in group):
        return
    for key in ("FGA", "FTA", "FGM", "FTM"):
        def _shot_mult(c, k=key):
            return playoff_shot_volume_multiplier_for_core(c, k)

        _redistribute_team_rate_preserving_total_fn(group, key, _shot_mult)
    _repair_fgm_within_fga_team(group)
    _repair_ftm_within_fta_team(group)
    fg3 = np.array([max(0.0, float(c["stat_means"]["FG3M"])) for c in group], dtype=float)
    fgm = np.array([max(0.0, float(c["rate_means"]["FGM"])) for c in group], dtype=float)
    fg3 = np.minimum(fg3, fgm)
    fg2m = np.maximum(0.0, fgm - fg3)
    fga = np.array([max(0.0, float(c["rate_means"]["FGA"])) for c in group], dtype=float)
    fg3a = np.array([max(0.0, float(c["rate_means"]["FG3A"])) for c in group], dtype=float)
    fg2a = np.maximum(0.0, fga - fg3a)
    for i, c in enumerate(group):
        c["rate_means"]["FG2M"] = float(fg2m[i])
        c["rate_means"]["FG2A"] = float(max(fg2a[i], fg2m[i], 0.0))


def apply_playoff_pts_shot_coherence(group, blend=0.32):
    if not group or not all(c.get("rate_means") for c in group):
        return
    fg3 = np.array([max(0.0, float(c["stat_means"]["FG3M"])) for c in group], dtype=float)
    fgm = np.array([max(0.0, float(c["rate_means"]["FGM"])) for c in group], dtype=float)
    ftm = np.array([max(0.0, float(c["rate_means"]["FTM"])) for c in group], dtype=float)
    fg3 = np.minimum(fg3, fgm)
    fg2m = np.maximum(0.0, fgm - fg3)
    implied = 2.0 * fg2m + 3.0 * fg3 + ftm
    pts_old = np.array([max(0.0, float(c["stat_means"]["PTS"])) for c in group], dtype=float)
    total = float(np.sum(pts_old))
    if total < 1e-9:
        return
    pts_mix = (1.0 - blend) * pts_old + blend * implied
    s = float(np.sum(pts_mix))
    if s < 1e-12:
        return
    pts_mix = pts_mix * (total / s)
    for i, c in enumerate(group):
        c["stat_means"]["PTS"] = float(max(0.25, pts_mix[i]))


def _redistribute_team_stat_preserving_total_fn(group, stat_key, multiplier_fn):
    if not group:
        return
    vals = np.array([max(0.0, float(c["stat_means"].get(stat_key, 0.0))) for c in group], dtype=float)
    total = float(np.sum(vals))
    if total < 1e-9:
        return
    mults = np.array([max(0.04, float(multiplier_fn(c))) for c in group], dtype=float)
    adj = vals * mults
    s = float(np.sum(adj))
    if s < 1e-12:
        return
    adj = adj * (total / s)
    for i, c in enumerate(group):
        c["stat_means"][stat_key] = float(adj[i])


PLAYOFF_ROLE_AST_CREATION_BASE = {
    "playoff_engine": 1.08,
    "core_starter": 1.045,
    "core_closer": 0.97,
    "rotation": 1.0,
    "fringe": 0.79,
    "emergency_only": 0.63,
}


def playoff_ast_creation_multiplier_for_core(core):
    role = str(core.get("playoff_role_label") or "rotation").strip()
    m = float(PLAYOFF_ROLE_AST_CREATION_BASE.get(role, PLAYOFF_ROLE_AST_CREATION_BASE["rotation"]))
    rf = core.get("role_fit") or {}
    tc = core.get("team_context") or {}
    rl = tc.get("ROLE_LOSSES") or {}
    pm = float(rf.get("PLAYMAKER", 0.0))
    scr = float(rf.get("SCORER", 0.0))
    u = float(min(float(tc.get("USAGE_LOSS", 0.0) or 0.0), 1.55))
    m *= 0.84 + 0.50 * (pm ** 1.05)
    finisher = max(0.0, scr - pm - 0.06)
    m *= 1.0 / (1.0 + 0.38 * finisher)
    if 0.30 <= pm <= 0.70:
        m *= 1.02 + 0.024 * (1.0 - abs(pm - 0.50) / 0.50)
    m *= 1.0 + min(0.09, 0.042 * u) * (0.40 + 0.60 * pm)
    m *= _playoff_injury_opportunity_factor(
        role,
        1.0 + min(0.12, 0.048 * float(rl.get("PLAYMAKER", 0.0))) * pm,
    )
    return max(0.04, float(m))


def apply_playoff_assist_creation_redistribution(group):
    if not group:
        return
    _redistribute_team_stat_preserving_total_fn(group, "AST", playoff_ast_creation_multiplier_for_core)


PLAYOFF_ROLE_FG3A_BASE = {
    "playoff_engine": 1.085,
    "core_starter": 1.04,
    "core_closer": 1.075,
    "rotation": 1.01,
    "fringe": 0.77,
    "emergency_only": 0.63,
}


def playoff_fg3a_multiplier_for_core(core):
    role = str(core.get("playoff_role_label") or "rotation").strip()
    m = float(PLAYOFF_ROLE_FG3A_BASE.get(role, PLAYOFF_ROLE_FG3A_BASE["rotation"]))
    rf = core.get("role_fit") or {}
    tc = core.get("team_context") or {}
    rl = tc.get("ROLE_LOSSES") or {}
    sh = float(rf.get("SHOOTER", 0.0))
    pm = float(rf.get("PLAYMAKER", 0.0))
    u = float(min(float(tc.get("USAGE_LOSS", 0.0) or 0.0), 1.55))
    m *= 1.0 + min(0.10, 0.04 * u) * (0.34 + 0.66 * sh)
    m *= 1.0 + min(0.048, 0.022 * u) * (0.30 + 0.70 * pm)
    m *= _playoff_injury_opportunity_factor(
        role,
        1.0 + min(0.11, 0.037 * float(rl.get("SHOOTER", 0.0))) * sh,
    )
    return max(0.04, float(m))


def _repair_fg3a_within_fga_team(group, eps=0.035, max_iter=32):
    fga = np.array([max(0.0, float(c["rate_means"]["FGA"])) for c in group], dtype=float)
    fg3a = np.array([max(0.0, float(c["rate_means"]["FG3A"])) for c in group], dtype=float)
    target = float(np.sum(fg3a))
    cap_max = np.maximum(fga - eps, 0.0)
    new = np.minimum(fg3a, cap_max)
    for _ in range(max_iter):
        deficit = target - float(np.sum(new))
        if deficit <= 1e-9:
            break
        headroom = np.maximum(0.0, cap_max - new)
        hsum = float(np.sum(headroom))
        if hsum < 1e-12:
            break
        new = new + deficit * (headroom / hsum)
        new = np.minimum(new, cap_max)
    for i, c in enumerate(group):
        c["rate_means"]["FG3A"] = float(max(0.0, new[i]))


def apply_playoff_team_fg3a_concentration(group):
    if not group or not all(c.get("rate_means") for c in group):
        return
    _redistribute_team_rate_preserving_total_fn(group, "FG3A", playoff_fg3a_multiplier_for_core)
    _repair_fg3a_within_fga_team(group)
    for c in group:
        fga = max(0.0, float(c["rate_means"]["FGA"]))
        fg3a = max(0.0, float(c["rate_means"]["FG3A"]))
        fg2m = max(0.0, float(c["rate_means"]["FG2M"]))
        c["rate_means"]["FG2A"] = float(max(fga - fg3a, fg2m, 0.0))


PLAYOFF_ROLE_TOV_POSSESSION_BASE = {
    "playoff_engine": 1.10,
    "core_starter": 1.048,
    "core_closer": 1.03,
    "rotation": 0.99,
    "fringe": 0.74,
    "emergency_only": 0.60,
}


def playoff_tov_possession_multiplier_for_core(core):
    role = str(core.get("playoff_role_label") or "rotation").strip()
    m = float(PLAYOFF_ROLE_TOV_POSSESSION_BASE.get(role, PLAYOFF_ROLE_TOV_POSSESSION_BASE["rotation"]))
    rf = core.get("role_fit") or {}
    tc = core.get("team_context") or {}
    rl = tc.get("ROLE_LOSSES") or {}
    pm = float(rf.get("PLAYMAKER", 0.0))
    scr = float(rf.get("SCORER", 0.0))
    u = float(min(float(tc.get("USAGE_LOSS", 0.0) or 0.0), 1.55))
    touch = 0.44 * scr + 0.56 * pm
    m *= 1.0 + min(0.10, 0.044 * u) * touch
    m *= 0.945 + 0.20 * pm + 0.17 * scr
    m *= _playoff_injury_opportunity_factor(
        role,
        1.0 + min(0.085, 0.032 * float(rl.get("PLAYMAKER", 0.0))) * (0.45 + 0.55 * pm),
    )
    return max(0.04, float(m))


def apply_playoff_team_tov_possession_redistribution(group):
    if not group or not all(c.get("rate_means") for c in group):
        return
    if not all("TOV" in c["rate_means"] for c in group):
        return
    _redistribute_team_rate_preserving_total_fn(group, "TOV", playoff_tov_possession_multiplier_for_core)


PLAYOFF_USAGE_TOUCH_REFINE_BASE = {
    "playoff_engine": 1.018,
    "core_starter": 1.012,
    "core_closer": 1.018,
    "rotation": 1.0,
    "fringe": 0.942,
    "emergency_only": 0.892,
}


def playoff_usage_touch_multiplier_for_core(core, key):
    role = str(core.get("playoff_role_label") or "rotation").strip()
    m = float(PLAYOFF_USAGE_TOUCH_REFINE_BASE.get(role, PLAYOFF_USAGE_TOUCH_REFINE_BASE["rotation"]))
    rf = core.get("role_fit") or {}
    touch = (
        0.46 * float(rf.get("SCORER", 0.0))
        + 0.40 * float(rf.get("PLAYMAKER", 0.0))
        + 0.14 * float(rf.get("SHOOTER", 0.0))
    )
    fin = max(0.0, float(rf.get("SCORER", 0.0)) - float(rf.get("PLAYMAKER", 0.0)))
    m *= 1.0 + 0.048 * touch - 0.038 * fin
    if key == "FTA":
        m *= 1.0 + 0.034 * float(rf.get("SCORER", 0.0))
    return max(0.04, float(m))


def apply_playoff_team_offensive_usage_refinement(group):
    if not group or not all(c.get("rate_means") for c in group):
        return
    for key in ("FGA", "FTA"):
        def _usage_mult(c, k=key):
            return playoff_usage_touch_multiplier_for_core(c, k)

        _redistribute_team_rate_preserving_total_fn(group, key, _usage_mult)
    _repair_fgm_within_fga_team(group)
    _repair_ftm_within_fta_team(group)
    for c in group:
        fga = max(0.0, float(c["rate_means"]["FGA"]))
        fg3a = max(0.0, float(c["rate_means"]["FG3A"]))
        fg2m = max(0.0, float(c["rate_means"]["FG2M"]))
        c["rate_means"]["FG2A"] = float(max(fga - fg3a, fg2m, 0.0))


def compute_playoff_team_lineup_chemistry(group):
    n = len(group)
    if n == 0:
        return {
            "creator_supply": 0.5,
            "finisher_weight": 0.5,
            "stretch_idx": 0.35,
            "rim_wall": 0.35,
            "top5_pm_density": 0.45,
            "lineup_cred": 0.7,
        }
    mins = np.array([max(0.0, float(c["mean_minutes"])) for c in group])
    tot_m = float(np.sum(mins))
    if tot_m < 1e-6:
        tot_m = 1.0
    w = mins / tot_m
    creators = np.array([float(c["role_fit"].get("PLAYMAKER", 0.0)) for c in group])
    scorers = np.array([float(c["role_fit"].get("SCORER", 0.0)) for c in group])
    shooters = np.array([float(c["role_fit"].get("SHOOTER", 0.0)) for c in group])
    rebounders = np.array([float(c["role_fit"].get("REBOUNDER", 0.0)) for c in group])
    rims = np.array([float(c["role_fit"].get("RIM", 0.0)) for c in group])
    creator_supply = float(np.sum(w * creators))
    finisher_weight = float(np.sum(w * scorers))
    stretch_idx = float(np.sum(w * shooters * (1.0 - 0.35 * rebounders)))
    rim_wall = float(np.sum(w * np.clip(rims + rebounders - 0.12, 0.0, None)))
    idx = np.argsort(-mins)
    top5_m = float(np.sum(mins[idx[:5]]))
    t5pm = float(np.sum(mins[idx[:5]] * creators[idx[:5]])) / max(top5_m, 1e-6)
    open_line = np.array([float(c["player_profile"].get("OPEN_LINEUP_SCORE", 0.5)) for c in group])
    close_line = np.array([float(c["player_profile"].get("CLOSE_LINEUP_SCORE", 0.5)) for c in group])
    lineup_cred = float(np.sum(w * (0.55 * open_line + 0.45 * close_line)))
    return {
        "creator_supply": creator_supply,
        "finisher_weight": finisher_weight,
        "stretch_idx": stretch_idx,
        "rim_wall": rim_wall,
        "top5_pm_density": t5pm,
        "lineup_cred": lineup_cred,
    }


def compute_playoff_opponent_style_factors(features, league_defaults):
    neutral = {
        "ast_env": 1.0,
        "reb_env": 1.0,
        "pts_env": 1.0,
        "fg3_env": 1.0,
        "tov_press": 1.0,
        "blk_env": 1.0,
    }
    if not features or not league_defaults:
        return neutral
    lap = max(float(league_defaults.get("OPP_PTS_ALLOWED", 110.0)), 1.0)
    laa = max(float(league_defaults.get("OPP_AST_ALLOWED", 24.0)), 0.1)
    lar = max(float(league_defaults.get("OPP_REB_ALLOWED", 43.0)), 0.1)
    pa = float(features.get("OPP_PTS_ALLOWED", lap))
    aa = float(features.get("OPP_AST_ALLOWED", laa))
    ra = float(features.get("OPP_REB_ALLOWED", lar))
    pts_z = (pa / lap) - 1.0
    ast_z = (aa / laa) - 1.0
    reb_z = (ra / lar) - 1.0
    return {
        "ast_env": float(np.clip(1.0 + 0.035 * ast_z, 0.972, 1.032)),
        "reb_env": float(np.clip(1.0 + 0.032 * reb_z, 0.973, 1.031)),
        "pts_env": float(np.clip(1.0 + 0.024 * pts_z, 0.975, 1.028)),
        "fg3_env": float(np.clip(1.0 + 0.028 * pts_z + 0.015 * ast_z, 0.972, 1.033)),
        "tov_press": float(np.clip(1.0 + 0.027 * (-ast_z), 0.973, 1.031)),
        "blk_env": float(np.clip(1.0 - 0.021 * pts_z, 0.972, 1.028)),
    }


def playoff_lineup_matchup_multiplier_for_core(core, key, chemistry, style):
    rf = core.get("role_fit") or {}
    tc = core.get("team_context") or {}
    rl = tc.get("ROLE_LOSSES") or {}
    pp = core.get("player_profile") or {}
    role = str(core.get("playoff_role_label") or "rotation").strip()
    pm = float(rf.get("PLAYMAKER", 0.0))
    scr = float(rf.get("SCORER", 0.0))
    sh = float(rf.get("SHOOTER", 0.0))
    reb = float(rf.get("REBOUNDER", 0.0))
    rim = float(rf.get("RIM", 0.0))
    cs = chemistry["creator_supply"]
    stretch = chemistry["stretch_idx"]
    rw = chemistry["rim_wall"]
    lc = chemistry["lineup_cred"]
    ls = float(pp.get("LIKELY_STARTER", 0.0))
    cl = float(pp.get("LIKELY_CLOSER", 0.0))
    floor_cred = float(np.clip(0.30 + 0.46 * ls + 0.40 * cl, 0.15, 1.2))
    bench_drag = 1.0
    if role in {"fringe", "emergency_only"} or (ls < 0.5 and cl < 0.5):
        bench_drag = 1.0 - 0.075 * max(0.0, 0.58 - floor_cred) * (1.0 - 0.32 * pm - 0.22 * scr)
        bench_drag = float(np.clip(bench_drag, 0.87, 1.0))
    creator_loss = float(rl.get("PLAYMAKER", 0.0))
    scorer_loss = float(rl.get("SCORER", 0.0))
    reb_loss = float(rl.get("REBOUNDER", 0.0))
    m = 1.0
    if key == "AST":
        m *= style["ast_env"]
        m *= 1.0 + 0.098 * pm * (0.52 + 0.48 * cs)
        m *= 1.0 - 0.125 * max(0.0, 0.36 - pm) * max(0.0, cs - 0.46)
        m *= 1.0 + 0.068 * creator_loss * (0.58 + 0.42 * pm)
        m *= 1.0 + 0.045 * creator_loss * max(0.0, 0.52 - pm) * (0.32 + 0.68 * scr)
        m *= float(np.clip(0.935 + 0.12 * lc, 0.92, 1.08))
        if pm < 0.42:
            m *= bench_drag
    elif key == "PTS":
        m *= style["pts_env"]
        m *= 1.0 + 0.078 * scr * min(0.17, max(0.0, cs - 0.405))
        m *= 1.0 + 0.042 * scorer_loss * scr * (0.40 + 0.60 * (1.0 - pm))
        m *= bench_drag
    elif key == "REB":
        m *= style["reb_env"]
        m *= 1.0 - 0.058 * stretch * reb * (1.0 - 0.48 * sh)
        m *= 1.0 + 0.048 * stretch * sh * (0.22 + 0.78 * reb)
        m *= 1.0 + 0.040 * reb_loss * (0.50 + 0.50 * reb)
        m *= 1.0 + 0.030 * rw * reb * (0.50 + 0.50 * rim)
    elif key == "FG3M":
        m *= style["fg3_env"]
        m *= 1.0 + 0.062 * sh * min(0.15, max(0.0, cs - 0.398))
        m *= bench_drag
    elif key == "STL":
        m *= float(np.clip(1.0 + 0.018 * (style["tov_press"] - 1.0), 0.97, 1.03))
    elif key == "BLK":
        m *= style["blk_env"]
        m *= 0.935 + 0.17 * rim + 0.065 * rw
    elif key == "FGA":
        m *= style["pts_env"] * (1.0 + 0.052 * scr * max(0.0, cs - 0.41)) * bench_drag
    elif key == "FGM":
        m *= style["pts_env"] * (1.0 + 0.050 * scr * max(0.0, cs - 0.41)) * bench_drag
    elif key == "FTA":
        m *= style["pts_env"] * (1.0 + 0.042 * scr) * bench_drag
    elif key == "FTM":
        m *= style["pts_env"] * (1.0 + 0.040 * scr) * bench_drag
    elif key == "FG3A":
        m *= style["fg3_env"] * (1.0 + 0.058 * sh * max(0.0, cs - 0.398)) * bench_drag
    elif key == "TOV":
        m *= style["tov_press"]
        m *= 1.0 + 0.038 * pm * max(0.0, style["tov_press"] - 1.0)
        m *= 1.0 + 0.024 * creator_loss * pm
    else:
        m = 1.0
    m = 1.0 + (m - 1.0) * PLAYOFF_LINEUP_MATCHUP_DAMP
    return max(0.04, float(m))


def attach_playoff_diagnostics_to_cores(group, chemistry, style):
    if not group:
        return
    env_mid = (style["pts_env"] + style["ast_env"] + style["reb_env"]) / 3.0
    for c in group:
        pre = c.get("mean_minutes_pre_closure")
        post = float(c["mean_minutes"])
        delta = (post - float(pre)) if pre is not None else 0.0
        tier = playoff_closure_priority_tier(c)
        role = str(c.get("playoff_role_label") or "")
        closure_reason = f"T{tier}|d{delta:+.1f}|{role[:18]}"[:80]
        u_loss = float((c.get("team_context") or {}).get("USAGE_LOSS", 0.0))
        w_red = playoff_redistribution_weight(c)
        usage_conc = float(np.clip(100 * min(1.0, w_red / 2.8) * (0.62 + 0.38 * min(u_loss, 1.2)), 0, 100))
        creator_ctx = float(np.clip(100 * chemistry["creator_supply"], 0, 100))
        lineup_cred_100 = float(np.clip(100 * chemistry["lineup_cred"], 0, 100))
        matchup_env = float(np.clip(50 + 850 * (env_mid - 1.0), 0, 100))
        m_ast = playoff_lineup_matchup_multiplier_for_core(c, "AST", chemistry, style)
        m_pts = playoff_lineup_matchup_multiplier_for_core(c, "PTS", chemistry, style)
        lm_layer = (m_ast + m_pts) / 2.0
        lineup_layer_score = float(np.clip(50 + 85 * (lm_layer - 1.0), 0, 100))
        composite = float(
            np.clip(
                0.26 * usage_conc
                + 0.26 * creator_ctx
                + 0.20 * lineup_cred_100
                + 0.14 * matchup_env
                + 0.14 * lineup_layer_score,
                0,
                100,
            )
        )
        c["playoff_diagnostics"] = {
            "PLAYOFF_TRACE_CLOSURE": closure_reason,
            "PLAYOFF_TRACE_USAGE_CONC": round(usage_conc, 2),
            "PLAYOFF_TRACE_CREATOR_CTX": round(creator_ctx, 2),
            "PLAYOFF_TRACE_LINEUP_CRED": round(lineup_cred_100, 2),
            "PLAYOFF_TRACE_MATCHUP_ENV": round(matchup_env, 2),
            "PLAYOFF_TRACE_LINEUP_LAYER": round(lineup_layer_score, 2),
            "PLAYOFF_TRACE_COMPOSITE": round(composite, 2),
        }


def apply_playoff_lineup_and_matchup_redistribution(group, chemistry=None, style=None):
    if not group:
        return
    league_defaults = group[0].get("league_defaults") or {}
    if chemistry is None:
        chemistry = compute_playoff_team_lineup_chemistry(group)
    if style is None:
        style = compute_playoff_opponent_style_factors(group[0].get("features") or {}, league_defaults)
    for stat in STAT_TARGETS:
        def _lm_mult(c, st=stat):
            return playoff_lineup_matchup_multiplier_for_core(c, st, chemistry, style)

        _redistribute_team_stat_preserving_total_fn(group, stat, _lm_mult)
    if not all(c.get("rate_means") for c in group):
        return
    for rkey in ("FGA", "FGM", "FTA", "FTM", "FG3A", "TOV"):
        def _rm_mult(c, rk=rkey):
            return playoff_lineup_matchup_multiplier_for_core(c, rk, chemistry, style)

        _redistribute_team_rate_preserving_total_fn(group, rkey, _rm_mult)
    _repair_fgm_within_fga_team(group)
    _repair_ftm_within_fta_team(group)
    _repair_fg3a_within_fga_team(group)
    fg3 = np.array([max(0.0, float(c["stat_means"]["FG3M"])) for c in group], dtype=float)
    fgm = np.array([max(0.0, float(c["rate_means"]["FGM"])) for c in group], dtype=float)
    fg3 = np.minimum(fg3, fgm)
    fg2m = np.maximum(0.0, fgm - fg3)
    fga = np.array([max(0.0, float(c["rate_means"]["FGA"])) for c in group], dtype=float)
    fg3a = np.array([max(0.0, float(c["rate_means"]["FG3A"])) for c in group], dtype=float)
    fg2a = np.maximum(0.0, fga - fg3a)
    for i, c in enumerate(group):
        c["rate_means"]["FG2M"] = float(fg2m[i])
        c["rate_means"]["FG2A"] = float(max(fg2a[i], fg2m[i], 0.0))


def apply_playoff_team_total_guardrails(group):
    if not group:
        return
    implied = group[0].get("implied_team_total")
    if implied is not None and not pd.isna(implied) and float(implied) > 0:
        pts_vals = np.array([max(0.0, float(c["stat_means"].get("PTS", 0.0))) for c in group], dtype=float)
        pts_sum = float(np.sum(pts_vals))
        hi = float(implied) * 1.08
        lo = float(implied) * 0.92
        if pts_sum > hi or pts_sum < lo:
            target = hi if pts_sum > hi else lo
            scale = target / max(pts_sum, 1e-9)
            for c in group:
                c["stat_means"]["PTS"] = float(c["stat_means"]["PTS"]) * scale
            print(
                f"Playoff team PTS guardrail {group[0].get('team', '?')}: "
                f"sum={pts_sum:.1f}, target_band=({lo:.1f},{hi:.1f}), scale={scale:.3f}"
            )

    tc = group[0].get("team_context") or {}
    for stat, key, band in [("AST", "BASELINE_TEAM_AST", 1.14), ("REB", "BASELINE_TEAM_REB", 1.12)]:
        target = float(tc.get(key, np.nan))
        if pd.isna(target) or target <= 0:
            continue
        vals = np.array([max(0.0, float(c["stat_means"].get(stat, 0.0))) for c in group], dtype=float)
        total = float(np.sum(vals))
        hi = target * band
        if total > hi:
            scale = hi / max(total, 1e-9)
            for c in group:
                c["stat_means"][stat] = float(c["stat_means"][stat]) * scale
            print(f"Playoff team {stat} guardrail {group[0].get('team', '?')}: sum={total:.1f}, cap={hi:.1f}, scale={scale:.3f}")


def playoff_tier_floor(tier, protected_min_floor):
    pf = float(protected_min_floor or 0.0)
    if tier <= 1:
        return max(24.0, pf * 0.85) if pf > 0 else 26.0
    if tier == 2:
        return max(16.0, pf * 0.72) if pf > 0 else 20.0
    if tier == 3:
        return max(6.0, pf * 0.32) if pf > 0 else 8.0
    if tier == 4:
        return 3.0
    return 0.0


def playoff_tier_cap(tier, star_signal, core=None):
    """
    Hard caps before soak. Only `playoff_high_minute_engine_eligible` cores keep T1/T2
    headroom in the true 37–40 band; secondary starters and specialists are throttled.
    """
    engine = playoff_high_minute_engine_eligible(core) if core is not None else False
    if tier == 1:
        if engine:
            return 41.8 if star_signal >= 0.64 else 40.5
        return 36.5 if star_signal >= 0.60 else 35.0
    if tier == 2:
        if engine:
            return 35.4 if star_signal >= 0.62 else 34.0
        return 30.5 if star_signal >= 0.58 else 29.0
    if tier == 3:
        return 31.2 if engine else 29.0
    if tier == 4:
        return 27.5
    return 21.5


def playoff_tier_scale_for_redistribution(tier):
    """Stronger separation so spare minutes land on the top 1-2 workhorses, not 8+ \"star\"s."""
    if tier == 1:
        return 1.0
    if tier == 2:
        return 0.48
    if tier == 3:
        return 0.26
    if tier == 4:
        return 0.13
    return 0.07


def playoff_redistribution_weight(core):
    rf = core["role_fit"]
    pp = core["player_profile"]
    t = playoff_closure_priority_tier(core)
    eng = playoff_high_minute_engine_eligible(core)
    star = star_signal_from_role_fit(rf) ** 1.2
    ls = float(pp.get("LIKELY_STARTER", 0.0))
    lc = float(pp.get("LIKELY_CLOSER", 0.0))
    stab = float(pp.get("ROLE_STABILITY_SCORE", 0.7))
    if t <= 2:
        role_adj = 0.52 + 0.28 * lc + 0.20 * ls
    else:
        role_adj = 0.34 + 0.08 * lc + 0.07 * ls
    base = (
        star
        * role_adj
        * (0.82 + 0.15 * stab)
        * (0.32 + 0.68 * playoff_tier_scale_for_redistribution(t))
    )
    if eng:
        return float(base)
    if t <= 2:
        return float(base * 0.38)
    if t == 3:
        return float(base * 0.52)
    return float(base * 0.75)


def playoff_closure_stat_minute_scale_ratio(pre_m, closed_m, role_fit):
    """
    When pre-closure minutes are tiny (or the closed/pre ratio is huge), a plain
    multiplicative reflow of counting stats is pathological. Cap scaling; stars
    can stretch slightly more than fringe/backup.
    """
    pre_m = float(max(pre_m, 1e-3))
    closed_m = float(max(0.0, closed_m))
    raw = closed_m / pre_m
    star = float(star_signal_from_role_fit(role_fit or {}))
    if pre_m < 2.0 or raw > 2.35:
        return float(min(raw, 2.02 + 0.55 * min(star, 1.0)))
    if raw > 1.88:
        return float(min(raw, 1.72 + 0.38 * min(star, 1.0)))
    return float(raw)


def solve_playoff_team_minutes_to_target(group, target=TEAM_REGULATION_MINUTES):
    n = len(group)
    mins = [max(0.0, float(c["mean_minutes"])) for c in group]
    tiers = [playoff_closure_priority_tier(c) for c in group]
    stars = [star_signal_from_role_fit(c["role_fit"]) for c in group]
    floors = [playoff_tier_floor(tiers[i], group[i]["protected_min_floor"]) for i in range(n)]
    caps = [playoff_tier_cap(tiers[i], stars[i], group[i]) for i in range(n)]
    mins = [max(floors[i], min(caps[i], mins[i])) for i in range(n)]

    def total_minutes():
        return float(sum(mins))

    surplus = total_minutes() - target
    if surplus > 1e-6:
        deficit = surplus
        for t in [5, 4, 3, 2, 1]:
            if deficit <= 1e-6:
                break
            idx = [i for i in range(n) if tiers[i] == t and mins[i] > floors[i] + 1e-6]
            slack = sum(mins[i] - floors[i] for i in idx)
            if slack <= 1e-6:
                continue
            take = min(deficit, slack)
            for i in idx:
                reducible = mins[i] - floors[i]
                mins[i] -= take * (reducible / slack)
            deficit = total_minutes() - target
        if total_minutes() > target + 1e-4:
            deficit = total_minutes() - target
            idx = [i for i in range(n) if mins[i] > floors[i] + 1e-6]
            slack = sum(mins[i] - floors[i] for i in idx)
            if slack > 1e-6:
                for i in idx:
                    reducible = mins[i] - floors[i]
                    mins[i] -= deficit * (reducible / slack)

    need = target - total_minutes()
    if need > 1e-6:
        for t in [1, 2, 3, 4, 5]:
            if need <= 1e-6:
                break
            idx = [i for i in range(n) if tiers[i] == t and mins[i] < caps[i] - 1e-6]
            head = sum(caps[i] - mins[i] for i in idx)
            if head <= 1e-6:
                continue
            weights = [playoff_redistribution_weight(group[i]) * (caps[i] - mins[i]) for i in idx]
            ws = sum(weights) or 1.0
            add = min(need, head)
            for j, i in enumerate(idx):
                mins[i] += add * (weights[j] / ws)
            need = target - total_minutes()
        if total_minutes() < target - 1e-4:
            need = target - total_minutes()
            idx = [i for i in range(n) if mins[i] < caps[i] - 1e-6]
            head = sum(caps[i] - mins[i] for i in idx)
            if head > 1e-6:
                weights = [playoff_redistribution_weight(group[i]) * (caps[i] - mins[i]) for i in idx]
                ws = sum(weights) or 1.0
                for j, i in enumerate(idx):
                    mins[i] += min(need, head) * (weights[j] / ws)

    mins = [max(floors[i], min(caps[i], float(m))) for i, m in enumerate(mins)]
    err = target - sum(mins)

    def _soft_stretch(i):
        t = int(tiers[i])
        eng = playoff_high_minute_engine_eligible(group[i])
        if t == 1 and eng:
            return 0.75
        if t == 1:
            return 0.28
        if t == 2 and eng:
            return 0.30
        if t == 2:
            return 0.10
        if t == 3:
            return 0.08
        return 0.0

    soft_ceiling = [caps[i] + _soft_stretch(i) for i in range(n)]
    guard = 0
    while abs(err) > 1e-7 and guard < n * 8:
        guard += 1
        if err > 0:
            order = sorted(range(n), key=lambda i: playoff_redistribution_weight(group[i]), reverse=True)
            moved = False
            for i in order:
                head = max(0.0, soft_ceiling[i] - mins[i])
                if head <= 1e-9:
                    continue
                step = min(err, head, 0.5)
                mins[i] += step
                err -= step
                moved = True
                break
            if not moved:
                break
        else:
            order = sorted(range(n), key=lambda i: playoff_redistribution_weight(group[i]), reverse=False)
            moved = False
            for i in order:
                reducible = max(0.0, mins[i] - floors[i])
                if reducible <= 1e-9:
                    continue
                step = min(-err, reducible, 0.5)
                mins[i] -= step
                err += step
                moved = True
                break
            if not moved:
                break

    def _proportional_minute_soak(ceiling_getter, max_passes=6000, step_max=0.5):
        """Spread residual target error without letting one player take the full remainder."""
        for _ in range(max_passes):
            err = target - float(sum(mins))
            if abs(err) <= 1e-4:
                return
            if err > 0:
                head = [max(0.0, ceiling_getter(i) - mins[i]) for i in range(n)]
                shead = float(sum(head))
                if shead <= 1e-8:
                    return
                step = min(err, step_max, shead)
                for i in range(n):
                    mins[i] += step * (head[i] / shead)
            else:
                red = [max(0.0, mins[i] - floors[i]) for i in range(n)]
                sred = float(sum(red))
                if sred <= 1e-8:
                    return
                step = min(-err, step_max, sred)
                for i in range(n):
                    mins[i] -= step * (red[i] / sred)

    err = target - float(sum(mins))
    if abs(err) > 1e-4:
        _proportional_minute_soak(lambda i: soft_ceiling[i], step_max=0.5)
    err = target - float(sum(mins))
    if abs(err) > 1e-4:
        # Last-resort soak: do not use a flat 48 for all tiers (was flattening the rotation to 38+).
        def _emergency_cap(i):
            c = float(caps[i])
            t = int(tiers[i])
            eng = playoff_high_minute_engine_eligible(group[i])
            if t == 1 and eng:
                return min(47.0, c + 1.0)
            if t == 1:
                return min(42.0, c + 0.35)
            if t == 2 and eng:
                return min(42.0, c + 0.45)
            if t == 2:
                return min(38.0, c + 0.18)
            if t == 3:
                return min(36.0, c + 0.12)
            return c

        _proportional_minute_soak(_emergency_cap, step_max=0.65)
    err = target - float(sum(mins))
    team_label = str(group[0].get("team", "")) if group else "?"
    if abs(err) > 0.2:
        print(
            f"WARNING: Playoff minute mass balance for {team_label} still off by {err:+.1f} "
            f"after soft/hard-capped distribution (n={n}, sum={sum(mins):.1f} vs {target}). "
            "Roster for this team may be too small or caps too tight."
        )
    return mins


def verify_playoff_closure_team_totals(cores, tol=0.08):
    by_team = {}
    for c in cores:
        by_team.setdefault(c["team"], []).append(float(c["mean_minutes"]))
    for team, vals in sorted(by_team.items()):
        s = float(sum(vals))
        if abs(s - TEAM_REGULATION_MINUTES) > tol:
            print(
                f"WARNING: Playoff minute closure for {team} sums to {s:.2f} "
                f"(target {TEAM_REGULATION_MINUTES}); check roster coverage."
            )


def snapshot_playoff_pre_closure_diagnostics(cores):
    for c in cores:
        c["_playoff_pre_diag"] = {
            "min": float(c["mean_minutes"]),
            "stats": {k: float(c["stat_means"][k]) for k in STAT_TARGETS},
        }


def verify_playoff_production_guardrails(cores, minute_tol=0.12):
    if not cores:
        return
    by_team = {}
    for c in cores:
        by_team.setdefault(c["team"], []).append(c)
    for team, group in sorted(by_team.items()):
        msum = float(sum(float(c["mean_minutes"]) for c in group))
        if abs(msum - TEAM_REGULATION_MINUTES) > minute_tol:
            print(
                f"WARNING [playoff guardrail]: {team} total minutes {msum:.2f} "
                f"(expected {TEAM_REGULATION_MINUTES})"
            )
        impl = group[0].get("implied_team_total")
        if impl is not None and not pd.isna(impl) and float(impl) > 0:
            sum_pts = float(sum(float(c["stat_means"]["PTS"]) for c in group))
            r = sum_pts / float(impl)
            if r > PLAYOFF_GUARD_IMPLIED_PTS_MAX_RATIO:
                print(
                    f"WARNING [playoff guardrail]: {team} sum PTS {sum_pts:.1f} vs implied {float(impl):.1f} "
                    f"(ratio {r:.2f}) — possible offensive stacking"
                )
            elif r < PLAYOFF_GUARD_IMPLIED_PTS_MIN_RATIO:
                print(
                    f"WARNING [playoff guardrail]: {team} sum PTS {sum_pts:.1f} vs implied {float(impl):.1f} "
                    f"(ratio {r:.2f}) — possible under-shoot"
                )
        sum_ast = float(sum(float(c["stat_means"]["AST"]) for c in group))
        if sum_ast > PLAYOFF_GUARD_TEAM_AST_SUM:
            print(f"WARNING [playoff guardrail]: {team} sum AST means {sum_ast:.1f} (unusually high)")
        sum_reb = float(sum(float(c["stat_means"]["REB"]) for c in group))
        if sum_reb > PLAYOFF_GUARD_TEAM_REB_SUM:
            print(f"WARNING [playoff guardrail]: {team} sum REB means {sum_reb:.1f} (unusually high)")
        for c in group:
            nm = c["player_name"]
            mn = float(c["mean_minutes"])
            if mn < -0.01 or mn > 46.6:
                print(f"WARNING [playoff guardrail]: {nm} ({team}) minutes {mn:.2f} out of sane range")
            role = str(c.get("playoff_role_label") or "")
            for sk in STAT_TARGETS:
                v = float(c["stat_means"].get(sk, 0.0))
                if v < -0.01:
                    print(f"WARNING [playoff guardrail]: {nm} ({team}) {sk} mean {v:.3f} negative")
            pts = float(c["stat_means"]["PTS"])
            if mn >= 6.0 and pts >= 0:
                ppm = pts / max(mn, 1e-6)
                if role in {"fringe", "emergency_only"}:
                    if ppm > PLAYOFF_GUARD_FRINGE_PTS_PER_MIN:
                        print(
                            f"WARNING [playoff guardrail]: fringe PTS/min {ppm:.2f} for {nm} ({team}) "
                            f"({mn:.1f} min)"
                        )
                    if mn > PLAYOFF_GUARD_FRINGE_MINUTES + 1e-6:
                        print(
                            f"WARNING [playoff guardrail]: fringe role {mn:.1f} min for {nm} ({team}) "
                            f"— check closure / expansion"
                        )
                if role == "playoff_engine" and mn >= 28.0 and ppm > PLAYOFF_GUARD_ENGINE_PTS_PER_MIN:
                    print(
                        f"WARNING [playoff guardrail]: engine PTS/min {ppm:.2f} for {nm} ({team}) "
                        f"({mn:.1f} min) — verify stacking"
                    )
            rm = c.get("rate_means") or {}
            if rm:
                fga = float(rm.get("FGA", 0.0))
                fgm = float(rm.get("FGM", 0.0))
                fta = float(rm.get("FTA", 0.0))
                ftm = float(rm.get("FTM", 0.0))
                fg3a = float(rm.get("FG3A", 0.0))
                if fga > 0.08 and fgm > fga + 0.1:
                    print(f"WARNING [playoff guardrail]: FGM>FGA for {nm} ({team})")
                if fta > 0.08 and ftm > fta + 0.08:
                    print(f"WARNING [playoff guardrail]: FTM>FTA for {nm} ({team})")
                if fga > 0.08 and fg3a > fga + 0.08:
                    print(f"WARNING [playoff guardrail]: FG3A>FGA for {nm} ({team})")


def print_playoff_regression_audit_and_cleanup(cores):
    if not cores:
        return
    min_rows = []
    pts_rows = []
    team_abs = {}
    for c in cores:
        pre = c.get("_playoff_pre_diag")
        if not pre:
            continue
        dmn = float(c["mean_minutes"]) - pre["min"]
        team_abs.setdefault(c["team"], []).append(abs(dmn))
        if abs(dmn) >= 2.0:
            min_rows.append((abs(dmn), dmn, c["player_name"], c["team"], str(c.get("playoff_role_label") or "")))
        p0 = float(pre["stats"].get("PTS", 0.0))
        p1 = float(c["stat_means"]["PTS"])
        if p0 > 0.5:
            rt = p1 / max(p0, 0.01)
            if abs(rt - 1.0) >= 0.18:
                pts_rows.append((abs(rt - 1.0), rt, c["player_name"], c["team"], p0, p1, str(c.get("playoff_role_label") or "")))
    for c in cores:
        c.pop("_playoff_pre_diag", None)
    min_rows.sort(reverse=True)
    pts_rows.sort(reverse=True)
    print("\n=== Playoff regression audit (pre- vs post-closure cores) ===")
    print(f"Playoff cores: {len(cores)}")
    print(f"Players with |ΔMIN| >= 2: {len(min_rows)}")
    print(f"Players with PTS mean drift >= 18% (pre PTS > 0.5): {len(pts_rows)}")
    if min_rows:
        print("Largest minute adjustments (top 10):")
        for _, dmn, nm, tm, rl in min_rows[:10]:
            print(f"  {nm} ({tm}) [{rl}]: {dmn:+.1f} min")
    if pts_rows:
        print("Largest PTS ratio shifts (top 10):")
        for _, rt, nm, tm, p0, p1, rl in pts_rows[:10]:
            print(f"  {nm} ({tm}) [{rl}]: {p0:.1f} -> {p1:.1f} (x{rt:.2f})")
    if team_abs:
        ranked = sorted(((float(np.mean(v)), t) for t, v in team_abs.items()), reverse=True)
        print("Teams by mean |ΔMIN| — closure stress (top 8):")
        for avg, t in ranked[:8]:
            print(f"  {t}: {avg:.2f}")
    print("=== End playoff regression audit ===\n")


def compute_team_rotation_structure(group, closed_minutes):
    by_min = sorted(range(len(group)), key=lambda i: closed_minutes[i], reverse=True)
    top5 = [group[i]["player_name"] for i in by_min[:5]]
    top7 = [group[i]["player_name"] for i in by_min[:7]]
    close_sorted = sorted(
        range(len(group)),
        key=lambda i: closed_minutes[i] * (0.62 + 0.38 * float(group[i]["player_profile"].get("CLOSE_LINEUP_SCORE", 0.0))),
        reverse=True,
    )
    closing = [group[i]["player_name"] for i in close_sorted[:5] if closed_minutes[i] >= 5.0]
    rot_size = int(sum(1 for m in closed_minutes if m >= 5.0))
    fringe_vals = [
        float(group[i]["player_profile"].get("FAKE_STARTER_RISK", 0.0))
        for i in range(len(group))
        if closed_minutes[i] >= 4.0
    ]
    fringe = float(np.mean(fringe_vals)) if fringe_vals else 0.0
    return {
        "projected_rotation_size": rot_size,
        "projected_core_5": "|".join(top5),
        "projected_core_7": "|".join(top7),
        "projected_closing_group": "|".join(closing),
        "fringe_rotation_risk": round(min(1.0, fringe), 4),
        "TEAM_MINUTES_CLOSED_SUM": float(TEAM_REGULATION_MINUTES),
    }


def apply_playoff_team_minute_closure_to_cores(cores):
    if not cores:
        return
    buckets = {}
    for c in cores:
        buckets.setdefault(c["team"], []).append(c)
    for team, group in buckets.items():
        if not group:
            continue
        pre = [float(c["mean_minutes"]) for c in group]
        closed = solve_playoff_team_minutes_to_target(group, TEAM_REGULATION_MINUTES)
        struct = compute_team_rotation_structure(group, closed)
        for i, c in enumerate(group):
            pre_m = pre[i]
            c["mean_minutes_pre_closure"] = pre_m
            c["mean_minutes"] = closed[i]
            if c["player_key"] in _TRACE_KEYS:
                tier = playoff_closure_priority_tier(c)
                print(
                    f"[TRACE:POST_CLOSURE] {c['player_key']} | "
                    f"pre_closure={round(pre_m, 2)} | "
                    f"post_closure={round(closed[i], 2)} | "
                    f"closure_tier={tier} | "
                    f"role_label={assign_playoff_role_label(c)} | "
                    f"engine={playoff_high_minute_engine_eligible(c)}"
                )

        # Structural guard: lock final minutes to the playoff prior so closure
        # redistribution, blowout logic, or heuristic overrides cannot invert reality.
        _clamp_playoff_minutes_to_prior(group)
        _enforce_playoff_prior_hierarchy(group)

        for i, c in enumerate(group):
            pre_m = float(c["mean_minutes_pre_closure"])
            closed_m = float(c["mean_minutes"])
            ratio = playoff_closure_stat_minute_scale_ratio(pre_m, closed_m, c.get("role_fit"))
            for s in STAT_TARGETS:
                c["stat_means"][s] = float(c["stat_means"][s]) * ratio
            c["team_rotation_structure"] = struct
            c["playoff_role_label"] = assign_playoff_role_label(c)
            apply_playoff_counting_stat_calibration(
                c["stat_means"],
                c["role_fit"],
                c["playoff_role_label"],
                float(closed[i]),
            )
            rm = c.get("rate_means")
            if rm:
                for rk in list(rm.keys()):
                    rm[rk] = float(rm[rk]) * ratio
        apply_playoff_team_stat_share_redistribution(group)
        apply_playoff_assist_creation_redistribution(group)
        apply_playoff_team_shot_volume_redistribution(group)
        apply_playoff_team_offensive_usage_refinement(group)
        apply_playoff_team_fg3a_concentration(group)
        apply_playoff_team_tov_possession_redistribution(group)
        apply_playoff_pts_shot_coherence(group)
        league_defaults = group[0].get("league_defaults") or {}
        chemistry = compute_playoff_team_lineup_chemistry(group)
        style = compute_playoff_opponent_style_factors(group[0].get("features") or {}, league_defaults)
        apply_playoff_lineup_and_matchup_redistribution(group, chemistry=chemistry, style=style)
        apply_playoff_pts_shot_coherence(group, blend=0.145)
        apply_playoff_team_total_guardrails(group)
        attach_playoff_diagnostics_to_cores(group, chemistry, style)


def apply_playoff_team_simulated_minute_reconciliation_to_cores(cores, target=TEAM_REGULATION_MINUTES):
    """
    Precompute playoff minute draws at the team level, then reconcile every
    simulation run back to the regulation team-minute target before any stat
    draw is generated. This keeps displayed minutes and downstream props on
    the same opportunity regime.
    """
    if not cores:
        return
    buckets = {}
    for c in cores:
        buckets.setdefault(c["team"], []).append(c)

    for team, group in buckets.items():
        raw_minutes = []
        raw_quarters = []
        active_masks = []
        game_scripts = []
        availability_vals = []
        for c in group:
            rng_seed = abs(hash((c["player_key"], current_projection_date()))) % (2 ** 32)
            rng = np.random.default_rng(rng_seed)
            minutes_draws, quarter_minutes, active_mask, game_script, availability = simulate_minutes(
                float(c["mean_minutes"]),
                c["features"],
                c["injury_status"],
                rng,
                c["role_fit"],
                game_context=c["game_context"],
            )
            raw_minutes.append(minutes_draws.astype(float))
            raw_quarters.append(quarter_minutes.astype(float))
            active_masks.append(active_mask)
            game_scripts.append(game_script)
            availability_vals.append(availability)

        matrix = np.vstack(raw_minutes)
        raw_team_totals = matrix.sum(axis=0)
        scale = np.divide(
            float(target),
            raw_team_totals,
            out=np.ones_like(raw_team_totals, dtype=float),
            where=raw_team_totals > 1e-9,
        )
        scale = np.clip(scale, 0.35, 2.25)
        reconciled = matrix * scale[None, :]
        final_team_totals = reconciled.sum(axis=0)
        residual = np.divide(
            float(target),
            final_team_totals,
            out=np.ones_like(final_team_totals, dtype=float),
            where=final_team_totals > 1e-9,
        )
        reconciled *= residual[None, :]

        cap_vals = []
        for c in group:
            engine = playoff_high_minute_engine_eligible(c)
            cap = playoff_tier_cap(playoff_closure_priority_tier(c), star_signal_from_role_fit(c["role_fit"]), c)
            cap += 3.0 if engine else 1.5
            if str(c.get("playoff_prior_kind", "")) != "true_playoff":
                cap = min(cap, 42.0 if engine else 38.0)
            cap_vals.append(min(46.0, cap))
        caps = np.array(cap_vals, dtype=float)
        weights = np.array([max(0.01, playoff_redistribution_weight(c)) for c in group], dtype=float)
        for j in range(reconciled.shape[1]):
            vals = reconciled[:, j].copy()
            for _ in range(4):
                vals = np.minimum(vals, caps)
                need = float(target) - float(np.sum(vals))
                if need <= 1e-7:
                    break
                headroom = np.maximum(0.0, caps - vals)
                eligible = headroom > 1e-7
                if not np.any(eligible):
                    break
                w = weights * headroom
                wsum = float(np.sum(w[eligible]))
                if wsum <= 1e-9:
                    break
                vals[eligible] += need * (w[eligible] / wsum)
            reconciled[:, j] = np.minimum(vals, caps)

        raw_matrix_safe = np.where(matrix > 1e-9, matrix, 1.0)
        player_draw_scale = np.divide(reconciled, raw_matrix_safe, out=np.zeros_like(reconciled), where=matrix > 1e-9)
        quarter_tensor = np.stack(raw_quarters, axis=0) * player_draw_scale[:, :, None]

        raw_mean = float(np.mean(raw_team_totals))
        reconciled_totals = reconciled.sum(axis=0)
        rec_mean = float(np.mean(reconciled_totals))
        print(
            f"Playoff simulated minute reconciliation {team}: "
            f"raw_mean={raw_mean:.2f}, reconciled_mean={rec_mean:.2f}, target={float(target):.1f}"
        )

        for i, c in enumerate(group):
            reconciled_player_mean = float(np.mean(reconciled[i]))
            old_mean = float(c.get("mean_minutes", reconciled_player_mean) or reconciled_player_mean)
            c["mean_minutes"] = reconciled_player_mean
            if c.get("mean_minutes_pre_closure") is not None:
                c["MINUTE_RECONCILIATION_DELTA"] = reconciled_player_mean - old_mean
            c["sim_minutes_bundle"] = {
                "minutes_draws": reconciled[i],
                "quarter_minutes": quarter_tensor[i],
                "active_mask": active_masks[i],
                "game_script": game_scripts[i],
                "availability": availability_vals[i],
                "raw_team_minutes_mean": raw_mean,
                "reconciled_team_minutes_mean": rec_mean,
            }


def protect_core_scoring_mean(points_mean, mean_minutes, player_logs, features, role_fit, protected_min_floor):
    if protected_min_floor <= 0 or points_mean <= 0 or mean_minutes <= 0:
        return points_mean
    if features["LOW_MIN_ROLE"] or role_fit.get("BENCH_PLAYER", 0.0) >= 0.5:
        return points_mean

    scorer_signal = (
        (0.58 * role_fit.get("SCORER", 0.0))
        + (0.18 * role_fit.get("SHOOTER", 0.0))
        + (0.14 * role_fit.get("CORE_PLAYER", 0.0))
        + (0.10 * role_fit.get("CLOSER", 0.0))
    )
    if scorer_signal < 0.55:
        return points_mean

    def points_per_minute(frame):
        minutes = pd.to_numeric(frame["MIN"], errors="coerce").fillna(0.0).sum()
        points = pd.to_numeric(frame["PTS"], errors="coerce").fillna(0.0).sum()
        return safe_divide(points, max(minutes, 1.0))

    recent5_rate = points_per_minute(player_logs.head(5))
    recent10_rate = points_per_minute(player_logs.head(10))
    recent20_rate = points_per_minute(player_logs.head(20))
    durable_rate = (0.50 * recent5_rate) + (0.30 * recent10_rate) + (0.20 * recent20_rate)
    current_rate = points_mean / max(mean_minutes, 1.0)
    if durable_rate <= current_rate:
        return points_mean

    target_points = durable_rate * mean_minutes
    raw_lift = (target_points / points_mean) - 1.0
    max_lift = 0.08 + (0.10 * scorer_signal)
    lift = min(max_lift, max(0.0, raw_lift) * 0.70)
    return points_mean * (1.0 + lift)


def protect_core_assist_mean(ast_mean, mean_minutes, player_logs, features, role_fit, protected_min_floor):
    if protected_min_floor <= 0 or ast_mean <= 0 or mean_minutes <= 0:
        return ast_mean
    if features["LOW_MIN_ROLE"] or role_fit.get("BENCH_PLAYER", 0.0) >= 0.5:
        return ast_mean

    creator_signal = (
        (0.62 * role_fit.get("PLAYMAKER", 0.0))
        + (0.14 * role_fit.get("SCORER", 0.0))
        + (0.14 * role_fit.get("CORE_PLAYER", 0.0))
        + (0.10 * role_fit.get("CLOSER", 0.0))
    )
    if creator_signal < 0.62:
        return ast_mean

    def assists_per_minute(frame):
        minutes = pd.to_numeric(frame["MIN"], errors="coerce").fillna(0.0).sum()
        assists = pd.to_numeric(frame["AST"], errors="coerce").fillna(0.0).sum()
        return safe_divide(assists, max(minutes, 1.0))

    recent5_rate = assists_per_minute(player_logs.head(5))
    recent10_rate = assists_per_minute(player_logs.head(10))
    recent20_rate = assists_per_minute(player_logs.head(20))
    durable_rate = (0.50 * recent5_rate) + (0.30 * recent10_rate) + (0.20 * recent20_rate)
    current_rate = ast_mean / max(mean_minutes, 1.0)
    if durable_rate <= current_rate:
        return ast_mean

    target_ast = durable_rate * mean_minutes
    raw_lift = (target_ast / ast_mean) - 1.0
    max_lift = 0.06 + (0.08 * creator_signal)
    lift = min(max_lift, max(0.0, raw_lift) * 0.65)
    return ast_mean * (1.0 + lift)


def control_rebound_inflation_mean(reb_mean, mean_minutes, player_logs, features, role_fit):
    if reb_mean <= 0 or mean_minutes <= 0 or reb_mean < 3.0:
        return reb_mean

    def rebounds_per_minute(frame):
        minutes = pd.to_numeric(frame["MIN"], errors="coerce").fillna(0.0).sum()
        rebounds = pd.to_numeric(frame["REB"], errors="coerce").fillna(0.0).sum()
        return safe_divide(rebounds, max(minutes, 1.0))

    recent5_rate = rebounds_per_minute(player_logs.head(5))
    recent10_rate = rebounds_per_minute(player_logs.head(10))
    recent20_rate = rebounds_per_minute(player_logs.head(20))
    durable_rate = (0.45 * recent5_rate) + (0.35 * recent10_rate) + (0.20 * recent20_rate)
    if durable_rate <= 0:
        return reb_mean

    current_rate = reb_mean / max(mean_minutes, 1.0)
    rebound_signal = np.clip(
        (0.62 * role_fit.get("REBOUNDER", 0.0))
        + (0.22 * role_fit.get("RIM", 0.0))
        + (0.16 * role_fit.get("CORE_PLAYER", 0.0)),
        0.0,
        1.0,
    )
    rate_tolerance = 0.015 + (0.025 * rebound_signal)
    if current_rate <= durable_rate + rate_tolerance:
        return reb_mean

    durable_mean = durable_rate * mean_minutes
    candidate = max(durable_mean * (1.03 + (0.10 * rebound_signal)), durable_mean + 0.35)
    max_down = 0.05 + (0.07 * (1.0 - rebound_signal))
    return max(reb_mean * (1.0 - max_down), min(reb_mean, candidate))


def protect_shooter_fg3m_mean(fg3m_mean, mean_minutes, player_logs, features, role_fit):
    if fg3m_mean <= 0 or mean_minutes <= 0:
        return fg3m_mean

    shooter_signal = np.clip(
        (0.60 * role_fit.get("SHOOTER", 0.0))
        + (0.22 * role_fit.get("SCORER", 0.0))
        + (0.10 * role_fit.get("CORE_PLAYER", 0.0))
        + (0.08 * role_fit.get("CLOSER", 0.0)),
        0.0,
        1.0,
    )
    if shooter_signal < 0.55:
        return fg3m_mean

    def per_minute(frame, col):
        minutes = pd.to_numeric(frame["MIN"], errors="coerce").fillna(0.0).sum()
        values = pd.to_numeric(frame[col], errors="coerce").fillna(0.0).sum()
        return safe_divide(values, max(minutes, 1.0))

    recent5_rate = per_minute(player_logs.head(5), "FG3M")
    recent10_rate = per_minute(player_logs.head(10), "FG3M")
    recent20_rate = per_minute(player_logs.head(20), "FG3M")
    durable_rate = (0.50 * recent5_rate) + (0.32 * recent10_rate) + (0.18 * recent20_rate)
    current_rate = fg3m_mean / max(mean_minutes, 1.0)
    if durable_rate <= current_rate:
        return fg3m_mean

    recent5_attempt_rate = per_minute(player_logs.head(5), "FG3A")
    recent10_attempt_rate = per_minute(player_logs.head(10), "FG3A")
    recent20_attempt_rate = per_minute(player_logs.head(20), "FG3A")
    durable_attempt_rate = (0.50 * recent5_attempt_rate) + (0.32 * recent10_attempt_rate) + (0.18 * recent20_attempt_rate)
    shot_volume_signal = min(1.0, durable_attempt_rate / 0.24)
    if durable_attempt_rate < 0.13 and durable_rate < 0.055:
        return fg3m_mean
    if shooter_signal < 0.65 and shot_volume_signal < 0.70:
        return fg3m_mean

    target_fg3m = durable_rate * mean_minutes
    raw_lift = (target_fg3m / fg3m_mean) - 1.0
    max_lift = 0.10 + (0.10 * shooter_signal) + (0.04 * shot_volume_signal)
    lift = min(max_lift, max(0.0, raw_lift) * 0.60)
    return fg3m_mean * (1.0 + lift)


def confidence_from_profile(features, games_used, availability):
    base = 0.56
    base += min(games_used, 10) * 0.020
    base += min(features["MIN_LAST5"], 36) * 0.006
    base -= min(features["MIN_STD5"], 10) * 0.015
    base -= abs(features["PTS_TREND"]) * 0.006
    base *= availability
    conf = max(0.05, min(base, 0.95))

    if conf >= 0.80:
        return conf, "HIGH", "High"
    if conf >= 0.64:
        return conf, "MEDIUM", "Medium"
    return conf, "LOW", "Low"


def simulate_minutes(mean_minutes, features, status, rng, role_fit, game_context=None):
    availability = STATUS_AVAILABILITY.get(status, STATUS_AVAILABILITY["UNKNOWN"])
    minutes_multiplier = STATUS_MINUTES_MULTIPLIER.get(status, STATUS_MINUTES_MULTIPLIER["UNKNOWN"])

    active_mask = rng.random(SIMULATION_RUNS) < availability
    player_noise = rng.normal(0.0, 0.35, SIMULATION_RUNS)

    if game_context:
        team_margin_draws = game_context["TEAM_MARGIN_DRAWS"]
        pace_script = game_context["PACE_SCRIPT"]
        competitive_mask = game_context["COMPETITIVE_MASK"]
        blowout_mask = game_context["BLOWOUT_MASK"]
        game_script = np.clip((team_margin_draws / 12.0) + player_noise, -1.6, 1.6)
    else:
        team_margin_draws = rng.normal(0.0, DEFAULT_MARGIN_STD, SIMULATION_RUNS)
        pace_script = np.ones(SIMULATION_RUNS)
        competitive_mask = np.abs(team_margin_draws) <= 6.0
        blowout_mask = np.abs(team_margin_draws) >= BLOWOUT_THRESHOLD
        game_script = np.clip((team_margin_draws / 12.0) + player_noise, -1.6, 1.6)

    base_sigma = max(2.2, features["MIN_STD5"] * 1.10)
    if features["VOLATILE_MINUTES"]:
        base_sigma += 1.5
    if features["LOW_MIN_ROLE"]:
        base_sigma += 1.0
    if status in {"QUESTIONABLE", "DOUBTFUL"}:
        base_sigma += 1.6

    core_minutes_share = min(1.0, max(0.0, ((mean_minutes - 18.0) / 16.0)))
    low_minutes_share = float(features["LOW_MIN_ROLE"])
    volatile_share = float(features["VOLATILE_MINUTES"])
    playmaker_share = float(role_fit.get("PLAYMAKER", 0.0))
    scorer_share = float(role_fit.get("SCORER", 0.0))
    rebounder_share = float(role_fit.get("REBOUNDER", 0.0))
    core_player = float(role_fit.get("CORE_PLAYER", 0.0))
    bench_player = float(role_fit.get("BENCH_PLAYER", 0.0))
    garbage_time_fit = float(role_fit.get("GARBAGE_TIME_FIT", 0.0))
    starter = float(role_fit.get("STARTER", 0.0))
    closer = float(role_fit.get("CLOSER", 0.0))
    second_unit = float(role_fit.get("SECOND_UNIT", 0.0))
    garbage_unit = float(role_fit.get("GARBAGE_UNIT", 0.0))
    template_minutes = float(role_fit.get("TEMPLATE_MINUTES", 0.0))
    template_sample = float(role_fit.get("TEMPLATE_SAMPLE_WEIGHT", 0.0))
    protected_min_floor = float(role_fit.get("PROTECTED_MIN_FLOOR", 0.0))
    template_shares = np.array(
        [
            float(role_fit.get("TEMPLATE_Q1_SHARE", 0.25)),
            float(role_fit.get("TEMPLATE_Q2_SHARE", 0.25)),
            float(role_fit.get("TEMPLATE_Q3_SHARE", 0.25)),
            float(role_fit.get("TEMPLATE_Q4_SHARE", 0.25)),
        ],
        dtype=float,
    )

    target_minutes = rng.normal(mean_minutes * minutes_multiplier, base_sigma, SIMULATION_RUNS)
    target_minutes *= pace_script
    if template_sample > 0 and template_minutes > 0:
        template_minutes_draw = rng.normal(template_minutes * minutes_multiplier, max(1.5, base_sigma * 0.65), SIMULATION_RUNS)
        anchor_weight = 0.18 + (0.17 * template_sample)
        target_minutes = ((1.0 - anchor_weight) * target_minutes) + (anchor_weight * template_minutes_draw)
        if protected_min_floor > 0:
            protected_draw = rng.normal(protected_min_floor * minutes_multiplier, max(1.8, base_sigma * 0.45), SIMULATION_RUNS)
            target_minutes = np.maximum(target_minutes, protected_draw)

    # Quarter-by-quarter rotation shape so close games and blowouts move time into
    # realistic buckets rather than acting like a flat full-game haircut.
    q1_share = 0.26 + (0.05 * starter) + (0.02 * core_player) - (0.06 * second_unit) - (0.08 * garbage_unit)
    q2_share = 0.24 - (0.04 * starter) + (0.07 * second_unit) + (0.02 * bench_player)
    q3_share = 0.25 + (0.04 * starter) + (0.02 * closer) - (0.02 * garbage_unit)
    q4_share = 0.25 + (0.06 * closer) - (0.04 * second_unit) - (0.05 * garbage_unit)
    share_total = q1_share + q2_share + q3_share + q4_share
    quarter_shares = np.array([q1_share, q2_share, q3_share, q4_share], dtype=float) / share_total
    template_share_total = template_shares.sum()
    if template_sample > 0 and template_share_total > 0:
        template_shares = template_shares / template_share_total
        share_blend = 0.45 + (0.40 * template_sample)
        quarter_shares = ((1.0 - share_blend) * quarter_shares) + (share_blend * template_shares)
        quarter_shares = quarter_shares / max(quarter_shares.sum(), 1e-6)
    quarter_minutes = target_minutes[:, None] * quarter_shares[None, :]

    quarter_minutes[:, 0] += 0.55 * starter + 0.20 * core_player + 0.15 * playmaker_share - 0.35 * second_unit - 0.45 * garbage_unit
    quarter_minutes[:, 1] += 0.60 * second_unit + 0.25 * bench_player + 0.15 * garbage_time_fit - 0.30 * starter
    quarter_minutes[:, 2] += 0.35 * starter + 0.20 * core_player + 0.18 * scorer_share - 0.10 * garbage_unit
    quarter_minutes[:, 3] += 0.55 * closer + 0.20 * core_player - 0.25 * second_unit - 0.40 * garbage_unit

    competitive_float = competitive_mask.astype(float)
    blowout_float = blowout_mask.astype(float)
    leading_big = (team_margin_draws >= BLOWOUT_THRESHOLD).astype(float)
    trailing_big = (team_margin_draws <= -BLOWOUT_THRESHOLD).astype(float)

    star_signal = (0.44 * scorer_share) + (0.24 * playmaker_share) + (0.20 * core_player) + (0.12 * closer)
    playoff_blowout_shield = 1.0
    playoff_close_boost = 1.0
    
    if game_context and game_context.get("PLAYOFF_MODE"):
        # Stars get massively reduced blowout suppression (up to 70% reduction)
        playoff_blowout_shield = 1.0 - 0.70 * np.clip((star_signal - 0.3) / 0.4, 0.0, 1.0)
        # Stars get stronger close-game upside (up to 1.8x)
        playoff_close_boost = 1.0 + 0.8 * np.clip((star_signal - 0.4) / 0.4, 0.0, 1.0)

    quarter_minutes[:, 3] += competitive_float * (1.0 * closer + 0.9 * core_minutes_share + 0.40 * playmaker_share) * playoff_close_boost
    quarter_minutes[:, 3] -= leading_big * (1.2 * closer + 0.8 * core_minutes_share + 0.35 * scorer_share) * playoff_blowout_shield
    quarter_minutes[:, 3] -= trailing_big * (1.3 * closer + 0.9 * core_minutes_share + 0.30 * scorer_share) * playoff_blowout_shield
    quarter_minutes[:, 3] += blowout_float * (1.05 * garbage_unit + 0.75 * second_unit + 0.95 * garbage_time_fit + 0.30 * rebounder_share)
    quarter_minutes[:, 2] -= trailing_big * (0.45 * closer + 0.35 * core_minutes_share) * playoff_blowout_shield
    quarter_minutes[:, 2] += blowout_float * (0.35 * second_unit + 0.40 * garbage_unit + 0.20 * garbage_time_fit)

    quarter_minutes += rng.normal(0.0, 0.24 + (0.10 * volatile_share), (SIMULATION_RUNS, 4))
    quarter_minutes = np.clip(quarter_minutes, 0.0, 12.0)
    minutes = quarter_minutes.sum(axis=1)

    close_game_bonus = competitive_float * (0.25 + (0.55 * core_player)) * playoff_close_boost
    blowout_penalty = blowout_float * (
        (0.50 + (1.0 * core_minutes_share) + (0.45 * core_player))
        * (1.0 - (0.55 * low_minutes_share) - (0.25 * bench_player))
    ) * playoff_blowout_shield
    garbage_time_bonus = blowout_float * (
        (0.70 * low_minutes_share)
        + (0.70 * bench_player)
        + (0.75 * garbage_time_fit)
        + (0.25 * volatile_share)
    )
    if game_context:
        close_game_bonus *= float(game_context.get("CLOSE_GAME_BONUS_SCALE", 1.0))
        blowout_penalty *= float(game_context.get("BLOWOUT_PENALTY_SCALE", 1.0))
        if game_context.get("TEAM_FACES_ELIMINATION"):
            close_game_bonus += competitive_float * (0.30 + (0.75 * closer) + (0.45 * core_player)) * playoff_close_boost
            blowout_penalty *= 0.65  # Stronger resistance to blowouts in elimination games
    minutes += close_game_bonus - blowout_penalty + garbage_time_bonus

    if features["LOW_MIN_ROLE"]:
        minutes = np.minimum(minutes, 32.0)
    else:
        minutes = np.minimum(minutes, 40.0)

    minutes = np.clip(minutes, 0.0, None)
    # Rescale quarter buckets to the final minute total after caps/adjustments.
    quarter_sum = np.clip(quarter_minutes.sum(axis=1), 0.1, None)
    quarter_minutes *= (minutes / quarter_sum)[:, None]
    quarter_minutes = np.clip(quarter_minutes, 0.0, 12.0)
    minutes = quarter_minutes.sum(axis=1)
    minutes *= active_mask.astype(float)
    quarter_minutes *= active_mask.astype(float)[:, None]
    return minutes, quarter_minutes, active_mask, game_script, availability


def simulate_core_stat(stat, mean_value, mean_minutes, minutes_draws, features, game_script, rng):
    minute_basis = max(mean_minutes, 1.0)
    rate = max(mean_value, 0.0) / minute_basis
    minutes_ratio = np.divide(minutes_draws, minute_basis, out=np.zeros_like(minutes_draws), where=minute_basis > 0)
    script_centered = game_script - float(np.mean(game_script))

    baseline = rate * minutes_draws
    baseline *= 1.0 + (USAGE_COEFFICIENT[stat] * script_centered)
    baseline = np.clip(baseline, 0.0, None)

    if stat in {"STL", "BLK", "FG3M"}:
        lam = np.clip(baseline, 0.02, None)
        return rng.poisson(lam).astype(float)

    if stat == "PTS":
        raw_sigma = max(features["PTS_STD5"], 0.22 * mean_value + 1.7)
    elif stat == "REB":
        raw_sigma = max(features["REB_STD5"], 0.18 * mean_value + 1.2)
    else:
        raw_sigma = max(features["AST_STD5"], 0.20 * mean_value + 1.1)

    sigma = raw_sigma * np.sqrt(np.clip(minutes_ratio, 0.2, 1.8))
    noise = rng.normal(0.0, sigma, SIMULATION_RUNS)
    draws = np.clip(baseline + noise, 0.0, None)
    return draws


def simulate_rate_stat(mean_value, mean_minutes, minutes_draws, volatility_scale, game_script, rng, integer_output=False):
    minute_basis = max(mean_minutes, 1.0)
    rate = max(mean_value, 0.0) / minute_basis
    baseline = np.clip(rate * minutes_draws, 0.0, None)
    script_centered = game_script - float(np.mean(game_script))
    baseline *= 1.0 + (volatility_scale * script_centered)
    baseline = np.clip(baseline, 0.0, None)

    if integer_output:
        return rng.poisson(np.clip(baseline, 0.01, None)).astype(float)

    sigma = np.maximum(0.5, 0.20 * baseline + 0.35)
    draws = baseline + rng.normal(0.0, sigma, SIMULATION_RUNS)
    return np.clip(draws, 0.0, None)


def simulate_opening_window_stat(full_game_draws, mean_minutes, quarter_minutes, role_strength, rng, scale=1.0):
    opening_minutes_share = np.clip(
        np.divide(3.0, np.maximum(quarter_minutes[:, 0], 6.0)),
        0.16,
        0.50,
    )
    opener_multiplier = 0.88 + (0.22 * role_strength)
    first_quarter_share = np.divide(quarter_minutes[:, 0], np.maximum(quarter_minutes.sum(axis=1), 1.0))
    lam = np.clip(full_game_draws * first_quarter_share * opening_minutes_share * opener_multiplier * scale, 0.01, None)
    return rng.poisson(lam).astype(float)


def simulate_quarters_points_hits(points_draws, quarter_minutes, scorer_strength, rng, threshold):
    hot_hand = rng.normal(1.0, 0.08 + (0.05 * scorer_strength), SIMULATION_RUNS)
    quarter_share = np.divide(quarter_minutes, np.maximum(quarter_minutes.sum(axis=1, keepdims=True), 1.0))
    lam_per_quarter = np.clip(points_draws[:, None] * quarter_share * hot_hand[:, None], 0.01, None)
    quarter_points = rng.poisson(lam_per_quarter).astype(float)
    return (quarter_points >= threshold).sum(axis=1).astype(float)


def playoff_team_pool_blend_weight(base_weight, playoff_slate, role_fit, stat_key=""):
    if not playoff_slate:
        return float(base_weight)
    rf = role_fit or {}
    conc = (
        0.44 * float(rf.get("SCORER", 0.0))
        + 0.38 * float(rf.get("PLAYMAKER", 0.0))
        + 0.18 * float(rf.get("SHOOTER", 0.0))
    )
    bump = 0.075 + 0.135 * conc
    if stat_key == "TOV":
        bump *= 0.82
    return float(min(0.825, float(base_weight) + bump))


def blend_with_team_pool(player_draws, team_pool_draws, share, minutes_draws, mean_minutes, rng, noise_scale=0.08, blend_weight=0.58):
    if share <= 0:
        return player_draws

    minute_ratio = np.clip(
        np.divide(minutes_draws, max(mean_minutes, 1.0), out=np.zeros_like(minutes_draws), where=max(mean_minutes, 1.0) > 0),
        0.35,
        1.65,
    )
    activity_mask = (minutes_draws > 0).astype(float)
    allocation_noise = rng.normal(1.0, noise_scale, SIMULATION_RUNS)
    team_allocated = np.clip(
        team_pool_draws * share * (0.76 + (0.24 * minute_ratio)) * allocation_noise * activity_mask,
        0.0,
        None,
    )
    return np.clip((blend_weight * player_draws) + ((1.0 - blend_weight) * team_allocated), 0.0, None)


def soft_reconcile_team_stat(stat, player_mean, team_target_total, allocation_share, role_fit):
    player_mean = float(max(player_mean, 0.0))
    team_target_total = float(team_target_total) if team_target_total is not None else np.nan
    allocation_share = float(allocation_share or 0.0)
    debug = {
        "PRE": player_mean,
        "POST": player_mean,
        "ALLOCATED": np.nan,
        "MODE": "none",
    }

    if np.isnan(team_target_total) or team_target_total <= 0 or allocation_share <= 0 or player_mean <= 0:
        return player_mean, debug

    allocated_mean = max(0.0, team_target_total * allocation_share)
    debug["ALLOCATED"] = allocated_mean

    intrinsic_share = player_mean / max(team_target_total, 1.0)
    if stat == "PTS":
        leader_strength = np.clip(
            (0.48 * role_fit.get("SCORER", 0.0))
            + (0.18 * role_fit.get("SHOOTER", 0.0))
            + (0.18 * role_fit.get("CORE_PLAYER", 0.0))
            + (0.16 * min(1.0, intrinsic_share / 0.18)),
            0.0,
            1.0,
        )
    elif stat == "AST":
        leader_strength = np.clip(
            (0.52 * role_fit.get("PLAYMAKER", 0.0))
            + (0.16 * role_fit.get("SCORER", 0.0))
            + (0.16 * role_fit.get("CORE_PLAYER", 0.0))
            + (0.16 * min(1.0, intrinsic_share / 0.20)),
            0.0,
            1.0,
        )
    else:
        leader_strength = np.clip(
            (0.52 * role_fit.get("REBOUNDER", 0.0))
            + (0.18 * role_fit.get("RIM", 0.0))
            + (0.16 * role_fit.get("CORE_PLAYER", 0.0))
            + (0.14 * min(1.0, intrinsic_share / 0.18)),
            0.0,
            1.0,
        )

    share_gap = allocated_mean - player_mean
    base_blend = 0.14 + (0.16 * (1.0 - leader_strength))

    if share_gap < 0:
        # Stars can move down a bit for team realism, but not enough to erase their role.
        base_blend *= 0.80
        max_down = 0.08 + (0.16 * (1.0 - leader_strength))
        candidate = ((1.0 - base_blend) * player_mean) + (base_blend * allocated_mean)
        post = max(player_mean * (1.0 - max_down), candidate)
    else:
        # Non-stars can absorb more upward reconciliation than stars.
        max_up = 0.10 + (0.22 * (1.0 - leader_strength))
        candidate = ((1.0 - base_blend) * player_mean) + (base_blend * allocated_mean)
        post = min(player_mean * (1.0 + max_up), candidate)

    debug["POST"] = float(post)
    debug["MODE"] = "soft_reconcile"
    return float(post), debug


def summarize_distribution(draws):
    return {
        "P10": float(np.percentile(draws, 10)),
        "P50": float(np.percentile(draws, 50)),
        "P90": float(np.percentile(draws, 90)),
        "MEAN": float(np.mean(draws)),
        "STD": float(np.std(draws)),
    }


def summarize_active_distribution(draws, active_mask):
    active_draws = draws[active_mask.astype(bool)]
    if active_draws.size == 0:
        return summarize_distribution(draws)
    return summarize_distribution(active_draws)


def mark_published_rotation_pool(projections):
    if projections is None or projections.empty:
        return projections

    work = projections.copy()
    work["HAS_PROP_LINE"] = work.get("HAS_PROP_LINE", False).fillna(False).astype(bool)
    work = work.sort_values(
        ["TEAM_ABBREVIATION", "MIN_PROJ", "PTS_PROJ"],
        ascending=[True, False, False],
    ).copy()
    work["TEAM_ACTIVE_RANK"] = work.groupby("TEAM_ABBREVIATION").cumcount() + 1
    team_cum_minutes = work.groupby("TEAM_ABBREVIATION")["MIN_PROJ"].cumsum()
    core_player = work.get("ROTATION_TIER", "").fillna("").astype(str).str.upper().eq("CORE")
    publish_mask = (
        work["HAS_PROP_LINE"]
        | core_player
        | (work["TEAM_ACTIVE_RANK"] <= PUBLISHED_MIN_TEAM_PLAYERS)
        | ((team_cum_minutes - work["MIN_PROJ"]) < PUBLISHED_TEAM_MINUTE_TARGET)
    )
    work["TEAM_PUBLISHED_CUM_MIN"] = team_cum_minutes.round(2)
    work["PUBLISH_ACTIVE_ROTATION"] = publish_mask
    return work


def build_player_projection_core(
    player_row,
    logs_df,
    opponent_defense,
    league_defaults,
    injury_map,
    matchups,
    models,
    lineup_injury_context,
    archetypes,
    team_pace,
    league_pace,
    game_sim_contexts,
    playoff_slate=False,
):
    player_name = str(player_row.get("PLAYER_NAME", "")).strip()
    player_key = str(player_row["PLAYER_KEY"]).strip()
    player_logs = logs_df[logs_df["PLAYER_KEY"] == player_key].copy()
    if not player_logs.empty:
        player_logs = player_logs.sort_values("GAME_DATE", ascending=False)
    if player_logs.empty:
        return None, "missing_logs"
    # Authoritative current team: most recent box score (not lines_today.csv / book TEAM).
    team = str(player_logs.iloc[0]["TEAM_ABBREVIATION"]).strip().upper()
    if not player_name:
        player_name = str(player_logs.iloc[0].get("PLAYER_NAME", "")).strip()

    recent10 = player_logs.head(10).copy()
    recent5 = player_logs.head(5).copy()

    if len(recent10) < 5:
        return None, "insufficient_logs"

    avg_min_5 = rolling_mean(recent5, "MIN", 5)
    if avg_min_5 < 8:
        return None, "too_few_minutes"

    days_since_last_game = (pd.Timestamp.now().normalize() - recent10.iloc[0]["GAME_DATE"].normalize()).days
    if days_since_last_game > 25:
        return None, "stale_logs"

    matchup_info = matchups.get(team, {})
    opponent = matchup_info.get("OPPONENT", str(recent10.iloc[0]["OPP_TEAM_ABBREVIATION"]).strip().upper())
    matchup = matchup_info.get("MATCHUP", "")

    features = build_player_features(
        player_logs,
        team,
        opponent,
        opponent_defense,
        league_defaults,
        team_pace,
        league_pace,
        playoff_mode=playoff_slate,
    )
    injury_status = normalize_injury_status(injury_map.get(player_key, "ACTIVE"))
    if injury_status == "OUT":
        return None, "inactive_out"
    player_profile = archetypes.get(player_key, {})
    team_context = lineup_injury_context.get(team, {"ROLE_LOSSES": {key: 0.0 for key in ROLE_KEYS}, "USAGE_LOSS": 0.0})
    game_context = game_sim_contexts.get(team)
    role_losses = team_context["ROLE_LOSSES"]
    team_injury_impact = float(sum(role_losses.values()) / max(len(ROLE_KEYS), 1))
    role_fit = {
        "SCORER": player_profile.get("SCORER", 0.0),
        "PLAYMAKER": player_profile.get("PLAYMAKER", 0.0),
        "REBOUNDER": player_profile.get("REBOUNDER", 0.0),
        "RIM": player_profile.get("RIM", 0.0),
        "SHOOTER": player_profile.get("SHOOTER", 0.0),
        "CORE_PLAYER": player_profile.get("CORE_PLAYER", 0.0),
        "BENCH_PLAYER": player_profile.get("BENCH_PLAYER", 0.0),
        "GARBAGE_TIME_FIT": player_profile.get("GARBAGE_TIME_FIT", 0.0),
        "STARTER": player_profile.get("STARTER", 0.0),
        "CLOSER": player_profile.get("CLOSER", 0.0),
        "SECOND_UNIT": player_profile.get("SECOND_UNIT", 0.0),
        "GARBAGE_UNIT": player_profile.get("GARBAGE_UNIT", 0.0),
        "ROTATION_TIER": player_profile.get("ROTATION_TIER", ""),
        "TEMPLATE_MINUTES": player_profile.get("TEMPLATE_MINUTES", 0.0),
        "TEMPLATE_GAMES": player_profile.get("TEMPLATE_GAMES", 0.0),
        "TEMPLATE_SAMPLE_WEIGHT": player_profile.get("TEMPLATE_SAMPLE_WEIGHT", 0.0),
        "TEMPLATE_Q1_SHARE": player_profile.get("TEMPLATE_Q1_SHARE", 0.25),
        "TEMPLATE_Q2_SHARE": player_profile.get("TEMPLATE_Q2_SHARE", 0.25),
        "TEMPLATE_Q3_SHARE": player_profile.get("TEMPLATE_Q3_SHARE", 0.25),
        "TEMPLATE_Q4_SHARE": player_profile.get("TEMPLATE_Q4_SHARE", 0.25),
    }
    if playoff_slate and player_profile:
        ls = float(player_profile.get("LIKELY_STARTER", 0.0))
        lc = float(player_profile.get("LIKELY_CLOSER", 0.0))
        role_fit["STARTER"] = float(np.clip(0.52 * role_fit["STARTER"] + 0.48 * ls, 0.0, 1.0))
        role_fit["CLOSER"] = float(np.clip(0.52 * role_fit["CLOSER"] + 0.48 * lc, 0.0, 1.0))
    expected_team_margin = float(game_context["EXPECTED_MARGIN"]) if game_context else 0.0
    market_spread = float(game_context["MARKET_SPREAD"]) if game_context and not pd.isna(game_context.get("MARKET_SPREAD")) else np.nan
    market_total = float(game_context["MARKET_TOTAL"]) if game_context and not pd.isna(game_context.get("MARKET_TOTAL")) else np.nan
    implied_team_total = float(game_context["IMPLIED_TEAM_TOTAL"]) if game_context and not pd.isna(game_context.get("IMPLIED_TEAM_TOTAL")) else np.nan
    allocation = team_context.get("PLAYER_ALLOCATION", {}).get(
        player_key,
        {"PTS_SHARE": 0.0, "AST_SHARE": 0.0, "REB_SHARE": 0.0, "FG3M_SHARE": 0.0, "TOV_SHARE": 0.0, "FGA_SHARE": 0.0, "FTA_SHARE": 0.0},
    )

    minutes_model = models.get("MIN")
    mean_minutes = minutes_projection(
        predict_with_model(minutes_model, features, MINUTES_FEATURES),
        features,
        playoff_mode=playoff_slate,
    )

    playoff_minutes_prior = 0.0
    playoff_prior_kind = ""
    playoff_prior_source = ""
    playoff_prior_confidence = ""
    playoff_prior_games_used = 0
    if playoff_slate:
        playoff_prior = compute_locked_playoff_minutes_prior(player_logs, player_profile, features)
        playoff_minutes_prior = float(playoff_prior.get("minutes", 0.0))
        playoff_prior_kind = str(playoff_prior.get("kind", ""))
        playoff_prior_source = str(playoff_prior.get("source", ""))
        playoff_prior_confidence = str(playoff_prior.get("confidence", ""))
        playoff_prior_games_used = int(playoff_prior.get("games_used", 0))
        if player_profile is not None:
            player_profile["playoff_minute_anchor"] = round(float(playoff_minutes_prior), 2)
            player_profile["playoff_anchor_source"] = playoff_prior_source
            player_profile["playoff_anchor_games_used"] = playoff_prior_games_used
            player_profile["playoff_anchor_confidence"] = playoff_prior_confidence
            player_profile["playoff_prior_kind"] = playoff_prior_kind
        if playoff_minutes_prior > 0:
            # True playoff minutes are hard evidence; regular-season fallback is only
            # an approximation and must not create fake playoff certainty.
            p_games = playoff_prior_games_used
            if playoff_prior_kind == "true_playoff" and p_games >= 4:
                prior_weight = 0.92
            elif playoff_prior_kind == "true_playoff" and p_games >= 2:
                prior_weight = 0.88
            elif playoff_prior_kind == "true_playoff":
                prior_weight = 0.85
            else:
                prior_weight = 0.56
            mean_minutes = (prior_weight * playoff_minutes_prior) + ((1.0 - prior_weight) * mean_minutes)

    if player_key in _TRACE_KEYS:
        print(
            f"[TRACE:PRIOR] {player_key} | "
            f"PLAYOFF_GAMES={player_profile.get('PLAYOFF_GAMES', 0)} | "
            f"PLAYOFF_MIN={round(player_profile.get('PLAYOFF_MIN', 0.0), 2)} | "
            f"PLAYOFF_STARTS={player_profile.get('PLAYOFF_STARTS', 0)} | "
            f"PLAYOFF_START_RATE={round(player_profile.get('PLAYOFF_START_RATE', 0.0), 2)} | "
            f"MINUTE_RANK_TEAM={player_profile.get('MINUTE_RANK_TEAM', 99)} | "
            f"USAGE_RANK_TEAM={player_profile.get('USAGE_RANK_TEAM', 99)} | "
            f"playoff_minutes_prior={round(playoff_minutes_prior, 2)} | "
            f"prior_kind={playoff_prior_kind} | "
            f"mean_minutes_before_protect={round(mean_minutes, 2)}"
        )

    protected_min_floor = 0.0
    if injury_status not in {"OUT", "DOUBTFUL"}:
        mean_minutes, protected_min_floor = protect_core_minutes(
            mean_minutes,
            player_logs,
            features,
            role_fit,
            playoff_mode=playoff_slate,
            player_profile=player_profile,
            playoff_minutes_prior=playoff_minutes_prior if playoff_prior_kind == "true_playoff" else 0.0,
        )
        if player_key in _TRACE_KEYS:
            print(
                f"[TRACE:PROTECT] {player_key} | "
                f"mean_minutes_after_protect={round(mean_minutes, 2)} | "
                f"protected_floor={round(protected_min_floor, 2)} | "
                f"anchor_source={player_profile.get('playoff_anchor_source', 'n/a')} | "
                f"anchor_value={round(player_profile.get('playoff_minute_anchor', 0.0), 2)}"
            )
    role_fit["PROTECTED_MIN_FLOOR"] = protected_min_floor
    if injury_status not in {"OUT", "DOUBTFUL"}:
        mean_minutes = apply_playoff_rotation_tightening(mean_minutes, role_fit, player_profile, playoff_slate)

    star_signal_pre = (
        (0.44 * role_fit["SCORER"])
        + (0.24 * role_fit["PLAYMAKER"])
        + (0.20 * role_fit["CORE_PLAYER"])
        + (0.12 * role_fit["CLOSER"])
    )
    gctx_pre = game_sim_contexts.get(team) if game_sim_contexts else None
    if playoff_slate and injury_status not in {"OUT", "DOUBTFUL"}:
        leverage = float(matchup_info.get("MUST_WIN_LEVERAGE", 0.0) or 0.0)
        if leverage > 0:
            mean_minutes += leverage * (1.15 + 2.35 * star_signal_pre) * max(role_fit["STARTER"], role_fit["CLOSER"])
        if gctx_pre and gctx_pre.get("TEAM_FACES_ELIMINATION"):
            mean_minutes += min(4.2, (1.85 + 2.45 * star_signal_pre) * max(role_fit["STARTER"], role_fit["CLOSER"]))

    if injury_status not in {"OUT", "DOUBTFUL"}:
        minute_fit = (
            0.34 * role_fit["SCORER"]
            + 0.36 * role_fit["PLAYMAKER"]
            + 0.18 * role_fit["REBOUNDER"]
            + 0.12 * role_fit["RIM"]
        )
        usage_loss_eff = float(team_context["USAGE_LOSS"]) * (1.32 if playoff_slate else 1.0)
        max_minutes_bump = 0.22 if playoff_slate else 0.13
        minutes_bump = 1.0 + min(max_minutes_bump, (0.025 + (0.04 * minute_fit)) * usage_loss_eff)
        mean_minutes *= minutes_bump

    stat_means = {}
    for stat in STAT_TARGETS:
        stat_means[stat] = blended_stat_projection(
            stat,
            predict_with_model(models.get(stat), features, MODEL_FEATURES),
            features,
            playoff_mode=playoff_slate,
        )

    stat_means["PTS"] = protect_core_scoring_mean(
        stat_means["PTS"],
        mean_minutes,
        player_logs,
        features,
        role_fit,
        protected_min_floor,
    )
    stat_means["AST"] = protect_core_assist_mean(
        stat_means["AST"],
        mean_minutes,
        player_logs,
        features,
        role_fit,
        protected_min_floor,
    )

    if injury_status not in {"OUT", "DOUBTFUL"} and team_context["USAGE_LOSS"] > 0:
        scorer_bump = min(0.20, role_losses["SCORER"] * (0.03 + 0.12 * role_fit["SCORER"]))
        playmaker_bump = min(0.20, role_losses["PLAYMAKER"] * (0.03 + 0.14 * role_fit["PLAYMAKER"]))
        rebound_bump = min(0.12, role_losses["REBOUNDER"] * (0.02 + 0.10 * role_fit["REBOUNDER"]))
        rim_bump = min(0.10, role_losses["RIM"] * (0.02 + 0.10 * role_fit["RIM"]))
        shooter_bump = min(0.16, role_losses["SHOOTER"] * (0.03 + 0.11 * role_fit["SHOOTER"]))

        stat_means["PTS"] *= 1.0 + scorer_bump + (0.35 * shooter_bump)
        stat_means["AST"] *= 1.0 + playmaker_bump + (0.18 * scorer_bump)
        stat_means["REB"] *= 1.0 + rebound_bump + (0.15 * rim_bump)
        stat_means["BLK"] *= 1.0 + rim_bump
        stat_means["FG3M"] *= 1.0 + shooter_bump + (0.20 * scorer_bump)

    pace_ratio = features["EXPECTED_PACE"] / max(league_pace, 1.0)
    pace_multiplier = min(1.08, max(0.94, pace_ratio))
    mean_minutes *= min(1.03, max(0.97, 1.0 + ((pace_multiplier - 1.0) * 0.35)))
    if playoff_slate:
        mean_minutes = float(np.clip(mean_minutes, 0.0, 44.5))

    # Structural guard: cap ALL downstream movement to the playoff prior.
    # This prevents rotation tightening, usage-loss bumps, or pace adjustments
    # from overriding the primary source of truth.
    if playoff_slate and playoff_minutes_prior > 0 and playoff_prior_kind == "true_playoff":
        tier = playoff_closure_priority_tier({
            "role_fit": role_fit,
            "player_profile": player_profile,
            "mean_minutes": mean_minutes,
        })
        max_delta = 2.5 if tier == 1 else 3.0 if tier == 2 else 4.0 if tier == 3 else 5.0
        mean_minutes = float(np.clip(mean_minutes, playoff_minutes_prior - max_delta, playoff_minutes_prior + max_delta))

    if player_key in _TRACE_KEYS:
        print(
            f"[TRACE:PRE_CLOSURE] {player_key} | "
            f"mean_minutes_pre_closure={round(mean_minutes, 2)} | "
            f"star_signal={round((0.44 * role_fit['SCORER'] + 0.24 * role_fit['PLAYMAKER'] + 0.20 * role_fit['CORE_PLAYER'] + 0.12 * role_fit['CLOSER']), 3)} | "
            f"starter={round(role_fit['STARTER'], 2)} | "
            f"closer={round(role_fit['CLOSER'], 2)}"
        )

    base_team_points = float(team_context.get("BASELINE_TEAM_POINTS", np.nan))
    base_team_ast = float(team_context.get("BASELINE_TEAM_AST", np.nan))
    base_team_reb = float(team_context.get("BASELINE_TEAM_REB", np.nan))
    team_balance_debug = {
        "PTS": {"PRE": float(stat_means["PTS"]), "POST": float(stat_means["PTS"]), "ALLOCATED": np.nan, "MODE": "none"},
        "REB": {"PRE": float(stat_means["REB"]), "POST": float(stat_means["REB"]), "ALLOCATED": np.nan, "MODE": "none"},
        "AST": {"PRE": float(stat_means["AST"]), "POST": float(stat_means["AST"]), "ALLOCATED": np.nan, "MODE": "none"},
    }
    if not np.isnan(implied_team_total) and not np.isnan(base_team_points) and base_team_points > 0:
        team_total_ratio = implied_team_total / base_team_points
        scoring_env = min(1.12, max(0.90, 1.0 + (TEAM_TOTAL_BLEND * (team_total_ratio - 1.0))))
        assist_env = min(1.10, max(0.91, 1.0 + (0.85 * TEAM_TOTAL_BLEND * (team_total_ratio - 1.0))))
        rebound_env = min(1.08, max(0.94, 1.0 + (0.30 * (team_total_ratio - 1.0))))
        usage_anchor = 0.55 + (0.45 * role_fit["SCORER"])
        shot_anchor = 0.55 + (0.35 * role_fit["SHOOTER"]) + (0.10 * role_fit["CORE_PLAYER"])
        stat_means["PTS"] *= 1.0 + ((scoring_env - 1.0) * usage_anchor)
        stat_means["AST"] *= 1.0 + ((assist_env - 1.0) * (0.60 + 0.40 * role_fit["PLAYMAKER"]))
        stat_means["FG3M"] *= 1.0 + ((scoring_env - 1.0) * shot_anchor)
        stat_means["PTS"], team_balance_debug["PTS"] = soft_reconcile_team_stat(
            "PTS",
            stat_means["PTS"],
            implied_team_total,
            allocation["PTS_SHARE"],
            role_fit,
        )
        stat_means["AST"], team_balance_debug["AST"] = soft_reconcile_team_stat(
            "AST",
            stat_means["AST"],
            (base_team_ast * assist_env) if not np.isnan(base_team_ast) and base_team_ast > 0 else np.nan,
            allocation["AST_SHARE"],
            role_fit,
        )
        stat_means["REB"], team_balance_debug["REB"] = soft_reconcile_team_stat(
            "REB",
            stat_means["REB"],
            (base_team_reb * rebound_env) if not np.isnan(base_team_reb) and base_team_reb > 0 else np.nan,
            allocation["REB_SHARE"],
            role_fit,
        )

    stat_means["REB"] = control_rebound_inflation_mean(
        stat_means["REB"],
        mean_minutes,
        player_logs,
        features,
        role_fit,
    )
    stat_means["FG3M"] = protect_shooter_fg3m_mean(
        stat_means["FG3M"],
        mean_minutes,
        player_logs,
        features,
        role_fit,
    )

    rate_means = {
        "FTM": float(weighted_recent_mean(recent5, recent10, "FTM")),
        "FTA": float(weighted_recent_mean(recent5, recent10, "FTA")),
        "FGM": float(weighted_recent_mean(recent5, recent10, "FGM")),
        "FGA": float(weighted_recent_mean(recent5, recent10, "FGA")),
        "FG2M": float(weighted_recent_mean(recent5, recent10, "FG2M")),
        "FG2A": float(weighted_recent_mean(recent5, recent10, "FG2A")),
        "FG3A": float(weighted_recent_mean(recent5, recent10, "FG3A")),
        "TOV": float(weighted_recent_mean(recent5, recent10, "TOV")),
    }

    core = {
        "player_name": player_name,
        "player_key": player_key,
        "team": team,
        "opponent": opponent,
        "matchup": matchup,
        "matchup_info": matchup_info,
        "player_logs": player_logs,
        "recent10": recent10,
        "recent5": recent5,
        "avg_min_5": avg_min_5,
        "features": features,
        "injury_status": injury_status,
        "player_profile": player_profile,
        "team_context": team_context,
        "game_context": game_context,
        "role_losses": role_losses,
        "team_injury_impact": team_injury_impact,
        "role_fit": role_fit,
        "allocation": allocation,
        "mean_minutes": float(mean_minutes),
        "protected_min_floor": protected_min_floor,
        "stat_means": stat_means,
        "team_balance_debug": team_balance_debug,
        "pace_multiplier": pace_multiplier,
        "expected_team_margin": expected_team_margin,
        "market_spread": market_spread,
        "market_total": market_total,
        "implied_team_total": implied_team_total,
        "playoff_slate": playoff_slate,
        "models": models,
        "team_rotation_structure": None,
        "mean_minutes_pre_closure": None,
        "playoff_role_label": None,
        "rate_means": rate_means,
        "league_defaults": league_defaults,
        "playoff_diagnostics": None,
        "playoff_minutes_prior": float(playoff_minutes_prior),
        "playoff_prior_kind": playoff_prior_kind,
        "playoff_prior_source": playoff_prior_source,
        "playoff_prior_confidence": playoff_prior_confidence,
        "playoff_prior_games_used": playoff_prior_games_used,
        "sim_minutes_bundle": None,
    }
    return core, None


def finalize_player_projection_from_core(core):
    player_name = core["player_name"]
    player_key = core["player_key"]
    team = core["team"]
    opponent = core["opponent"]
    matchup = core["matchup"]
    player_logs = core["player_logs"]
    recent10 = core["recent10"]
    recent5 = core["recent5"]
    avg_min_5 = core["avg_min_5"]
    features = core["features"]
    injury_status = core["injury_status"]
    player_profile = core["player_profile"]
    team_context = core["team_context"]
    game_context = core["game_context"]
    role_losses = core["role_losses"]
    team_injury_impact = core["team_injury_impact"]
    role_fit = core["role_fit"]
    allocation = core["allocation"]
    mean_minutes = float(core["mean_minutes"])
    stat_means = core["stat_means"]
    team_balance_debug = core["team_balance_debug"]
    pace_multiplier = core["pace_multiplier"]
    expected_team_margin = core["expected_team_margin"]
    market_spread = core["market_spread"]
    market_total = core["market_total"]
    implied_team_total = core["implied_team_total"]
    playoff_slate = core["playoff_slate"]
    rm = core.get("rate_means")

    rng_seed = abs(hash((player_key, current_projection_date()))) % (2 ** 32)
    rng = np.random.default_rng(rng_seed)
    sim_bundle = core.get("sim_minutes_bundle")
    if sim_bundle:
        minutes_draws = sim_bundle["minutes_draws"]
        quarter_minutes = sim_bundle["quarter_minutes"]
        active_mask = sim_bundle["active_mask"]
        game_script = sim_bundle["game_script"]
        availability = sim_bundle["availability"]
    else:
        minutes_draws, quarter_minutes, active_mask, game_script, availability = simulate_minutes(
            mean_minutes,
            features,
            injury_status,
            rng,
            role_fit,
            game_context=game_context,
        )

    stat_draws = {}
    stat_summaries = {}
    for stat in STAT_TARGETS:
        draws = simulate_core_stat(stat, stat_means[stat], mean_minutes, minutes_draws, features, game_script, rng)
        draws *= active_mask.astype(float)
        if game_context is not None:
            if stat == "FG3M":
                fg3m_blend_weight = min(
                    0.82,
                    0.60 + (0.16 * role_fit["SHOOTER"]) + (0.06 * role_fit["SCORER"]),
                )
                fg3m_blend_weight = playoff_team_pool_blend_weight(
                    fg3m_blend_weight, playoff_slate, role_fit, "FG3M"
                )
                draws = blend_with_team_pool(
                    draws,
                    game_context["TEAM_FG3M_DRAWS"],
                    allocation["FG3M_SHARE"],
                    minutes_draws,
                    mean_minutes,
                    rng,
                    noise_scale=0.09,
                    blend_weight=fg3m_blend_weight,
                )
        stat_draws[stat] = draws
        stat_summaries[stat] = summarize_distribution(draws)

    if rm:
        tov_mean = max(0.0, float(rm.get("TOV", 0.0)))
    else:
        tov_mean = max(0.0, (0.55 * safe_mean(recent5["TOV"])) + (0.45 * safe_mean(recent10["TOV"])))
    tov_rate = tov_mean / max(mean_minutes, 1.0)
    tov_draws = rng.poisson(np.clip(tov_rate * minutes_draws, 0.01, None)).astype(float)
    tov_draws *= active_mask.astype(float)
    if game_context is not None:
        tov_draws = blend_with_team_pool(
            tov_draws,
            game_context["TEAM_TOV_DRAWS"],
            allocation["TOV_SHARE"],
            minutes_draws,
            mean_minutes,
            rng,
            noise_scale=0.08,
            blend_weight=playoff_team_pool_blend_weight(0.62, playoff_slate, role_fit, "TOV"),
        )
    tov_summary = summarize_distribution(tov_draws)

    if rm:
        ftm_mean = float(rm["FTM"])
        fta_mean = float(rm["FTA"])
        fgm_mean = float(rm["FGM"])
        fga_mean = float(rm["FGA"])
        fg3a_mean = float(rm["FG3A"])
        fg3_for_split = min(float(stat_means["FG3M"]), max(0.0, fgm_mean))
        fg2m_mean = max(0.0, fgm_mean - fg3_for_split)
        fg2a_mean = max(0.0, fga_mean - fg3a_mean, fg2m_mean)
    else:
        ftm_mean = weighted_recent_mean(recent5, recent10, "FTM")
        fta_mean = weighted_recent_mean(recent5, recent10, "FTA")
        fgm_mean = weighted_recent_mean(recent5, recent10, "FGM")
        fga_mean = weighted_recent_mean(recent5, recent10, "FGA")
        fg2m_mean = weighted_recent_mean(recent5, recent10, "FG2M")
        fg2a_mean = weighted_recent_mean(recent5, recent10, "FG2A")
        fg3a_mean = weighted_recent_mean(recent5, recent10, "FG3A")
    oreb_mean = weighted_recent_mean(recent5, recent10, "OREB")
    dreb_mean = weighted_recent_mean(recent5, recent10, "DREB")
    pf_mean = weighted_recent_mean(recent5, recent10, "PF")

    ftm_draws = simulate_rate_stat(ftm_mean, mean_minutes, minutes_draws, 0.08, game_script, rng, integer_output=True) * active_mask.astype(float)
    fta_draws = simulate_rate_stat(fta_mean, mean_minutes, minutes_draws, 0.09, game_script, rng, integer_output=True) * active_mask.astype(float)
    fgm_draws = simulate_rate_stat(fgm_mean, mean_minutes, minutes_draws, 0.08, game_script, rng, integer_output=True) * active_mask.astype(float)
    fga_draws = simulate_rate_stat(fga_mean, mean_minutes, minutes_draws, 0.10, game_script, rng, integer_output=True) * active_mask.astype(float)
    if game_context is not None:
        fta_draws = blend_with_team_pool(
            fta_draws,
            game_context["TEAM_FTA_DRAWS"],
            allocation["FTA_SHARE"],
            minutes_draws,
            mean_minutes,
            rng,
            noise_scale=0.08,
            blend_weight=playoff_team_pool_blend_weight(0.58, playoff_slate, role_fit, "FTA"),
        )
        ftm_draws = np.minimum(
            blend_with_team_pool(
                ftm_draws,
                game_context["TEAM_FTM_DRAWS"],
                allocation["FTA_SHARE"],
                minutes_draws,
                mean_minutes,
                rng,
                noise_scale=0.08,
                blend_weight=playoff_team_pool_blend_weight(0.58, playoff_slate, role_fit, "FTM"),
            ),
            np.maximum(fta_draws, 0.0),
        )
        fga_draws = blend_with_team_pool(
            fga_draws,
            game_context["TEAM_FGA_DRAWS"],
            allocation["FGA_SHARE"],
            minutes_draws,
            mean_minutes,
            rng,
            noise_scale=0.07,
            blend_weight=playoff_team_pool_blend_weight(0.58, playoff_slate, role_fit, "FGA"),
        )
        fgm_draws = np.minimum(
            blend_with_team_pool(
                fgm_draws,
                game_context["TEAM_FGM_DRAWS"],
                allocation["FGA_SHARE"],
                minutes_draws,
                mean_minutes,
                rng,
                noise_scale=0.07,
                blend_weight=playoff_team_pool_blend_weight(0.60, playoff_slate, role_fit, "FGM"),
            ),
            np.maximum(fga_draws, 0.0),
        )
    fg2m_draws = np.minimum(
        simulate_rate_stat(fg2m_mean, mean_minutes, minutes_draws, 0.08, game_script, rng, integer_output=True),
        np.maximum(fgm_draws, 0.0),
    ) * active_mask.astype(float)
    fg2a_draws = np.minimum(
        simulate_rate_stat(fg2a_mean, mean_minutes, minutes_draws, 0.10, game_script, rng, integer_output=True),
        np.maximum(fga_draws, 0.0),
    ) * active_mask.astype(float)
    fg3a_draws = np.minimum(
        simulate_rate_stat(fg3a_mean, mean_minutes, minutes_draws, 0.10, game_script, rng, integer_output=True),
        np.maximum(fga_draws, 0.0),
    ) * active_mask.astype(float)
    oreb_draws = simulate_rate_stat(oreb_mean, mean_minutes, minutes_draws, 0.05, game_script, rng, integer_output=True) * active_mask.astype(float)
    dreb_draws = simulate_rate_stat(dreb_mean, mean_minutes, minutes_draws, 0.05, game_script, rng, integer_output=True) * active_mask.astype(float)
    pf_draws = simulate_rate_stat(pf_mean, mean_minutes, minutes_draws, 0.03, game_script, rng, integer_output=True) * active_mask.astype(float)
    dunk_base_rate = np.clip(
        (safe_divide(fg2m_mean, max(mean_minutes, 1.0)) * (0.10 + (0.40 * role_fit["RIM"]) + (0.15 * role_fit["SCORER"]))),
        0.0,
        None,
    )
    dunk_draws = rng.poisson(np.clip(dunk_base_rate * minutes_draws, 0.01, None)).astype(float) * active_mask.astype(float)

    pts_3m_draws = simulate_opening_window_stat(stat_draws["PTS"], mean_minutes, quarter_minutes, role_fit["SCORER"], rng) * active_mask.astype(float)
    ast_3m_draws = simulate_opening_window_stat(stat_draws["AST"], mean_minutes, quarter_minutes, role_fit["PLAYMAKER"], rng, scale=0.78) * active_mask.astype(float)
    reb_3m_draws = simulate_opening_window_stat(stat_draws["REB"], mean_minutes, quarter_minutes, role_fit["REBOUNDER"], rng, scale=0.92) * active_mask.astype(float)
    q3p_draws = simulate_quarters_points_hits(stat_draws["PTS"], quarter_minutes, role_fit["SCORER"], rng, threshold=3) * active_mask.astype(float)
    q5p_draws = simulate_quarters_points_hits(stat_draws["PTS"], quarter_minutes, role_fit["SCORER"], rng, threshold=5) * active_mask.astype(float)

    fantasy_draws = (
        stat_draws["PTS"]
        + 1.2 * stat_draws["REB"]
        + 1.5 * stat_draws["AST"]
        + 3.0 * stat_draws["STL"]
        + 3.0 * stat_draws["BLK"]
        + 0.5 * stat_draws["FG3M"]
        - tov_draws
    )
    dd_hits = (
        (stat_draws["PTS"] >= 10).astype(int)
        + (stat_draws["REB"] >= 10).astype(int)
        + (stat_draws["AST"] >= 10).astype(int)
        + (stat_draws["STL"] >= 10).astype(int)
        + (stat_draws["BLK"] >= 10).astype(int)
    ) >= 2
    td_hits = (
        (stat_draws["PTS"] >= 10).astype(int)
        + (stat_draws["REB"] >= 10).astype(int)
        + (stat_draws["AST"] >= 10).astype(int)
        + (stat_draws["STL"] >= 10).astype(int)
        + (stat_draws["BLK"] >= 10).astype(int)
    ) >= 3

    supplemental_draws = {
        "FTM": ftm_draws,
        "FTA": fta_draws,
        "FGM": fgm_draws,
        "FGA": fga_draws,
        "FG2M": fg2m_draws,
        "FG2A": fg2a_draws,
        "FG3A": fg3a_draws,
        "OREB": oreb_draws,
        "DREB": dreb_draws,
        "PF": pf_draws,
        "DUNKS": dunk_draws,
        "FANTASY": fantasy_draws,
        "DD": dd_hits.astype(float),
        "TD": td_hits.astype(float),
        "PTS_3M": pts_3m_draws,
        "AST_3M": ast_3m_draws,
        "REB_3M": reb_3m_draws,
        "Q3P": q3p_draws,
        "Q5P": q5p_draws,
    }

    min_summary = summarize_distribution(minutes_draws)
    active_min_summary = summarize_active_distribution(minutes_draws, active_mask)

    conf_num, model_conf, conf_label = confidence_from_profile(features, len(recent10), availability)
    if playoff_slate and core.get("playoff_prior_kind") == "rs_fallback":
        conf_num = max(0.05, conf_num - 0.08)
        model_conf = "MEDIUM" if model_conf == "HIGH" else model_conf
        conf_label = "Medium" if conf_label == "High" else conf_label
    if game_context and game_context.get("MARKET_GUARDRAIL_MODE") != "market":
        conf_num = max(0.05, conf_num - 0.04)
        model_conf = "MEDIUM" if model_conf == "HIGH" else model_conf
        conf_label = "Medium" if conf_label == "High" else conf_label
    spot_stability = spot_stability_bucket(features, injury_status, role_fit, playoff_slate, player_profile)

    row = {
        "GAME_DATE": current_projection_date(),
        "PLAYER_KEY": player_key,
        "PLAYER_NAME": player_name,
        "TEAM_ABBREVIATION": team,
        "OPPONENT": opponent,
        "MATCHUP": matchup,
        "SIM_RUNS": SIMULATION_RUNS,
        "ACTIVE_PROB": round(float(availability), 4),
        "TEAM_INJURY_IMPACT": round(float(team_injury_impact), 4),
        "ARCHETYPE_SCORER": round(float(role_fit["SCORER"]), 4),
        "ARCHETYPE_PLAYMAKER": round(float(role_fit["PLAYMAKER"]), 4),
        "ARCHETYPE_REBOUNDER": round(float(role_fit["REBOUNDER"]), 4),
        "ARCHETYPE_RIM": round(float(role_fit["RIM"]), 4),
        "ARCHETYPE_SHOOTER": round(float(role_fit["SHOOTER"]), 4),
        "EXPECTED_PACE": round(float(features["EXPECTED_PACE"]), 2),
        "PACE_MULTIPLIER": round(float(pace_multiplier), 4),
        "EXPECTED_TEAM_MARGIN": round(expected_team_margin, 2),
        "BLOWOUT_RISK": round(float(np.mean(np.abs(game_context["TEAM_MARGIN_DRAWS"]) >= BLOWOUT_THRESHOLD)) if game_context else 0.0, 4),
        "MARKET_SPREAD": round(market_spread, 2) if not np.isnan(market_spread) else np.nan,
        "MARKET_TOTAL": round(market_total, 2) if not np.isnan(market_total) else np.nan,
        "IMPLIED_TEAM_TOTAL": round(implied_team_total, 2) if not np.isnan(implied_team_total) else np.nan,
        "ROTATION_TIER": player_profile.get("ROTATION_TIER", ""),
        "ROTATION_TEMPLATE_GAMES": round(float(player_profile.get("TEMPLATE_GAMES", 0.0)), 2),
        "ROTATION_TEMPLATE_MIN": round(float(player_profile.get("TEMPLATE_MINUTES", 0.0)), 2),
        "INJURY_STATUS": injury_status,
        "CONFIDENCE": round(float(conf_num), 2),
        "BET_CONFIDENCE": round(float(conf_num), 2),
        "MODEL_CONFIDENCE": model_conf,
        "CONFIDENCE_LABEL": conf_label,
        "SPOT_STABILITY": spot_stability,
        "PLAYOFF_ROLE": str(core.get("playoff_role_label") or "") if playoff_slate else "",
        "PLAYOFF_SLATE": bool(playoff_slate),
        "TEAM_FACES_ELIMINATION": bool(game_context.get("TEAM_FACES_ELIMINATION")) if game_context else False,
        "PLAYOFF_CLOSURE_TIER": int(playoff_closure_priority_tier(core)) if playoff_slate else np.nan,
        "MIN_PRE_CLOSURE": round(float(core["mean_minutes_pre_closure"]), 2) if core.get("mean_minutes_pre_closure") is not None else np.nan,
        "MIN_CLOSURE_DELTA": round(float(mean_minutes - float(core["mean_minutes_pre_closure"])), 2) if core.get("mean_minutes_pre_closure") is not None else np.nan,
        "projected_rotation_size": (core.get("team_rotation_structure") or {}).get("projected_rotation_size", np.nan),
        "projected_core_5": (core.get("team_rotation_structure") or {}).get("projected_core_5", ""),
        "projected_core_7": (core.get("team_rotation_structure") or {}).get("projected_core_7", ""),
        "projected_closing_group": (core.get("team_rotation_structure") or {}).get("projected_closing_group", ""),
        "fringe_rotation_risk": (core.get("team_rotation_structure") or {}).get("fringe_rotation_risk", np.nan),
        "TEAM_MINUTES_CLOSED_SUM": (core.get("team_rotation_structure") or {}).get("TEAM_MINUTES_CLOSED_SUM", np.nan),
        "PLAYOFF_TRACE_CLOSURE": str((core.get("playoff_diagnostics") or {}).get("PLAYOFF_TRACE_CLOSURE", "")) if playoff_slate else "",
        "PLAYOFF_TRACE_USAGE_CONC": (core.get("playoff_diagnostics") or {}).get("PLAYOFF_TRACE_USAGE_CONC", np.nan) if playoff_slate else np.nan,
        "PLAYOFF_TRACE_CREATOR_CTX": (core.get("playoff_diagnostics") or {}).get("PLAYOFF_TRACE_CREATOR_CTX", np.nan) if playoff_slate else np.nan,
        "PLAYOFF_TRACE_LINEUP_CRED": (core.get("playoff_diagnostics") or {}).get("PLAYOFF_TRACE_LINEUP_CRED", np.nan) if playoff_slate else np.nan,
        "PLAYOFF_TRACE_MATCHUP_ENV": (core.get("playoff_diagnostics") or {}).get("PLAYOFF_TRACE_MATCHUP_ENV", np.nan) if playoff_slate else np.nan,
        "PLAYOFF_TRACE_LINEUP_LAYER": (core.get("playoff_diagnostics") or {}).get("PLAYOFF_TRACE_LINEUP_LAYER", np.nan) if playoff_slate else np.nan,
        "PLAYOFF_TRACE_COMPOSITE": (core.get("playoff_diagnostics") or {}).get("PLAYOFF_TRACE_COMPOSITE", np.nan) if playoff_slate else np.nan,
        "PLAYOFF_MINUTE_ANCHOR": round(float((core.get("player_profile") or {}).get("playoff_minute_anchor", np.nan)), 2) if playoff_slate else np.nan,
        "PLAYOFF_ANCHOR_SOURCE": str((core.get("player_profile") or {}).get("playoff_anchor_source", "")) if playoff_slate else "",
        "PLAYOFF_ANCHOR_GAMES_USED": (core.get("player_profile") or {}).get("playoff_anchor_games_used", 0) if playoff_slate else 0,
        "PLAYOFF_ANCHOR_CONFIDENCE": str((core.get("player_profile") or {}).get("playoff_anchor_confidence", "")) if playoff_slate else "",
        "PLAYOFF_PRIOR_KIND": str(core.get("playoff_prior_kind", "")) if playoff_slate else "",
        "MARKET_GUARDRAIL_MODE": str(game_context.get("MARKET_GUARDRAIL_MODE", "")) if game_context else "",
        "SIM_TEAM_MIN_RAW_MEAN": round(float((sim_bundle or {}).get("raw_team_minutes_mean", np.nan)), 2) if sim_bundle else np.nan,
        "SIM_TEAM_MIN_RECONCILED_MEAN": round(float((sim_bundle or {}).get("reconciled_team_minutes_mean", np.nan)), 2) if sim_bundle else np.nan,
        "AVG_MIN_LAST_5": round(float(avg_min_5), 2),
        "AVG_MIN_LAST_10": round(float(rolling_mean(recent10, "MIN", 10)), 2),
        "MIN_PROJ": round(min_summary["MEAN"], 2),
        "PRED_MIN": round(min_summary["MEAN"], 2),
        "ACTIVE_MIN_PROJ": round(active_min_summary["MEAN"], 2),
        "SIM_MIN_P10": round(min_summary["P10"], 2),
        "SIM_MIN_P50": round(min_summary["P50"], 2),
        "SIM_MIN_P90": round(min_summary["P90"], 2),
        "SIM_MIN_STD": round(min_summary["STD"], 2),
    }

    for stat in STAT_TARGETS:
        summary = stat_summaries[stat]
        row[f"{stat}_PROJ"] = round(summary["MEAN"], 2)
        row[f"PRED_{stat}"] = round(summary["MEAN"], 2)
        if stat in {"PTS", "REB", "AST", "FG3M"}:
            active_summary = summarize_active_distribution(stat_draws[stat], active_mask)
            row[f"ACTIVE_{stat}_PROJ"] = round(active_summary["MEAN"], 2)
        row[f"SIM_{stat}_P10"] = round(summary["P10"], 2)
        row[f"SIM_{stat}_P50"] = round(summary["P50"], 2)
        row[f"SIM_{stat}_P90"] = round(summary["P90"], 2)
        row[f"SIM_{stat}_STD"] = round(summary["STD"], 2)

    for stat in ["PTS", "REB", "AST"]:
        debug = team_balance_debug[stat]
        row[f"{stat}_PRE_TEAM_BALANCE"] = round(float(debug["PRE"]), 2)
        row[f"{stat}_POST_TEAM_BALANCE"] = round(float(debug["POST"]), 2)
        row[f"{stat}_TEAM_ALLOCATED"] = round(float(debug["ALLOCATED"]), 2) if not np.isnan(debug["ALLOCATED"]) else np.nan
        row[f"{stat}_TEAM_BALANCE_MODE"] = debug["MODE"]

    row["TOV_PROJ"] = round(tov_summary["MEAN"], 2)
    row["PRED_TOV"] = round(tov_summary["MEAN"], 2)
    row["SIM_TOV_P10"] = round(tov_summary["P10"], 2)
    row["SIM_TOV_P50"] = round(tov_summary["P50"], 2)
    row["SIM_TOV_P90"] = round(tov_summary["P90"], 2)
    row["SIM_TOV_STD"] = round(tov_summary["STD"], 2)

    for stat, draws in supplemental_draws.items():
        summary = summarize_distribution(draws)
        row[f"{stat}_PROJ"] = round(summary["MEAN"], 4 if stat in {"DD", "TD"} else 2)
        row[f"PRED_{stat}"] = round(summary["MEAN"], 4 if stat in {"DD", "TD"} else 2)
        row[f"SIM_{stat}_P10"] = round(summary["P10"], 4 if stat in {"DD", "TD"} else 2)
        row[f"SIM_{stat}_P50"] = round(summary["P50"], 4 if stat in {"DD", "TD"} else 2)
        row[f"SIM_{stat}_P90"] = round(summary["P90"], 4 if stat in {"DD", "TD"} else 2)
        row[f"SIM_{stat}_STD"] = round(summary["STD"], 4 if stat in {"DD", "TD"} else 2)

    for combo, parts in COMBO_TARGETS.items():
        combo_draws = np.zeros(SIMULATION_RUNS)
        for part in parts:
            combo_draws += stat_draws[part]
        combo_summary = summarize_distribution(combo_draws)
        row[f"{combo}_PROJ"] = round(combo_summary["MEAN"], 2)
        row[f"SIM_{combo}_P10"] = round(combo_summary["P10"], 2)
        row[f"SIM_{combo}_P50"] = round(combo_summary["P50"], 2)
        row[f"SIM_{combo}_P90"] = round(combo_summary["P90"], 2)
        row[f"SIM_{combo}_STD"] = round(combo_summary["STD"], 2)

    return row, None


def build_player_projection(
    player_row,
    logs_df,
    opponent_defense,
    league_defaults,
    injury_map,
    matchups,
    models,
    lineup_injury_context,
    archetypes,
    team_pace,
    league_pace,
    game_sim_contexts,
    playoff_slate=False,
):
    core, err = build_player_projection_core(
        player_row,
        logs_df,
        opponent_defense,
        league_defaults,
        injury_map,
        matchups,
        models,
        lineup_injury_context,
        archetypes,
        team_pace,
        league_pace,
        game_sim_contexts,
        playoff_slate=playoff_slate,
    )
    if core is None:
        return None, err
    return finalize_player_projection_from_core(core)


def build_projections():
    lines_df = load_lines_df()
    # Rebuild the core identity columns defensively so small upstream schema
    # shifts do not break the full projection run on game day.
    if "PLAYER_NAME" not in lines_df.columns:
        player_col = find_player_col(lines_df)
        lines_df["PLAYER_NAME"] = lines_df[player_col].astype(str).str.strip()
    if "PLAYER_KEY" not in lines_df.columns:
        lines_df["PLAYER_KEY"] = lines_df["PLAYER_NAME"].map(clean_name)
    if "TEAM" not in lines_df.columns:
        team_col = None
        for candidate in ["TEAM_ABBREVIATION", "TEAM_ABBR", "PLAYER_TEAM", "TEAM_NAME"]:
            if candidate in lines_df.columns:
                team_col = candidate
                break
        lines_df["TEAM"] = (
            lines_df[team_col].astype(str).str.strip().str.upper()
            if team_col
            else ""
        )
    else:
        lines_df["TEAM"] = lines_df["TEAM"].astype(str).str.strip().str.upper()

    lines_df["PLAYER_NAME"] = lines_df["PLAYER_NAME"].astype(str).str.strip()
    lines_df["PLAYER_KEY"] = lines_df["PLAYER_KEY"].astype(str).str.strip()

    # Authoritative slate: teams_today (no min-team skip). Legacy path only if file empty.
    slate_baseline = load_authoritative_slate_teams_enforcement()
    slate_teams = load_today_slate_teams()
    slate_effective = slate_baseline if len(slate_baseline) else slate_teams
    if len(slate_baseline):
        print(
            f"Authoritative teams_today slate (used for line + log filters, final output gate): {sorted(slate_baseline)}"
        )
    if slate_effective and "TEAM" in lines_df.columns:
        line_teams = lines_df["TEAM"].astype(str).str.strip().str.upper()
        off_slate_count = int((~line_teams.isin(slate_effective)).sum())
        if off_slate_count:
            print(
                f"Filtering out {off_slate_count} off-slate line row(s) (line TEAM not in today's slate; props lines are not identity)."
            )
        filtered_lines = lines_df[line_teams.isin(slate_effective)].copy()
        if filtered_lines.empty and not lines_df.empty:
            print("WARNING: Slate-team filter removed every line row. Falling back to unfiltered lines for this run.")
        else:
            lines_df = filtered_lines
    injury_map = load_injuries()
    matchups = load_matchups()
    market_game_lines = load_market_game_lines(matchups)
    playoff_slate = playoff_slate_active(matchups)
    logs_df, opponent_defense, league_defaults, team_pace, league_pace, team_strength, league_game_total = load_historical_games()
    models = load_models()
    rotation_templates = load_rotation_templates(logs_df)
    archetypes = build_player_archetypes(logs_df, rotation_templates=rotation_templates, matchups=matchups)
    lineup_injury_context = build_lineup_injury_context(logs_df, injury_map, archetypes)
    game_sim_contexts = build_game_sim_contexts(
        matchups,
        team_strength,
        lineup_injury_context,
        team_pace,
        league_pace,
        league_game_total,
        market_game_lines,
        playoff_slate=playoff_slate,
    )

    single_player_df = lines_df[~lines_df["PLAYER_NAME"].apply(is_combo_player_name)].copy()
    single_player_df = single_player_df.assign(
        PLAYER_NAME=single_player_df.get("PLAYER_NAME", pd.Series(dtype="object")).astype(str).str.strip(),
        PLAYER_KEY=single_player_df.get("PLAYER_KEY", pd.Series(dtype="object")).astype(str).str.strip(),
        TEAM=single_player_df.get("TEAM", pd.Series(dtype="object")).astype(str).str.strip().str.upper(),
    )
    single_player_df = single_player_df[
        single_player_df["PLAYER_NAME"].ne("")
        & single_player_df["PLAYER_KEY"].ne("")
    ].copy()

    line_universe = single_player_df.reindex(columns=["PLAYER_NAME", "PLAYER_KEY", "TEAM"]).copy()
    latest_player_rows = (
        logs_df.drop_duplicates(subset=["PLAYER_KEY"], keep="first")[["PLAYER_NAME", "PLAYER_KEY", "TEAM_ABBREVIATION"]]
        .rename(columns={"TEAM_ABBREVIATION": "TEAM"})
        .copy()
    )
    latest_player_rows["PLAYER_NAME"] = latest_player_rows["PLAYER_NAME"].astype(str).str.strip()
    latest_player_rows["PLAYER_KEY"] = latest_player_rows["PLAYER_KEY"].astype(str).str.strip()
    latest_player_rows["TEAM"] = latest_player_rows["TEAM"].astype(str).str.strip().str.upper()
    if slate_effective:
        latest_player_rows = latest_player_rows[latest_player_rows["TEAM"].isin(slate_effective)].copy()
        team_latest_dates = (
            logs_df[logs_df["TEAM_ABBREVIATION"].isin(slate_effective)]
            .groupby("TEAM_ABBREVIATION")["GAME_DATE"]
            .max()
            .to_dict()
        )
        latest_game_logs = logs_df.copy()
        latest_game_logs["_TEAM_LATEST_DATE"] = latest_game_logs["TEAM_ABBREVIATION"].map(team_latest_dates)
        latest_game_logs = latest_game_logs[
            latest_game_logs["GAME_DATE"].notna()
            & latest_game_logs["_TEAM_LATEST_DATE"].notna()
            & (latest_game_logs["GAME_DATE"] == latest_game_logs["_TEAM_LATEST_DATE"])
        ].copy()
        latest_game_player_keys = set(latest_game_logs["PLAYER_KEY"].dropna().astype(str).str.strip().tolist())
        if latest_game_player_keys:
            latest_player_rows = latest_player_rows[latest_player_rows["PLAYER_KEY"].isin(latest_game_player_keys)].copy()

    # Roster truth: game logs (latest game per player) must override lines_today.csv TEAM.
    # Props feeds often carry stale or mis-joined book team labels; line-first merge poisoned
    # matchups, injury context, game script, and playoff minute closure by team.
    unique_players = (
        pd.concat([latest_player_rows, line_universe], ignore_index=True)
        .dropna(subset=["PLAYER_NAME", "PLAYER_KEY"])
        .drop_duplicates(subset=["PLAYER_KEY"], keep="first")
        .reset_index(drop=True)
    )

    if playoff_slate:
        teams_for_expansion = slate_effective if slate_effective else {str(t).strip().upper() for t in matchups.keys() if t}
        exist_keys = set(unique_players["PLAYER_KEY"].dropna().astype(str).str.strip().tolist())
        expansion = build_playoff_rotation_expansion_rows(logs_df, injury_map, teams_for_expansion, archetypes, exist_keys)
        if not expansion.empty:
            unique_players = (
                pd.concat([unique_players, expansion], ignore_index=True)
                .dropna(subset=["PLAYER_NAME", "PLAYER_KEY"])
                .drop_duplicates(subset=["PLAYER_KEY"], keep="first")
                .reset_index(drop=True)
            )
            print(
                f"Playoff rotation universe expansion: added {len(expansion)} candidate player(s); "
                f"deduped universe size {len(unique_players)}."
            )

    # Hard gate: only players whose current log team is on teams_today; never trust line TEAM.
    enforcement_slate = slate_baseline if len(slate_baseline) else slate_effective
    slate_meta = {}
    if enforcement_slate:
        unique_players, slate_meta = apply_final_slate_universe_enforcement(
            unique_players, logs_df, enforcement_slate, line_universe
        )
        log_final_slate_enforcement_report(slate_meta, enforcement_slate)
    else:
        print("WARNING: No authoritative teams_today slate; skipping final log-team + slate hard filter (legacy run).")

    if playoff_slate:
        before_realism_filter = len(unique_players)
        unique_players = filter_playoff_projection_universe(unique_players, logs_df, archetypes, line_universe, matchups)
        if len(unique_players) != before_realism_filter:
            print(
                f"Playoff production universe tightened: {before_realism_filter} -> {len(unique_players)} player(s)."
            )

    print(f"Projection date: {current_projection_date()}")
    print(f"Total rows in lines_today.csv: {len(lines_df)}")
    print(f"Single-player rows used for projections: {len(single_player_df)}")
    print(f"Players with lines loaded: {len(line_universe.drop_duplicates(subset=['PLAYER_KEY']))}")
    print(f"Players in full projection universe: {len(unique_players)}")
    print(f"Injury entries loaded: {len(injury_map)}")
    print(f"Market game lines loaded: {len(market_game_lines)}")
    print(f"Rotation templates loaded: {len(rotation_templates)}")
    print(f"Loaded trained models: {sorted(models.keys())}")
    print(f"Playoff slate mode: {'ON' if playoff_slate else 'OFF'}")

    rows = []
    skipped_combo = sorted(
        name for name in lines_df["PLAYER_NAME"].dropna().astype(str).unique().tolist()
        if is_combo_player_name(name)
    )
    failed_players = []

    if playoff_slate:
        playoff_cores = []
        for _, player_row in unique_players.iterrows():
            core, fail_reason = build_player_projection_core(
                player_row,
                logs_df,
                opponent_defense,
                league_defaults,
                injury_map,
                matchups,
                models,
                lineup_injury_context,
                archetypes,
                team_pace,
                league_pace,
                game_sim_contexts,
                playoff_slate=True,
            )
            if core is None:
                failed_players.append(f"{player_row['PLAYER_NAME']} ({fail_reason})")
                continue
            playoff_cores.append(core)
        snapshot_playoff_pre_closure_diagnostics(playoff_cores)
        apply_playoff_team_minute_closure_to_cores(playoff_cores)
        apply_playoff_team_simulated_minute_reconciliation_to_cores(playoff_cores)
        verify_playoff_closure_team_totals(playoff_cores)
        verify_playoff_production_guardrails(playoff_cores)
        print_playoff_regression_audit_and_cleanup(playoff_cores)
        for core in playoff_cores:
            projection_row, _ = finalize_player_projection_from_core(core)
            rows.append(projection_row)
    else:
        for _, player_row in unique_players.iterrows():
            projection_row, fail_reason = build_player_projection(
                player_row,
                logs_df,
                opponent_defense,
                league_defaults,
                injury_map,
                matchups,
                models,
                lineup_injury_context,
                archetypes,
                team_pace,
                league_pace,
                game_sim_contexts,
                playoff_slate=False,
            )
            if projection_row is None:
                failed_players.append(f"{player_row['PLAYER_NAME']} ({fail_reason})")
                continue
            rows.append(projection_row)

    projections = pd.DataFrame(rows)
    if projections.empty:
        raise ValueError("No projections were created")

    p_before = len(projections)
    if enforcement_slate:
        projections, n_proj_dropped = filter_projections_dataframe_to_slate_enforcement(
            projections, enforcement_slate, label="projections"
        )
        if projections.empty:
            raise ValueError(
                "No projections remain after final slate enforcement on output frame; check raw_games and teams_today."
            )
        if n_proj_dropped or p_before != len(projections):
            print(
                f"Final output frame slate check: {p_before} -> {len(projections)} row(s) "
                f"(TEAM_ABBREVIATION must be in {sorted(enforcement_slate)}; dropped {n_proj_dropped} row(s) not on slate)."
            )

    line_player_keys = set(line_universe["PLAYER_KEY"].dropna().astype(str).str.strip().tolist())
    projections["HAS_PROP_LINE"] = projections["PLAYER_KEY"].astype(str).str.strip().isin(line_player_keys)
    projections = mark_published_rotation_pool(projections)

    projections = projections.sort_values(
        by=["PTS_PROJ", "PRA_PROJ", "MIN_PROJ"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    projections.to_csv(PROJECTIONS_PATH, index=False)
    app_view = build_projection_app_view(projections.copy())
    app_view.to_csv(PROJECTIONS_APP_VIEW_PATH, index=False)

    print(f"\nSaved projections: {PROJECTIONS_PATH}")
    print(f"Saved projections app view: {PROJECTIONS_APP_VIEW_PATH}")
    print(f"Rows saved: {len(projections)}")

    if skipped_combo:
        print(f"\nSkipped combo props from player lookup: {len(skipped_combo)}")
        for name in skipped_combo[:25]:
            print(f"- {name}")

    if failed_players:
        print(f"\nPlayers skipped due to missing/insufficient history: {len(failed_players)}")
        for name in failed_players[:25]:
            print(f"- {name}")

    print("\nTop 20 simulated scorers:")
    print(
        projections[
            [
                "PLAYER_NAME",
                "TEAM_ABBREVIATION",
                "OPPONENT",
                "PTS_PROJ",
                "SIM_PTS_P10",
                "SIM_PTS_P90",
                "ACTIVE_PROB",
                "INJURY_STATUS",
            ]
        ]
        .head(20)
        .to_string(index=False)
    )


def main():
    build_projections()
    print("\npredict_today.py finished successfully")


if __name__ == "__main__":
    main()
