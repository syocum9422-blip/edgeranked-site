import csv
import json
from nba_model.webapp.mlb_weather_view import register_mlb_weather_routes
import logging
import os
import urllib.request
from datetime import date, datetime, timedelta
from html import escape
from math import erf, isnan, sqrt
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from flask import Flask, Response, jsonify, request, send_from_directory
from nba_model.webapp.auth_views import register_auth_routes

from nba_model.common import build_projection_app_view
from nba_model.settings import (
    BEST_BETS_OUTPUT_PATH,
    CALIBRATION_SUMMARY_PATH,
    HISTORY_PATH,
    INJURY_CSV_PATH,
    LINES_PATH,
    MATCH_AUDIT_PATH,
    PROJECTIONS_APP_VIEW_PATH,
    PROJECTIONS_PATH,
    RECORD_SUMMARY_PATH,
    RESULTS_PAGE_PATH,
    TEAMS_TODAY_PATH,
)
from nba_model.webapp.wnba_views import register_wnba_routes


ET = ZoneInfo("America/New_York")
MODEL_VERSION = "v2.1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPORTS_ROOT = PROJECT_ROOT.parent / "sports"
DEFAULT_UFC_BASE = PROJECT_ROOT / "data" / "ufc"
LOGGER = logging.getLogger(__name__)
MLB_SCHEDULE_CACHE = {"date": None, "fetched_at": None, "active_matchups": None}
MLB_INACTIVE_GAME_STATES = {
    "final",
    "game over",
    "completed early",
    "postponed",
    "cancelled",
    "canceled",
}


def _resolve_first_existing_dir(candidates):
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    return candidates[0]


def _resolve_first_existing_path(candidates):
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    return candidates[0] if candidates else Path()


def _unique_paths(candidates):
    unique = []
    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _mlb_base_candidates():
    mlb_base_env = os.environ.get("EDGERANKED_MLB_BASE_DIR")
    candidates = []
    if mlb_base_env:
        candidates.append(Path(mlb_base_env))
    candidates.extend(
        [
            SPORTS_ROOT / "mlb" / "mlb_model",
            PROJECT_ROOT / "mlb_model",
            PROJECT_ROOT,
        ]
    )
    return _unique_paths(candidates)


def _mlb_mode_env(name, default="legacy"):
    value = str(os.environ.get(name, default)).strip().lower()
    return value if value in {"legacy", "canonical"} else default


mlb_base_candidates = _mlb_base_candidates()
MLB_OUTPUT_DIR = _resolve_first_existing_dir([base / "mlb" / "outputs" for base in mlb_base_candidates])
MLB_DATA_DIR = _resolve_first_existing_dir([base / "data" / "mlb" for base in mlb_base_candidates])
MLB_LINEUPS_FILE = _resolve_first_existing_path([base / "lineups_with_ids.csv" for base in mlb_base_candidates])
MLB_CANONICAL_OUTPUT_DIR = _resolve_first_existing_dir([base / "outputs" / "canonical" for base in mlb_base_candidates])
MLB_SITE_OUTPUT_DIR = _resolve_first_existing_dir([base / "outputs" / "site" for base in mlb_base_candidates])
MLB_NORMALIZED_DATA_DIR = _resolve_first_existing_dir([base / "data" / "normalized" for base in mlb_base_candidates])
MLB_READER_MODE = _mlb_mode_env("MLB_READER_MODE", "legacy")

ufc_base_env = os.environ.get("EDGERANKED_UFC_BASE_DIR")
ufc_base_candidates = [Path(ufc_base_env)] if ufc_base_env else []
ufc_base_candidates.append(DEFAULT_UFC_BASE)
UFC_BASE_DIR = _resolve_first_existing_dir(ufc_base_candidates)
UFC_WEBSITE_DIR = UFC_BASE_DIR / "website"

pga_base_env = os.environ.get("EDGERANKED_PGA_BASE_DIR")
PGA_BASE_DIR = _resolve_first_existing_dir(
    _unique_paths(
        [
            Path(pga_base_env).expanduser() if pga_base_env else None,
            SPORTS_ROOT / "pga",
            PROJECT_ROOT / "pga",
        ]
    )
).resolve()
PGA_OUTPUT_DIR = PGA_BASE_DIR / "outputs"
PGA_DATA_DIR = PGA_BASE_DIR / "data"
PGA_CONFIG_PATH = PGA_BASE_DIR / "config" / "config.json"
PGA_TOURNAMENT_METADATA_PATH = PGA_DATA_DIR / "processed" / "current_tournament.json"
PGA_PROCESSED_ODDS_DIR = PGA_DATA_DIR / "processed" / "odds"
PGA_PUBLISHED_DIR = PGA_DATA_DIR / "published" / "pga"
PGA_PUBLISHED_BEST_BETS_PATH = PGA_PUBLISHED_DIR / "best_bets.json"
PGA_PUBLISH_STATE_PATH = PGA_PUBLISHED_DIR / "publish_state.json"
PGA_RESULTS_PATH = PGA_PUBLISHED_DIR / "pga_simulation_results.csv"
PGA_INVALID_PROP_TYPES = {"", "holes_played", "null", "nan", "none"}


BRAND_ASSETS_DIR = PROJECT_ROOT / "assets" / "brand"
BRAND_LOGO_FILE = "edgeranked_logo.png"
SUPPORT_EMAIL = "support@edgerankedai.com"
WAITLIST_CONTACT_EMAIL = "info@edgerankedai.com"
WAITLIST_DATA_PATH = PROJECT_ROOT / "data" / "waitlist.csv"

MLB_FILES = {
    "best_bets": MLB_OUTPUT_DIR / "betting_sheet_today.csv",
    "pitchers": MLB_OUTPUT_DIR / "pitcher_props_today.csv",
    "pitcher_predictions": MLB_OUTPUT_DIR / "mlb_pitcher_projections_today.csv",
    "hitters": MLB_OUTPUT_DIR / "hitter_summary_today.csv",
    "hitters_full": MLB_CANONICAL_OUTPUT_DIR / "hitter_predictions_full.csv",
    "hitters_site": MLB_SITE_OUTPUT_DIR / "hitter_summary_today.csv",
    "fantasy": MLB_OUTPUT_DIR / "fantasy_projections_today.csv",
    "history": MLB_OUTPUT_DIR / "bet_history.csv",
    "record": MLB_OUTPUT_DIR / "daily_betting_summary.csv",
    "hitter_tracking": MLB_OUTPUT_DIR / "hitter_tracking.csv",
    "pitcher_tracking": MLB_OUTPUT_DIR / "pitcher_tracking.csv",
    "lines": MLB_DATA_DIR / "lines_today.csv",
    "normalized_lines": MLB_NORMALIZED_DATA_DIR / "lines_today.csv",
    "validation_manifest": MLB_SITE_OUTPUT_DIR / "validation_manifest.json",
}
MLB_REALISM_FIELD_DISPLAY = [
    ("blended_hr_prob_v2", "Blend HR %"),
    ("blended_hit_2plus_prob_v2", "Blend 2+ Hit %"),
    ("blended_tb2_prob_v2", "Blend 2+ Bases %"),
    ("sim_hr_prob_shadow_v2", "Shadow HR %"),
    ("sim_hit_2plus_shadow_v2", "Shadow 2+ Hit %"),
    ("sim_tb2_shadow_v2", "Shadow 2+ Bases %"),
]
MLB_REALISM_STAT_FIELDS = {
    "Home Runs": ("blended_hr_prob_v2", "sim_hr_prob_shadow_v2", "hr_prob"),
    "2+ Hits": ("blended_hit_2plus_prob_v2", "sim_hit_2plus_shadow_v2", None),
    "2+ Bases": ("blended_tb2_prob_v2", "sim_tb2_shadow_v2", "tb2_prob"),
}

NBA_PAGE_SPECS = {
    "best_bets": {"title": "NBA Top Plays", "path": Path(BEST_BETS_OUTPUT_PATH), "route": "/nba/best-bets", "api_route": "/api/nba/best-bets", "description": "A supporting top-plays layer built from the strongest model-approved opportunities on the current slate."},
    "projections": {"title": "NBA Projection Explorer", "path": Path(PROJECTIONS_PATH), "route": "/nba/projections", "api_route": "/api/nba/projections", "description": "Full-slate player projections with workload, distribution, matchup, and confidence context."},
    "history": {"title": "Bet History", "path": Path(HISTORY_PATH), "route": "/nba/history", "api_route": "/api/nba/history", "description": "Your latest graded NBA card."},
    "graded": {"title": "Latest Graded Bets", "path": Path(HISTORY_PATH), "route": "/nba/graded", "api_route": "/api/nba/graded", "description": "Rows already graded in the most recent NBA history export."},
    "record": {"title": "Verified Results", "path": Path(RECORD_SUMMARY_PATH), "route": "/nba/record", "api_route": "/api/nba/record", "description": "Tracked record, recent hit rate, and verified results from published NBA outputs."},
    "injuries": {"title": "Injuries", "path": Path(INJURY_CSV_PATH), "route": "/nba/injuries", "api_route": "/api/nba/injuries", "description": "Current injury and availability inputs."},
    "system": {"title": "System Status", "path": Path(RESULTS_PAGE_PATH), "route": "/nba/system", "api_route": "/api/nba/system", "description": "Quick status view of NBA backing files."},
}

UFC_PAGE_SPECS = {
    "fights": {"title": "Fight Forecasts", "path": UFC_WEBSITE_DIR / "ufc_site_payload.json", "route": "/ufc/fights", "api_route": "/api/ufc/fights", "description": "Clean fight-by-fight simulation percentages."},
    "props": {"title": "Prop Probabilities", "path": UFC_BASE_DIR / "ufc_prop_probabilities.csv", "route": "/ufc/props", "api_route": "/api/ufc/props", "description": "Readable UFC prop probabilities."},
    "backtest": {"title": "Backtest Summary", "path": UFC_BASE_DIR / "ufc_backtest_summary.csv", "route": "/ufc/backtest", "api_route": "/api/ufc/backtest", "description": "Current UFC summary metrics."},
    "system": {"title": "System Status", "path": UFC_BASE_DIR, "route": "/ufc/system", "api_route": "/api/ufc/system", "description": "Quick status view of UFC backing files."},
}

MLB_PAGE_SPECS = {
    "best_bets": {"title": "MLB Best Bets", "route": "/mlb/best-bets", "api_route": "/api/mlb/best-bets", "description": "Top Plays Today with the strongest current model edge.", "kind": "mlb_best_bets"},
    "pitcher_strikeouts": {"title": "Pitcher Projections", "route": "/mlb/pitcher-strikeouts", "api_route": "/api/mlb/pitcher-strikeouts", "description": "Projection-first pitcher rows with strikeout and workload context.", "kind": "mlb_pitchers"},
    "hitter_full": {"title": "Full Hitter Board", "route": "/mlb/hitter-board", "api_route": "/api/mlb/hitter-board", "description": "Full slate hitter board with every available projection category.", "kind": "mlb_hitter_full"},
    "projections": {"title": "Hitter Projections", "route": "/mlb/projections", "api_route": "/api/mlb/projections", "description": "Slate-wide hitter projection board with model projections, lines, and edges.", "kind": "mlb_hitters"},
    "two_plus_hits": {"title": "2+ Hit Targets", "route": "/mlb/two-plus-hits", "api_route": "/api/mlb/two-plus-hits", "description": "Shadow hitter realism 2+ hit leaderboard when blended fields are available.", "kind": "mlb_hit2plus"},
    "two_plus_bases": {"title": "2+ Bases Targets", "route": "/mlb/two-plus-bases", "api_route": "/api/mlb/two-plus-bases", "description": "Current 2+ bases targets sorted by probability.", "kind": "mlb_tb2"},
    "rbi_targets": {"title": "RBI Targets", "route": "/mlb/rbi-targets", "api_route": "/api/mlb/rbi-targets", "description": "Current RBI targets sorted by probability.", "kind": "mlb_rbi"},
    "hitter_strikeouts": {"title": "Hitter Strikeouts", "route": "/mlb/hitter-strikeouts", "api_route": "/api/mlb/hitter-strikeouts", "description": "Hitters most likely to strike out today.", "kind": "mlb_hitter_k"},
    "stolen_bases": {"title": "Stolen Base Targets", "route": "/mlb/stolen-bases", "api_route": "/api/mlb/stolen-bases", "description": "Current stolen-base targets sorted by probability.", "kind": "mlb_sb"},
    "hr_targets": {"title": "Home Run Targets", "route": "/mlb/hr-targets", "api_route": "/api/mlb/hr-targets", "description": "Hitters with the highest home-run probability on the slate.", "kind": "mlb_hr"},
    "history": {"title": "MLB History", "route": "/mlb/history", "api_route": "/api/mlb/history", "description": "Most recent available completed board from MLB history.", "kind": "mlb_history"},
    "graded": {"title": "Graded Results", "route": "/mlb/graded", "api_route": "/api/mlb/graded", "description": "Latest graded MLB results with outcome-level accountability.", "kind": "mlb_graded"},
    "record": {"title": "Performance Record", "route": "/mlb/record", "api_route": "/api/mlb/record", "description": "Overall performance, recent windows, and daily market breakdowns.", "kind": "mlb_record"},
    "lines": {"title": "Current Lines", "route": "/mlb/lines", "api_route": "/api/mlb/lines", "description": "Current MLB lines being evaluated by the model.", "kind": "mlb_lines"},
    "injuries": {"title": "Tracking Files", "route": "/mlb/injuries", "api_route": "/api/mlb/injuries", "description": "Latest hitter and pitcher tracking exports.", "kind": "mlb_tracking"},
    "system": {"title": "System Status", "route": "/mlb/system", "api_route": "/api/mlb/system", "description": "Status of MLB data files backing the site.", "kind": "mlb_system"},
}

ROOT_NAV_ITEMS = [
    ("Home", "/"),
    ("NBA", "/nba"),
    ("MLB", "/mlb"),
    ("WNBA", "/wnba"),
    ("PGA", "/pga"),
    ("UFC", "/ufc"),
    ("Pricing", "/pricing"),
    ("About", "/about"),
]
NBA_NAV_ITEMS = [("Overview", "/nba"), ("Projections", "/nba/projections"), ("Top Plays", "/nba/best-bets"), ("History", "/nba/history")]
UFC_NAV_ITEMS = [("Overview", "/ufc"), ("Fight Card", "/ufc/fights"), ("Props", "/ufc/props")]
PGA_NAV_ITEMS = [("Overview", "/pga"), ("Best Bets", "/pga/best-bets"), ("Leaderboard", "/pga/leaderboard")]
MLB_PRIMARY_NAV = [("Overview", "/mlb"), ("Top Plays", "/mlb/best-bets"), ("Pitchers", "/mlb/pitcher-strikeouts"), ("Hitters", "/mlb/projections"), ("Weather", "/mlb/weather")]
MLB_HITTER_NAV = [
    ("Full Board", "/mlb/hitter-board"),
    ("Hit Targets", "/mlb/projections"),
    ("2+ Hits", "/mlb/two-plus-hits"),
    ("2+ Bases", "/mlb/two-plus-bases"),
    ("RBI Targets", "/mlb/rbi-targets"),
    ("Home Runs", "/mlb/hr-targets"),
    ("Stolen Bases", "/mlb/stolen-bases"),
    ("Hitter Ks", "/mlb/hitter-strikeouts"),
]
MLB_HITTER_ROUTES = {href for _, href in MLB_HITTER_NAV}
MLB_HITTER_CATEGORY_STATS = {
    "mlb_hitters": "Hits",
    "mlb_hit2plus": "2+ Hits",
    "mlb_tb2": "2+ Bases",
    "mlb_rbi": "RBI",
    "mlb_hitter_k": "Hitter Strikeouts",
    "mlb_sb": "Stolen Bases",
    "mlb_hr": "Home Runs",
}
MLB_HITTER_PAGE_STATS = {
    "projections": "Hits",
    "two_plus_hits": "2+ Hits",
    "two_plus_bases": "2+ Bases",
    "rbi_targets": "RBI",
    "hitter_strikeouts": "Hitter Strikeouts",
    "stolen_bases": "Stolen Bases",
    "hr_targets": "Home Runs",
}
MLB_HITTER_STAT_SORT_FIELDS = {
    "Hits": ("hit_prob", "MC_Mean_Hits"),
    "2+ Hits": ("MC_Hit2Plus_Prob", "MC_Mean_Hits"),
    "2+ Bases": ("tb2_prob", "MC_Mean_Total_Bases"),
    "RBI": ("rbi_prob", "MC_Mean_RBI"),
    "Home Runs": ("hr_prob", "historical_hr_game_rate"),
    "Stolen Bases": ("sb_prob", "MC_Mean_Stolen_Bases"),
    "Hitter Strikeouts": ("hitter_strikeout_pct", "projected_hitter_strikeouts"),
}
MLB_HITTER_TIEBREAKER_COLUMNS = {
    "Hits": ("MC_Mean_Hits",),
    "2+ Hits": ("MC_Mean_Hits",),
    "2+ Bases": ("MC_Mean_Total_Bases",),
    "RBI": ("MC_Mean_RBI",),
    "Home Runs": ("historical_hr_game_rate", "historical_power_ops", "barrel_rate"),
    "Stolen Bases": ("MC_Mean_Stolen_Bases",),
    "Hitter Strikeouts": ("projected_hitter_strikeouts",),
}

NBA_STAT_CONFIGS = [
    {"key": "PTS", "label": "Points", "projection": "PTS_PROJ", "median": "SIM_PTS_P50", "floor": "SIM_PTS_P10", "ceiling": "SIM_PTS_P90", "std": "SIM_PTS_STD", "thresholds": [10, 15, 20, 25, 30, 35, 40]},
    {"key": "REB", "label": "Rebounds", "projection": "REB_PROJ", "median": "SIM_REB_P50", "floor": "SIM_REB_P10", "ceiling": "SIM_REB_P90", "std": "SIM_REB_STD", "thresholds": [4, 6, 8, 10, 12, 14]},
    {"key": "AST", "label": "Assists", "projection": "AST_PROJ", "median": "SIM_AST_P50", "floor": "SIM_AST_P10", "ceiling": "SIM_AST_P90", "std": "SIM_AST_STD", "thresholds": [4, 6, 8, 10, 12, 14]},
    {"key": "3PM", "label": "3PM", "projection": "FG3M_PROJ", "median": "SIM_FG3M_P50", "floor": "SIM_FG3M_P10", "ceiling": "SIM_FG3M_P90", "std": "SIM_FG3M_STD", "thresholds": [1, 2, 3, 4, 5, 6]},
    {"key": "STL", "label": "Steals", "projection": "STL_PROJ", "median": "SIM_STL_P50", "floor": "SIM_STL_P10", "ceiling": "SIM_STL_P90", "std": "SIM_STL_STD", "thresholds": [1, 2, 3, 4]},
    {"key": "BLK", "label": "Blocks", "projection": "BLK_PROJ", "median": "SIM_BLK_P50", "floor": "SIM_BLK_P10", "ceiling": "SIM_BLK_P90", "std": "SIM_BLK_STD", "thresholds": [1, 2, 3, 4]},
    {"key": "TOV", "label": "Turnovers", "projection": "TOV_PROJ", "median": "SIM_TOV_P50", "floor": "SIM_TOV_P10", "ceiling": "SIM_TOV_P90", "std": "SIM_TOV_STD", "thresholds": [2, 3, 4, 5, 6]},
    {"key": "PRA", "label": "PRA", "projection": "PRA_PROJ", "median": "SIM_PRA_P50", "floor": "SIM_PRA_P10", "ceiling": "SIM_PRA_P90", "std": "SIM_PRA_STD", "thresholds": [20, 25, 30, 35, 40, 45, 50]},
    {"key": "PR", "label": "PR", "projection": "PR_PROJ", "median": "SIM_PR_P50", "floor": "SIM_PR_P10", "ceiling": "SIM_PR_P90", "std": "SIM_PR_STD", "thresholds": [15, 20, 25, 30, 35, 40]},
    {"key": "PA", "label": "PA", "projection": "PA_PROJ", "median": "SIM_PA_P50", "floor": "SIM_PA_P10", "ceiling": "SIM_PA_P90", "std": "SIM_PA_STD", "thresholds": [15, 20, 25, 30, 35, 40]},
    {"key": "RA", "label": "RA", "projection": "RA_PROJ", "median": "SIM_RA_P50", "floor": "SIM_RA_P10", "ceiling": "SIM_RA_P90", "std": "SIM_RA_STD", "thresholds": [10, 15, 20, 25, 30]},
    {"key": "SB", "label": "Steals + Blocks", "projection": "SB_PROJ", "median": "SIM_SB_P50", "floor": "SIM_SB_P10", "ceiling": "SIM_SB_P90", "std": "SIM_SB_STD", "thresholds": [1, 2, 3, 4, 5]},
    {"key": "FANTASY", "label": "Fantasy Points", "projection": "FANTASY_PROJ", "median": "SIM_FANTASY_P50", "floor": "SIM_FANTASY_P10", "ceiling": "SIM_FANTASY_P90", "std": "SIM_FANTASY_STD", "thresholds": [20, 25, 30, 35, 40, 45, 50, 55]},
    {"key": "MIN", "label": "Minutes", "projection": "MIN_PROJ", "median": "SIM_MIN_P50", "floor": "SIM_MIN_P10", "ceiling": "SIM_MIN_P90", "std": "SIM_MIN_STD", "thresholds": [20, 24, 28, 32, 36, 40]},
]

NBA_HOME_SNAPSHOT_STATS = ["PTS", "REB", "AST", "3PM", "BLK", "SB", "PRA", "FANTASY", "MIN"]

NBA_LINE_STAT_MAP = {
    "POINTS": "PTS",
    "REBOUNDS": "REB",
    "ASSISTS": "AST",
    "STEALS": "STL",
    "BLOCKED SHOTS": "BLK",
    "3-PT MADE": "3PM",
    "TURNOVERS": "TOV",
    "PTS+REBS+ASTS": "PRA",
    "PTS+REBS": "PR",
    "PTS+ASTS": "PA",
    "REBS+ASTS": "RA",
    "BLKS+STLS": "SB",
    "FANTASY SCORE": "FANTASY",
    "MINUTES": "MIN",
}


def read_csv_df(path):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def records_from_df(df):
    if df is None or df.empty:
        return []
    return df.where(pd.notna(df), None).to_dict(orient="records")


def read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def json_ready(value):
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [json_ready(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None:
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def ensure_waitlist_storage():
    WAITLIST_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    if WAITLIST_DATA_PATH.exists():
        return
    with open(WAITLIST_DATA_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "name", "email", "message", "source_page"])
        writer.writeheader()


def save_waitlist_submission(name, email, message="", source_page="/waitlist"):
    ensure_waitlist_storage()

    normalized_email = normalize_text(email).lower()
    existing_emails = set()
    try:
        with open(WAITLIST_DATA_PATH, "r", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                existing = normalize_text(row.get("email")).lower()
                if existing:
                    existing_emails.add(existing)
    except Exception:
        existing_emails = set()

    if normalized_email in existing_emails:
        return "duplicate"

    with open(WAITLIST_DATA_PATH, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "name", "email", "message", "source_page"])
        writer.writerow({
            "timestamp": now_et().isoformat(),
            "name": normalize_text(name),
            "email": normalized_email,
            "message": normalize_text(message),
            "source_page": normalize_text(source_page, "/waitlist"),
        })

    return "created"


def now_et():
    return datetime.now(ET)


def today_et():
    return now_et().date()


def mlb_matchup_key(team, opponent):
    team_name = normalize_text(team)
    opponent_name = normalize_text(opponent)
    if not team_name or not opponent_name:
        return None
    return frozenset({team_name, opponent_name})


def current_mlb_active_matchups():
    slate_date = today_et().isoformat()
    cached_at = MLB_SCHEDULE_CACHE.get("fetched_at")
    if (
        MLB_SCHEDULE_CACHE.get("date") == slate_date
        and cached_at
        and (now_et() - cached_at).total_seconds() < 120
    ):
        return MLB_SCHEDULE_CACHE.get("active_matchups")

    url = (
        "https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&date={slate_date}&hydrate=probablePitcher,team"
    )
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"WARNING: MLB schedule status fetch failed: {exc}")
        return MLB_SCHEDULE_CACHE.get("active_matchups")

    active = set()
    for date_payload in payload.get("dates", []):
        for game in date_payload.get("games", []):
            status = normalize_text(game.get("status", {}).get("detailedState")).lower()
            if status in MLB_INACTIVE_GAME_STATES:
                continue
            teams = game.get("teams", {})
            away = teams.get("away", {}).get("team", {}).get("name")
            home = teams.get("home", {}).get("team", {}).get("name")
            key = mlb_matchup_key(away, home)
            if key:
                active.add(key)

    MLB_SCHEDULE_CACHE.update({
        "date": slate_date,
        "fetched_at": now_et(),
        "active_matchups": active,
    })
    return active


def filter_mlb_frame_to_active_slate(df, team_col, opponent_col):
    if df.empty or not team_col or not opponent_col:
        return df
    active_matchups = current_mlb_active_matchups()
    if active_matchups is None:
        return df
    if not active_matchups:
        return df.iloc[0:0].copy()

    work = df.copy()
    keys = work.apply(lambda row: mlb_matchup_key(row.get(team_col), row.get(opponent_col)), axis=1)
    filtered = work[keys.isin(active_matchups)].copy()
    return filtered


def file_timestamp(path):
    path = Path(path)
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, ET)




def public_data_source_label(path):
    return Path(path).name or "data_source"


def public_data_source_labels(paths):
    return [public_data_source_label(path) for path in paths if Path(path).exists()]

def format_timestamp(ts):
    if not ts:
        return "n/a"
    return ts.astimezone(ET).strftime("%B %-d, %Y %-I:%M %p ET")


def parse_date(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return pd.to_datetime(value, errors="coerce").date()
    except Exception:
        return None


def latest_date_in_df(df, column="date"):
    if df.empty or column not in df.columns:
        return None
    parsed = pd.to_datetime(df[column], errors="coerce").dropna()
    if parsed.empty:
        return None
    return parsed.max().date()


def normalize_text(value, default=""):
    if value is None:
        return default
    text = str(value).strip()
    if text.lower() == "nan":
        return default
    return text


def safe_float(value, default=None):
    try:
        if value is None or str(value).strip() == "":
            return default
        number = float(value)
        if isnan(number):
            return default
        return number
    except Exception:
        return default


def safe_int(value, default=0):
    number = safe_float(value)
    if number is None:
        return default
    return int(round(number))


def pct_label(value, digits=1):
    number = safe_float(value)
    if number is None:
        return "n/a"
    if abs(number) <= 1:
        number *= 100
    return f"{number:.{digits}f}%"


def metric_label(value, digits=1):
    number = safe_float(value)
    if number is None:
        text = normalize_text(value)
        return text or "n/a"
    if digits == 0:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def props_scanned_count():
    df = read_csv_df(MLB_FILES["normalized_lines"])
    if df.empty:
        df = read_csv_df(MLB_FILES["lines"])
    if df.empty:
        return 0
    if "LEAGUE" in df.columns:
        df = df[df["LEAGUE"].astype(str).str.upper() == "MLB"].copy()
    df = df[df.apply(mlb_line_is_clean_display_row, axis=1)].copy()
    return len(df)


def pitcher_props_scanned_count():
    df = read_csv_df(MLB_FILES["normalized_lines"])
    if df.empty:
        df = read_csv_df(MLB_FILES["lines"])
    if df.empty:
        return 0
    work = df.copy()
    if "LEAGUE" in work.columns:
        work = work[work["LEAGUE"].astype(str).str.upper() == "MLB"].copy()
    work = work[work.apply(mlb_line_is_clean_display_row, axis=1)].copy()
    if "PLAYER_TYPE" in work.columns:
        work = work[work["PLAYER_TYPE"].astype(str).str.upper() == "PITCHER"].copy()
    return len(work)


def source_freshness_label(ts):
    if not ts:
        return "Awaiting source file"
    age = now_et() - ts
    minutes = max(int(age.total_seconds() // 60), 0)
    if minutes < 2:
        return "Updated moments ago"
    if minutes < 60:
        return f"Updated {minutes} minutes ago"
    hours = minutes // 60
    if hours < 24:
        return f"Updated {hours} hour{'s' if hours != 1 else ''} ago"
    return f"Updated {age.days} day{'s' if age.days != 1 else ''} ago"


def grade_result_label(value):
    text = normalize_text(value).upper()
    if text in {"WIN", "LOSS", "PUSH"}:
        return text.title()
    return ""


def confidence_level(value):
    text = normalize_text(value).lower()
    if "high" in text:
        return "High"
    if "medium" in text or "med" in text:
        return "Medium"
    if "low" in text:
        return "Low"
    score = safe_float(value)
    if score is None:
        return "Medium"
    if score >= 6:
        return "High"
    if score >= 4:
        return "Medium"
    return "Low"


def confidence_rank(value):
    mapping = {"high": 3, "medium": 2, "low": 1}
    return mapping.get(confidence_level(value).lower(), 0)


def find_first_column(df, names):
    for name in names:
        if name in df.columns:
            return name
    return None


def normalize_player_key(value):
    return " ".join(normalize_text(value).lower().split())


def normalize_profile_key(player, team=""):
    player_key = normalize_player_key(player)
    team_key = normalize_text(team).upper()
    return f"{player_key}|{team_key}" if team_key else player_key


def projection_display_label(column_name):
    label = normalize_text(column_name)
    label = label.replace("SIM_", "").replace("PRED_", "")
    label = label.replace("_PROJ", "").replace("_PROJECTION", "")
    label = label.replace("_PROB", " Probability").replace("_PCT", " %")
    label = label.replace("_P10", " P10").replace("_P50", " P50").replace("_P90", " P90")
    label = label.replace("_STD", " Std").replace("_", " ")
    return label.title().replace("Fg3M", "3PM").replace("Pts", "Points").replace("Reb", "Rebounds").replace("Ast", "Assists")


def profile_value_payload(value, kind="value"):
    number = safe_float(value)
    if number is None:
        text = normalize_text(value)
        if not text:
            return None
        return {"value": text, "display": text, "kind": kind}
    display = pct_label(number) if kind == "probability" else metric_label(number)
    return {"value": number, "display": display, "kind": kind}


def append_profile_field(target, label, value, kind="value", source_column=None):
    payload = profile_value_payload(value, kind)
    if payload is None:
        return
    payload.update({"label": label})
    duplicate_key = normalize_text(payload["label"]).lower()
    for item in target:
        item_key = normalize_text(item.get("label")).lower()
        if item_key == duplicate_key:
            return
    target.append(payload)


def finalize_player_profiles(profiles):
    records = []
    for profile in profiles.values():
        for group_key in ("stats", "probabilities", "confidence_fields"):
            fields = profile.get(group_key, [])
            profile[group_key] = sorted(fields, key=lambda item: normalize_text(item.get("label")).lower())
        profile["stats_object"] = {
            normalize_text(item.get("label")): item.get("value")
            for item in profile.get("stats", [])
            if normalize_text(item.get("label"))
        }
        profile["probabilities_object"] = {
            normalize_text(item.get("label")): item.get("value")
            for item in profile.get("probabilities", [])
            if normalize_text(item.get("label"))
        }
        records.append(profile)
    return sorted(records, key=lambda item: (normalize_text(item.get("team")).upper(), normalize_text(item.get("player"))))


def latest_rows_by_date(df, allowed_results_only=False):
    if df.empty or "date" not in df.columns:
        return pd.DataFrame()
    work = df.copy()
    if allowed_results_only:
        result_col = "result" if "result" in work.columns else None
        graded_col = "graded" if "graded" in work.columns else None
        if result_col:
            mask = work[result_col].astype(str).str.upper().isin({"WIN", "LOSS", "PUSH"})
            if graded_col:
                mask = mask | work[graded_col].astype(str).str.upper().eq("YES")
            work = work[mask].copy()
    latest = latest_date_in_df(work, "date")
    if not latest:
        return pd.DataFrame()
    work["_parsed_date"] = pd.to_datetime(work["date"], errors="coerce").dt.date
    return work[work["_parsed_date"] == latest].drop(columns=["_parsed_date"], errors="ignore").copy()


def latest_pitcher_tracking_snapshot():
    df = read_csv_df(MLB_FILES["pitcher_tracking"])
    predictions_df = read_csv_df(MLB_FILES["pitcher_predictions"])
    prediction_snapshot = {}

    if not predictions_df.empty:
        pitcher_col = find_first_column(predictions_df, ["pitcher_name", "Pitcher", "player_name"])
        if pitcher_col:
            for _, raw in predictions_df.iterrows():
                pitcher_key = normalize_text(raw.get(pitcher_col)).lower()
                if not pitcher_key:
                    continue
                season_k_pct = safe_float(raw.get("season_k_pct"))
                if season_k_pct is None:
                    pitcher_k_pct_display = safe_float(raw.get("Pitcher_K_Pct"))
                    season_k_pct = pitcher_k_pct_display / 100.0 if pitcher_k_pct_display is not None and pitcher_k_pct_display > 1 else pitcher_k_pct_display
                opponent_k_pct = safe_float(raw.get("opponent_k_pct"))
                if opponent_k_pct is None:
                    opponent_k_pct_display = safe_float(raw.get("Opponent_K_Pct"))
                    opponent_k_pct = opponent_k_pct_display / 100.0 if opponent_k_pct_display is not None and opponent_k_pct_display > 1 else opponent_k_pct_display
                prediction_snapshot[pitcher_key] = {
                    "pitcher_k_percent_season": season_k_pct,
                    "opponent_hitter_k_percent": opponent_k_pct,
                    "estimated_innings": safe_float(raw.get("Projected_IP") or raw.get("season_ip_per_start")),
                }

    if df.empty or "pitcher_name" not in df.columns:
        return prediction_snapshot
    work = df.copy()
    work["pitcher_name_key"] = work["pitcher_name"].astype(str).str.strip().str.lower()
    work["parsed_date"] = pd.to_datetime(work.get("date"), errors="coerce")
    work = work.sort_values(["pitcher_name_key", "parsed_date"], ascending=[True, False], kind="stable")
    snapshot = {}
    for pitcher_key, group in work.groupby("pitcher_name_key", dropna=False):
        if not pitcher_key:
            continue
        latest = group.iloc[0]
        recent_actuals = pd.to_numeric(group.get("actual_strikeouts"), errors="coerce").dropna().head(3)
        prediction_context = prediction_snapshot.get(pitcher_key, {})
        snapshot[pitcher_key] = {
            "pitcher_k_percent_season": safe_float(latest.get("season_k_pct"), default=prediction_context.get("pitcher_k_percent_season")),
            "opponent_hitter_k_percent": safe_float(latest.get("opponent_k_pct"), default=prediction_context.get("opponent_hitter_k_percent")),
            "estimated_innings": safe_float(latest.get("season_ip_per_start"), default=prediction_context.get("estimated_innings")),
            "recent_avg_ks": float(round(recent_actuals.mean(), 2)) if not recent_actuals.empty else None,
        }
    for pitcher_key, context in prediction_snapshot.items():
        snapshot.setdefault(pitcher_key, context)
    return snapshot


def best_hitter_tracking_snapshot():
    df = read_csv_df(MLB_FILES["hitter_tracking"])
    if df.empty or "hitter_name" not in df.columns:
        return {}
    work = df.copy()
    work["hitter_key"] = work["hitter_name"].astype(str).str.strip().str.lower()
    work["parsed_date"] = pd.to_datetime(work.get("date"), errors="coerce")
    work = work.sort_values(["hitter_key", "parsed_date"], ascending=[True, False], kind="stable")
    snapshot = {}
    for hitter_key, group in work.groupby("hitter_key", dropna=False):
        if not hitter_key:
            continue
        latest = group.iloc[0]
        snapshot[hitter_key] = {
            "pitcher_name": normalize_text(latest.get("pitcher_name")),
        }
    return snapshot


def board_reason(row):
    market = normalize_text(row.get("market")).upper()
    confidence_score = safe_float(row.get("confidence_score"), 0) or 0
    opp_k = safe_float(row.get("opponent_hitter_k_percent"))
    pitcher_k = safe_float(row.get("pitcher_k_percent_season"))
    recent_avg = safe_float(row.get("recent_avg_ks"))
    if market == "PITCHER_K" and opp_k is not None and opp_k >= 24:
        return "Opponent K-heavy"
    if market == "PITCHER_K" and pitcher_k is not None and pitcher_k >= 27:
        return "Swing-and-miss profile"
    if market == "PITCHER_K" and recent_avg is not None and recent_avg >= 6:
        return "Recent form edge"
    if market.startswith("HITTER") and normalize_text(row.get("play")).upper() == "OVER":
        return "Recent form edge"
    if market.startswith("HITTER") and normalize_text(row.get("play")).upper() == "UNDER":
        return "Pitcher matchup drag"
    if confidence_score >= 6:
        return "Model confidence spike"
    return "Model edge confirmed"


def market_label(row):
    market = normalize_text(row.get("market")).upper()
    mapping = {
        "PITCHER_K": "Pitcher Strikeouts",
        "PITCHER_OUTS": "Pitcher Outs",
        "HITTER_HIT": "Hits",
        "HITTER_HR": "Home Runs",
        "HITTER_RBI": "RBIs",
        "HITTER_HRRBI": "H+R+RBI",
    }
    return mapping.get(market, market.replace("_", " ").title() or "Prop")


def recommended_play(row):
    play = normalize_text(row.get("play")).upper()
    line = safe_float(row.get("line"))
    if play and line is not None:
        return f"{play.title()} {line:g}"
    fallback = normalize_text(row.get("recommended_play"))
    return fallback or play.title() or "n/a"


def projection_value(row):
    market = normalize_text(row.get("market")).upper()
    if market == "PITCHER_K":
        return safe_float(row.get("predicted_strikeouts"))
    return safe_float(row.get("projected_value"))


def team_lookup_from_pitchers():
    df = read_csv_df(MLB_FILES["pitchers"])
    if df.empty or "pitcher_name" not in df.columns or "team" not in df.columns:
        return {}
    return {
        normalize_text(row["pitcher_name"]).lower(): normalize_text(row["team"])
        for _, row in df.iterrows()
        if normalize_text(row.get("pitcher_name"))
    }


def build_mlb_hitter_context_lookup():
    lookup = {}

    lineup_df = read_csv_df(MLB_LINEUPS_FILE)
    if not lineup_df.empty:
        hitter_col = find_first_column(lineup_df, ["hitter_name", "player_name", "player"])
        team_col = find_first_column(lineup_df, ["team", "TEAM"])
        opponent_col = find_first_column(lineup_df, ["opponent", "opp", "matchup"])
        if hitter_col:
            for _, raw in lineup_df.iterrows():
                player = normalize_text(raw.get(hitter_col)).lower()
                if not player:
                    continue
                team = mlb_clean_text(raw.get(team_col), fallback="") if team_col else ""
                opponent = mlb_clean_text(raw.get(opponent_col), fallback="") if opponent_col else ""
                current = lookup.setdefault(player, {})
                if team and not current.get("team"):
                    current["team"] = team
                if opponent and not current.get("opponent"):
                    current["opponent"] = opponent

    fantasy_df = read_csv_df(MLB_FILES["fantasy"])
    if not fantasy_df.empty:
        player_col = find_first_column(fantasy_df, ["player_name", "hitter_name", "player", "hitter"])
        team_col = find_first_column(fantasy_df, ["team", "TEAM", "team_abbreviation", "TEAM_ABBREVIATION"])
        opponent_col = find_first_column(fantasy_df, ["opponent", "opp", "matchup", "opposing_team"])
        if player_col:
            for _, raw in fantasy_df.iterrows():
                player = normalize_text(raw.get(player_col)).lower()
                if not player:
                    continue
                team = mlb_clean_text(raw.get(team_col), fallback="") if team_col else ""
                opponent = mlb_clean_text(raw.get(opponent_col), fallback="") if opponent_col else ""
                current = lookup.setdefault(player, {})
                if team and not current.get("team"):
                    current["team"] = team
                if opponent and not current.get("opponent"):
                    current["opponent"] = opponent

    return lookup


def build_mlb_hitter_team_lookup():
    return {
        player: context.get("team", "")
        for player, context in build_mlb_hitter_context_lookup().items()
        if context.get("team")
    }


def build_mlb_pitcher_context_lookup():
    df = read_csv_df(MLB_FILES["pitchers"])
    if df.empty:
        return {}

    pitcher_col = find_first_column(df, ["pitcher_name", "player_name", "player"])
    team_col = find_first_column(df, ["team", "TEAM"])
    opponent_col = find_first_column(df, ["opponent", "opp", "matchup"])
    if not pitcher_col:
        return {}

    lookup = {}
    for _, raw in df.iterrows():
        pitcher = normalize_text(raw.get(pitcher_col)).lower()
        if not pitcher:
            continue
        lookup[pitcher] = {
            "pitcher_team": mlb_clean_text(raw.get(team_col), fallback="") if team_col else "",
            "pitcher_opponent": mlb_clean_text(raw.get(opponent_col), fallback="") if opponent_col else "",
        }
    return lookup


def load_mlb_best_bets():
    today_board = read_csv_df(MLB_FILES["best_bets"])
    history = read_csv_df(MLB_FILES["history"])
    tracking = latest_pitcher_tracking_snapshot()
    hitter_tracking = best_hitter_tracking_snapshot()
    team_lookup = team_lookup_from_pitchers()
    hitter_team_lookup = build_mlb_hitter_team_lookup()
    pitcher_context_lookup = build_mlb_pitcher_context_lookup()

    using_fallback = False
    source_path = MLB_FILES["best_bets"]
    source_df = pd.DataFrame()
    board_date = None

    if not today_board.empty:
        source_df = today_board.copy()
        board_date = latest_date_in_df(source_df, "date") or today_et()
    else:
        source_df = latest_rows_by_date(history, allowed_results_only=False)
        using_fallback = True
        source_path = MLB_FILES["history"]
        board_date = latest_date_in_df(source_df, "date")

    records = []
    if not source_df.empty:
        work = source_df.copy()
        work["edge_sort"] = pd.to_numeric(work.get("edge"), errors="coerce").abs().fillna(0)
        work["score_sort"] = pd.to_numeric(work.get("confidence_score"), errors="coerce").fillna(0)
        work = work.sort_values(["score_sort", "edge_sort"], ascending=[False, False], kind="stable")
        for _, raw in work.iterrows():
            row = raw.to_dict()
            player = normalize_text(row.get("player_name"))
            player_key = player.lower()
            market = normalize_text(row.get("market")).upper()
            projection = projection_value(row)
            team = ""
            if market.startswith("PITCHER"):
                team = team_lookup.get(player_key, "")
            elif market.startswith("HITTER"):
                pitcher_context = pitcher_context_lookup.get(normalize_text(row.get("matchup_pitcher")).lower(), {})
                team = mlb_clean_text(hitter_team_lookup.get(player_key), fallback="") or mlb_clean_text(pitcher_context.get("pitcher_opponent"), fallback="")
            opponent = normalize_text(row.get("opponent")) or normalize_text(row.get("matchup_pitcher")) or "TBD"
            if market.startswith("HITTER"):
                pitcher_context = pitcher_context_lookup.get(normalize_text(row.get("matchup_pitcher")).lower(), {})
                opponent = mlb_clean_text(pitcher_context.get("pitcher_team"), fallback="") or opponent
            enriched = {
                "player": player,
                "team": team or "TBD",
                "opponent": opponent,
                "stat_type": market_label(row),
                "sportsbook_line": safe_float(row.get("line")),
                "projection": projection,
                "edge": safe_float(row.get("edge")),
                "confidence": confidence_level(row.get("confidence") or row.get("confidence_score")),
                "recommended_play": recommended_play(row),
                "market": market,
                "result": grade_result_label(row.get("result")),
                "board_date": parse_date(row.get("date")),
                "confidence_score": safe_float(row.get("confidence_score"), 0),
            }
            if market == "PITCHER_K":
                pitcher_context = tracking.get(player_key, {})
                enriched.update(pitcher_context)
            elif player_key in hitter_tracking:
                enriched["opponent"] = opponent
            enriched["reason"] = board_reason(enriched)
            records.append(enriched)

    top_plays = records[:7]
    last_updated = file_timestamp(source_path)
    if not board_date and last_updated:
        board_date = last_updated.date()
    banner = "Showing most recent available board" if using_fallback or (board_date and board_date < today_et()) else ""
    return {
        "records": records,
        "top_plays": top_plays,
        "board_date": board_date,
        "banner": banner,
        "source_label": public_data_source_label(source_path),
        "last_updated": last_updated,
        "props_scanned": props_scanned_count(),
        "plays_shown": len(records),
        "model_version": MODEL_VERSION,
        "data_source_freshness": source_freshness_label(last_updated),
    }


def load_mlb_pitcher_board():
    props = read_csv_df(MLB_FILES["pitchers"])
    tracking = latest_pitcher_tracking_snapshot()
    using_fallback = False
    source_path = MLB_FILES["pitchers"]

    if props.empty:
        fallback = latest_rows_by_date(read_csv_df(MLB_FILES["pitcher_tracking"]), allowed_results_only=False)
        using_fallback = True
        source_path = MLB_FILES["pitcher_tracking"]
        props = fallback

    records = []
    for _, raw in props.iterrows():
        row = raw.to_dict()
        name = normalize_text(row.get("pitcher_name"))
        key = name.lower()
        line = safe_float(row.get("best_over_line"))
        projected_ks = safe_float(row.get("projected_strikeouts") or row.get("predicted_strikeouts"))
        context = tracking.get(key, {})
        est_innings = safe_float(row.get("projected_ip"))
        if est_innings is None:
            est_outs = safe_float(row.get("projected_outs") or row.get("predicted_outs"))
            est_innings = round(est_outs / 3, 2) if est_outs is not None else context.get("estimated_innings")
        record = {
            "pitcher_name": name,
            "team": normalize_text(row.get("team")) or "TBD",
            "opponent": normalize_text(row.get("opponent")) or "TBD",
            "projected_ks": projected_ks,
            "sportsbook_line": line,
            "edge": round(projected_ks - line, 2) if projected_ks is not None and line is not None else None,
            "confidence": confidence_level(row.get("recommendation_confidence") or row.get("confidence")),
            "pitcher_k_percent_season": context.get("pitcher_k_percent_season"),
            "opponent_hitter_k_percent": context.get("opponent_hitter_k_percent"),
            "estimated_innings": est_innings,
            "recent_avg_ks": context.get("recent_avg_ks"),
            "recommended_play": normalize_text(row.get("recommended_play")) or (f"Over {line:g}" if line is not None else "n/a"),
            "board_date": parse_date(row.get("date")),
        }
        records.append(record)

    records.sort(key=lambda item: ((item.get("edge") or 0), (item.get("projected_ks") or 0)), reverse=True)
    board_date = latest_date_in_df(props, "date")
    last_updated = file_timestamp(source_path)
    if not board_date and last_updated:
        board_date = last_updated.date()
    banner = "Showing most recent available board" if using_fallback or (board_date and board_date < today_et()) else ""
    return {
        "records": records[:25],
        "board_date": board_date,
        "banner": banner,
        "source_label": public_data_source_label(source_path),
        "last_updated": last_updated,
        "props_scanned": pitcher_props_scanned_count() or len(records),
        "plays_shown": min(len(records), 25),
        "model_version": MODEL_VERSION,
        "data_source_freshness": source_freshness_label(last_updated),
    }


def latest_completed_history_frame():
    history = read_csv_df(MLB_FILES["history"])
    completed = latest_rows_by_date(history, allowed_results_only=True)
    if not completed.empty:
        return completed, MLB_FILES["history"], latest_date_in_df(completed, "date"), True
    fallback = latest_rows_by_date(history, allowed_results_only=False)
    return fallback, MLB_FILES["history"], latest_date_in_df(fallback, "date"), False


def tidy_history_rows(df):
    rows = []
    if df.empty:
        return rows
    team_lookup = team_lookup_from_pitchers()
    for _, raw in df.iterrows():
        row = raw.to_dict()
        player = normalize_text(row.get("player_name"))
        market = normalize_text(row.get("market")).upper()
        team = team_lookup.get(player.lower(), "") if market.startswith("PITCHER") else ""
        rows.append({
            "date": normalize_text(row.get("date")),
            "player": player,
            "team": team or "TBD",
            "opponent": normalize_text(row.get("opponent")) or normalize_text(row.get("matchup_pitcher")) or "TBD",
            "stat_type": market_label(row),
            "line": safe_float(row.get("line")),
            "projection": projection_value(row),
            "edge": safe_float(row.get("edge")),
            "confidence": confidence_level(row.get("confidence") or row.get("confidence_score")),
            "play": recommended_play(row),
            "actual": safe_float(row.get("actual_stat")),
            "result": grade_result_label(row.get("result")) or "Pending",
        })
    return rows


def load_mlb_history_board():
    df, source_path, board_date, has_graded = latest_completed_history_frame()
    rows = tidy_history_rows(df)
    last_updated = file_timestamp(source_path)
    banner = "Showing most recent available board" if board_date and board_date < today_et() else ""
    return {
        "records": rows,
        "board_date": board_date,
        "banner": banner,
        "source_label": public_data_source_label(source_path),
        "last_updated": last_updated,
        "props_scanned": len(rows),
        "plays_shown": len(rows),
        "model_version": MODEL_VERSION,
        "data_source_freshness": source_freshness_label(last_updated),
        "has_graded": has_graded,
    }


def load_mlb_graded_board():
    current = read_csv_df(MLB_FILES["best_bets"])
    graded_today = pd.DataFrame()
    if not current.empty and "graded" in current.columns:
        graded_today = current[current["graded"].astype(str).str.upper() == "YES"].copy()

    using_fallback = False
    source_path = MLB_FILES["best_bets"]
    board_date = latest_date_in_df(graded_today, "date")
    if graded_today.empty:
        graded_today, source_path, board_date, _ = latest_completed_history_frame()
        using_fallback = True

    rows = tidy_history_rows(graded_today)
    last_updated = file_timestamp(source_path)
    banner = "Showing most recent available board" if using_fallback or (board_date and board_date < today_et()) else ""
    return {
        "records": rows,
        "board_date": board_date,
        "banner": banner,
        "source_label": public_data_source_label(source_path),
        "last_updated": last_updated,
        "props_scanned": len(rows),
        "plays_shown": len(rows),
        "model_version": MODEL_VERSION,
        "data_source_freshness": source_freshness_label(last_updated),
    }


def compute_streak(history_df):
    if history_df.empty or "result" not in history_df.columns:
        return "No active streak"
    work = history_df.copy()
    work["parsed_date"] = pd.to_datetime(work.get("date"), errors="coerce")
    work = work.sort_values(["parsed_date"], ascending=[False], kind="stable")
    streak_result = None
    streak_count = 0
    for result in work["result"].astype(str).str.upper():
        if result not in {"WIN", "LOSS"}:
            continue
        if streak_result is None:
            streak_result = result
            streak_count = 1
            continue
        if result == streak_result:
            streak_count += 1
            continue
        break
    if not streak_result:
        return "No active streak"
    label = "W" if streak_result == "WIN" else "L"
    return f"{label}{streak_count}"


def summarize_window(history_df, days):
    if history_df.empty or "date" not in history_df.columns or "result" not in history_df.columns:
        return "0-0"
    cutoff = today_et() - timedelta(days=days - 1)
    work = history_df.copy()
    work["parsed_date"] = pd.to_datetime(work.get("date"), errors="coerce").dt.date
    work = work[work["parsed_date"].notna() & (work["parsed_date"] >= cutoff)]
    wins = (work["result"].astype(str).str.upper() == "WIN").sum()
    losses = (work["result"].astype(str).str.upper() == "LOSS").sum()
    return f"{wins}-{losses}"


def load_mlb_record_board():
    history = read_csv_df(MLB_FILES["history"])
    daily = read_csv_df(MLB_FILES["record"])
    graded = history[history["result"].astype(str).str.upper().isin({"WIN", "LOSS", "PUSH"})].copy() if not history.empty and "result" in history.columns else pd.DataFrame()
    wins = int((graded["result"].astype(str).str.upper() == "WIN").sum()) if not graded.empty else 0
    losses = int((graded["result"].astype(str).str.upper() == "LOSS").sum()) if not graded.empty else 0
    total = wins + losses
    win_rate = round((wins / total) * 100, 1) if total else 0.0
    summary = {
        "total_wins": wins,
        "total_losses": losses,
        "win_rate": win_rate,
        "last_7_days": summarize_window(graded, 7),
        "last_30_days": summarize_window(graded, 30),
        "current_streak": compute_streak(graded),
    }
    rows = []
    if not daily.empty:
        work = daily.copy()
        work["parsed_date"] = pd.to_datetime(work.get("date"), errors="coerce")
        work = work.sort_values(["parsed_date", "market"], ascending=[False, True], kind="stable").drop(columns=["parsed_date"], errors="ignore")
        for _, raw in work.iterrows():
            row = raw.to_dict()
            rows.append({
                "date": normalize_text(row.get("date")),
                "market": market_label(row),
                "bets": safe_int(row.get("bets")),
                "wins": safe_int(row.get("wins")),
                "losses": safe_int(row.get("losses")),
                "pushes": safe_int(row.get("pushes")),
                "win_rate": pct_label(row.get("win_rate")),
            })
    last_updated = max(filter(None, [file_timestamp(MLB_FILES["record"]), file_timestamp(MLB_FILES["history"])]), default=None)
    return {
        "summary": summary,
        "records": rows,
        "board_date": latest_date_in_df(daily, "date") or latest_date_in_df(history, "date"),
        "banner": "Showing most recent available board" if (latest_date_in_df(daily, "date") or latest_date_in_df(history, "date")) and (latest_date_in_df(daily, "date") or latest_date_in_df(history, "date")) < today_et() else "",
        "source_label": public_data_source_label(MLB_FILES["record"]),
        "last_updated": last_updated,
        "props_scanned": len(graded),
        "plays_shown": len(rows),
        "model_version": MODEL_VERSION,
        "data_source_freshness": source_freshness_label(last_updated),
    }


def load_hitter_summary(kind):
    df = read_csv_df(MLB_FILES["hitters"])
    if df.empty:
        return []
    category_col = find_first_column(df, ["Category", "category"])
    hitter_col = find_first_column(df, ["Hitter", "hitter_name", "player_name"])
    pitcher_col = find_first_column(df, ["Pitcher", "pitcher_name", "matchup_pitcher"])
    team_col = find_first_column(df, ["Team", "team", "TEAM"])
    opponent_col = find_first_column(df, ["Opponent", "opponent", "opp", "matchup"])
    if kind == "mlb_hitters":
        prob_col = "Hit Probability"
        category_match = "HIT TARGETS"
        keep = [hitter_col, pitcher_col, team_col, opponent_col, "Hit Probability", "Total Bases >= 2", "Home Run Probability", "Stolen Base Probability"]
        rename = {"Hit Probability": "Hit %", "Total Bases >= 2": "2+ Bases %", "Home Run Probability": "HR %", "Stolen Base Probability": "SB %"}
    elif kind == "mlb_hit2plus":
        return []
    elif kind == "mlb_tb2":
        prob_col = "Total Bases >= 2"
        category_match = "2+ TOTAL BASES TARGETS"
        keep = [hitter_col, pitcher_col, team_col, opponent_col, "Total Bases >= 2", "Hit Probability", "Home Run Probability"]
        rename = {"Total Bases >= 2": "2+ Bases %", "Hit Probability": "Hit %", "Home Run Probability": "HR %"}
    elif kind == "mlb_rbi":
        prob_col = "RBI Probability"
        category_match = "RBI TARGETS"
        keep = [hitter_col, pitcher_col, team_col, opponent_col, "RBI Probability", "Hit Probability", "Home Run Probability"]
        rename = {"RBI Probability": "RBI %", "Hit Probability": "Hit %", "Home Run Probability": "HR %"}
    elif kind == "mlb_hitter_k":
        prob_col = "Hitter Strikeout %"
        category_match = "HITTER STRIKEOUT TARGETS"
        keep = [hitter_col, pitcher_col, team_col, opponent_col, "Hitter Strikeout %", "Projected Hitter Strikeouts", "Hit Probability"]
        rename = {"Hitter Strikeout %": "K %", "Projected Hitter Strikeouts": "Projected K", "Hit Probability": "Hit %"}
    elif kind == "mlb_sb":
        prob_col = "Stolen Base Probability"
        category_match = "STOLEN BASE TARGETS"
        keep = [hitter_col, pitcher_col, team_col, opponent_col, "Stolen Base Probability", "Hit Probability", "Hitter Strikeout %"]
        rename = {"Stolen Base Probability": "SB %", "Hit Probability": "Hit %", "Hitter Strikeout %": "K %"}
    else:
        prob_col = "Home Run Probability"
        category_match = "HOME RUN TARGETS"
        keep = [hitter_col, pitcher_col, team_col, opponent_col, "Home Run Probability", "Hit Probability", "Total Bases >= 2"]
        rename = {"Home Run Probability": "HR %", "Hit Probability": "Hit %", "Total Bases >= 2": "2+ Bases %"}

    if prob_col not in df.columns or not hitter_col:
        return []
    work = df.copy()
    if category_col:
        filtered = work[work[category_col].astype(str).str.upper() == category_match].copy()
        if not filtered.empty:
            work = filtered
    work[prob_col] = pd.to_numeric(work[prob_col], errors="coerce")
    work = work.sort_values(prob_col, ascending=False, kind="stable").drop_duplicates(subset=[hitter_col], keep="first")
    keep = [column for column in keep if column and column in work.columns]
    rename_map = {hitter_col: "Hitter", pitcher_col: "Pitcher", **rename}
    if team_col:
        rename_map[team_col] = "Team"
    if opponent_col:
        rename_map[opponent_col] = "Opponent"
    work = work[keep].rename(columns=rename_map)
    return records_from_df(work)


def load_hitter_full_projection_records(sort_by=None):
    df = read_csv_df(MLB_FILES["hitters_full"])
    if df.empty:
        return []

    required = [
        "hitter_name",
        "team",
        "opponent",
        "pitcher_name",
        "hit_prob",
        "tb2_prob",
        "hr_prob",
        "sb_prob",
        "hitter_strikeout_pct",
        "projected_hitter_strikeouts",
    ]
    if any(column not in df.columns for column in required):
        return []

    work = filter_mlb_frame_to_active_slate(df, "team", "opponent").copy()
    numeric_columns = [
        "lineup_spot",
        "expected_pa",
        "hit_prob",
        "tb2_prob",
        "hr_prob",
        "sb_prob",
        "hitter_strikeout_pct",
        "projected_hitter_strikeouts",
    ]
    for column, _ in MLB_REALISM_FIELD_DISPLAY:
        if column in df.columns:
            numeric_columns.append(column)
    for column in numeric_columns:
        work[column] = pd.to_numeric(work.get(column), errors="coerce")

    keep = [
        "hitter_name",
        "team",
        "opponent",
        "pitcher_name",
        "lineup_spot",
        "expected_pa",
        "hit_prob",
        "tb2_prob",
        "hr_prob",
        "sb_prob",
        "hitter_strikeout_pct",
        "projected_hitter_strikeouts",
    ]
    keep.extend([column for column, _ in MLB_REALISM_FIELD_DISPLAY if column in work.columns])
    rename = {
        "hitter_name": "Hitter",
        "team": "Team",
        "opponent": "Opponent",
        "pitcher_name": "Pitcher",
        "lineup_spot": "Lineup Spot",
        "expected_pa": "Expected PA",
        "hit_prob": "Hit %",
        "tb2_prob": "2+ Bases %",
        "hr_prob": "HR %",
        "sb_prob": "SB %",
        "hitter_strikeout_pct": "Hitter K %",
        "projected_hitter_strikeouts": "Projected Hitter Strikeouts",
    }
    work = work[keep].rename(columns=rename)
    sort_field = sort_by if sort_by in work.columns else None
    if sort_field:
        work = work.sort_values(
            [sort_field, "Hit %", "2+ Bases %", "HR %"],
            ascending=False,
            kind="stable",
        )
    else:
        work = work.sort_values(
            ["Hit %", "2+ Bases %", "HR %", "SB %", "Projected Hitter Strikeouts"],
            ascending=False,
            kind="stable",
        )
    work = work.drop_duplicates(subset=["Hitter"], keep="first")
    return records_from_df(work)


def mlb_display_confidence(value):
    tier = confidence_level(value)
    return {"High": "Top", "Medium": "Strong", "Low": "Active"}.get(tier, "Active")


def mlb_projection_confidence(value, edge=None):
    projection = safe_float(value, default=0)
    edge_value = abs(safe_float(edge, default=0))
    if projection >= 58 or edge_value >= 8:
        return "High"
    if projection >= 54 or edge_value >= 4:
        return "Medium"
    return "Low"


def mlb_clean_text(value, fallback="n/a"):
    text = normalize_text(value)
    if not text or text.upper() == "TBD":
        return fallback
    return text


MLB_CLEAN_STANDARD_HITTER_LINES = {
    "K": (0.5, 2.5),
    "HIT": (1.5, 1.5),
    "HITS": (1.5, 1.5),
    "TB": (1.5, 2.5),
    "RBI": (1.5, 1.5),
    "RUNS": (1.5, 1.5),
    "H+R+RBI": (1.5, 2.5),
}

MLB_CLEAN_STANDARD_PITCHER_LINES = {
    "K": (0.5, 12.5),
    "OUTS": (9.0, 24.5),
}


def mlb_boolish(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def mlb_blankish(value):
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return str(value).strip() == ""


def mlb_half_step_line(value):
    try:
        line = float(value)
    except Exception:
        return False
    return abs((line * 2.0) - round(line * 2.0)) < 1e-9


def mlb_line_is_clean_display_row(row):
    odds_type = normalize_text(row.get("ODDS_TYPE", row.get("odds_type", ""))).lower()
    if odds_type and odds_type != "standard":
        return False

    if mlb_boolish(row.get("ADJUSTED_ODDS", row.get("adjusted_odds", False))):
        return False
    if not mlb_blankish(row.get("FLASH_SALE_LINE_SCORE", row.get("flash_sale_line_score", None))):
        return False
    if mlb_boolish(row.get("IS_PROMO", row.get("is_promo", False))):
        return False
    if mlb_boolish(row.get("IN_GAME", row.get("in_game", False))):
        return False
    if mlb_boolish(row.get("IS_LIVE", row.get("is_live", False))):
        return False

    status = normalize_text(row.get("STATUS", row.get("status", ""))).lower()
    if status and status not in {"pre_game", "scheduled"}:
        return False

    player_type = normalize_text(row.get("PLAYER_TYPE", row.get("player_type", ""))).upper()
    stat = normalize_text(row.get("STAT", row.get("stat", ""))).upper()
    line = safe_float(row.get("LINE", row.get("line", None)))
    if line is None or line <= 0 or not mlb_half_step_line(line):
        return False

    if player_type == "HITTER":
        allowed = MLB_CLEAN_STANDARD_HITTER_LINES.get(stat)
    elif player_type == "PITCHER":
        allowed = MLB_CLEAN_STANDARD_PITCHER_LINES.get(stat)
    else:
        return False

    if allowed is None:
        return False
    low, high = allowed
    return low <= line <= high


def build_mlb_line_lookup():
    line_sources = [MLB_FILES["normalized_lines"], MLB_FILES["lines"]]
    df = pd.DataFrame()
    for source_path in line_sources:
        candidate = read_csv_df(source_path)
        if candidate.empty:
            continue
        slate_col = find_first_column(candidate, ["SLATE_DATE", "slate_date"])
        if slate_col:
            slate_dates = sorted(
                set(candidate[slate_col].astype(str).str.slice(0, 10).str.strip())
            )
            if slate_dates != [today_et().isoformat()]:
                continue
        odds_col = find_first_column(candidate, ["ODDS_TYPE", "odds_type"])
        if odds_col:
            candidate = candidate[
                candidate[odds_col].astype(str).str.lower().str.strip().eq("standard")
            ].copy()
        if not candidate.empty:
            candidate = candidate[candidate.apply(mlb_line_is_clean_display_row, axis=1)].copy()
        if not candidate.empty:
            df = candidate
            break
    if df.empty:
        return {}, {}
    work = df.copy()
    work.columns = [str(column).strip() for column in work.columns]
    player_col = find_first_column(work, ["PLAYER_NAME", "player_name"])
    stat_col = find_first_column(work, ["STAT", "stat"])
    line_col = find_first_column(work, ["LINE", "line"])
    opponent_col = find_first_column(work, ["RAW_DESCRIPTION", "RAW_OPPONENT", "opponent"])
    board_col = find_first_column(work, ["BOARD_TIME", "board_time"])
    regular_hint_col = find_first_column(work, ["IS_REGULAR_HINT", "is_regular_hint"])
    goblin_col = find_first_column(work, ["IS_GOBLIN", "is_goblin"])
    demon_col = find_first_column(work, ["IS_DEMON", "is_demon"])
    if not player_col or not stat_col:
        return {}, {}
    if regular_hint_col:
        work["_regular_hint"] = work[regular_hint_col].fillna(False).astype(bool)
    else:
        work["_regular_hint"] = False
    if goblin_col:
        work["_is_goblin"] = work[goblin_col].fillna(False).astype(bool)
    else:
        work["_is_goblin"] = False
    if demon_col:
        work["_is_demon"] = work[demon_col].fillna(False).astype(bool)
    else:
        work["_is_demon"] = False
    if board_col:
        work["_board_time"] = pd.to_datetime(work[board_col], errors="coerce", utc=True)
    else:
        work["_board_time"] = pd.NaT
    line_lookup = {}
    opponent_lookup = {}
    for _, group in work.groupby([player_col, stat_col], dropna=False):
        group = group.copy()
        group = group.sort_values("_board_time", ascending=False, kind="stable", na_position="last")

        regular_rows = group[group["_regular_hint"] == True]
        if not regular_rows.empty:
            chosen = regular_rows.iloc[0]
        else:
            normal_rows = group[(group["_is_goblin"] == False) & (group["_is_demon"] == False)]
            if not normal_rows.empty:
                chosen = normal_rows.iloc[0]
            else:
                # No trustworthy main line. Keep the player row on the site, but leave line blank.
                chosen = None

        if chosen is None:
            raw_player = normalize_text(group.iloc[0].get(player_col)).lower()
            raw_stat = normalize_text(group.iloc[0].get(stat_col)).upper()
            if raw_player and raw_stat:
                line_lookup.setdefault((raw_player, raw_stat), None)
                opponent_lookup.setdefault(
                    (raw_player, raw_stat),
                    mlb_clean_text(group.iloc[0].get(opponent_col), fallback="Matchup pending") if opponent_col else "Matchup pending",
                )
            continue

        raw = chosen
        player = normalize_text(raw.get(player_col)).lower()
        stat = normalize_text(raw.get(stat_col)).upper()
        if not player or not stat:
            continue
        key = (player, stat)
        line_lookup.setdefault(key, safe_float(raw.get(line_col)) if line_col else None)
        opponent_lookup.setdefault(key, mlb_clean_text(raw.get(opponent_col), fallback="Matchup pending") if opponent_col else "Matchup pending")
    return line_lookup, opponent_lookup


def load_mlb_fantasy_projection_rows():
    df = read_csv_df(MLB_FILES["fantasy"])
    if df.empty:
        return []

    player_col = find_first_column(df, ["player_name", "hitter_name", "player", "hitter"])
    if not player_col:
        return []

    team_col = find_first_column(df, ["team", "TEAM", "team_abbreviation", "TEAM_ABBREVIATION"])
    opponent_col = find_first_column(df, ["opponent", "opp", "matchup", "opposing_team"])
    projection_col = find_first_column(
        df,
        [
            "fantasy_points",
            "fantasy_projection",
            "fantasy_proj",
            "projected_fantasy",
            "projected_fantasy_points",
            "sim_fantasy_points",
            "sim_fantasy",
            "p50_fantasy_points",
        ],
    )
    confidence_col = find_first_column(df, ["confidence", "confidence_tier", "fantasy_confidence"])
    p90_col = find_first_column(df, ["fantasy_points_p90", "p90_fantasy_points", "ceiling", "fantasy_ceiling"])
    p10_col = find_first_column(df, ["fantasy_points_p10", "p10_fantasy_points", "floor", "fantasy_floor"])

    if not projection_col:
        return []

    line_lookup, opponent_lookup = build_mlb_line_lookup()
    rows = []
    for _, raw in df.iterrows():
        player = normalize_text(raw.get(player_col))
        projection = safe_float(raw.get(projection_col))
        if not player or projection is None:
            continue
        player_key = player.lower()
        line = line_lookup.get((player_key, "FANTASY"))
        opponent = mlb_clean_text(raw.get(opponent_col), fallback="")
        if not opponent:
            opponent = opponent_lookup.get((player_key, "FANTASY"), "Matchup pending")
        p90 = safe_float(raw.get(p90_col)) if p90_col else None
        p10 = safe_float(raw.get(p10_col)) if p10_col else None
        edge = round(projection - line, 2) if line is not None else None
        confidence = normalize_text(raw.get(confidence_col)) if confidence_col else ""
        if not confidence:
            spread = None
            if p90 is not None and p10 is not None:
                spread = p90 - p10
            if spread is not None and spread <= 8:
                confidence = "High"
            elif spread is not None and spread <= 14:
                confidence = "Medium"
            else:
                confidence = mlb_projection_confidence(projection, edge)

        rows.append({
            "player": player,
            "team": mlb_clean_text(raw.get(team_col), fallback="") if team_col else "",
            "opponent": opponent,
            "stat": "Fantasy Points",
            "projection": projection,
            "projection_display": metric_label(projection),
            "line": line,
            "edge": edge,
            "confidence": confidence,
            "lean": "Over" if edge is None or edge >= 0 else "Under",
            "sort_projection": projection,
            "sort_edge": abs(safe_float(edge, default=0)),
            "sort_confidence": confidence_rank(confidence),
        })
    return rows


def ensure_mlb_minimum_team_players(records, fallback_rows, min_players=3):
    if not records:
        return records

    team_players = {}
    for row in records:
        team = normalize_text(row.get("team"))
        player = normalize_text(row.get("player"))
        if not team or not player:
            continue
        team_players.setdefault(team, set()).add(player.lower())

    additions = []
    for row in sorted(fallback_rows, key=lambda item: safe_float(item.get("sort_projection"), default=-9999), reverse=True):
        team = normalize_text(row.get("team"))
        player = normalize_text(row.get("player"))
        if not team or not player:
            continue
        players = team_players.setdefault(team, set())
        if len(players) >= min_players:
            continue
        player_key = player.lower()
        if player_key in players:
            continue
        additions.append(row)
        players.add(player_key)

    if additions:
        records = records + additions
    records.sort(key=lambda item: (safe_float(item.get("sort_projection"), default=-9999), safe_float(item.get("sort_edge"), default=-9999)), reverse=True)
    return records


def filter_mlb_hitter_projection_rows(rows, target_stat=None, include_zero=False):
    if not target_stat:
        return list(rows)

    target = normalize_text(target_stat).lower()
    filtered = []
    for row in rows:
        if normalize_text(row.get("stat")).lower() != target:
            continue
        value = safe_float(row.get("sort_projection"), default=None)
        if value is None:
            value = safe_float(row.get("projection"), default=None)
        if value is None:
            continue
        if not include_zero and value <= 0:
            continue
        filtered.append(row)

    filtered.sort(
        key=lambda item: (
            safe_float(item.get("sort_projection"), default=-9999),
            safe_float(item.get("sort_tiebreaker"), default=-9999),
            safe_float(item.get("sort_edge"), default=-9999),
            safe_float(item.get("sort_confidence"), default=-9999),
        ),
        reverse=True,
    )
    return filtered


def mlb_hitter_sort_column_label(target_stat):
    fields = MLB_HITTER_STAT_SORT_FIELDS.get(target_stat)
    if not fields:
        return "sort_projection"
    primary, secondary = fields
    return f"{primary} desc, {secondary} desc tie-break"


def mlb_first_numeric_from_row(row, columns):
    for column in columns:
        value = safe_float(row.get(column), default=None)
        if value is not None:
            return value
    return None


def log_mlb_hitter_category_debug(route_label, category_key, target_stat, rows):
    top_players = [normalize_text(row.get("player")) for row in rows[:5]]
    LOGGER.info(
        "MLB hitter category route=%s selected_category=%s metric=%s top5=%s",
        route_label,
        category_key,
        mlb_hitter_sort_column_label(target_stat),
        top_players,
    )
    return ""


def build_mlb_hitter_projection_board():
    full_board_source = MLB_OUTPUT_DIR / "hitter_predictions_full.csv"
    if full_board_source.exists():
        summary_source = full_board_source
    elif MLB_READER_MODE == "canonical" and MLB_FILES["hitters_full"].exists():
        summary_source = MLB_FILES["hitters_full"]
    else:
        summary_source = MLB_FILES["hitters"]
    using_full_board = summary_source.name == "hitter_predictions_full.csv"
    summary_df = read_csv_df(summary_source)
    if summary_df.empty:
        return []

    hitter_col = find_first_column(summary_df, ["Hitter", "hitter_name", "player_name"])
    pitcher_col = find_first_column(summary_df, ["Pitcher", "pitcher_name", "matchup_pitcher"])
    team_col = find_first_column(summary_df, ["Team", "team", "TEAM"])
    opponent_col = find_first_column(summary_df, ["Opponent", "opponent", "opp", "matchup"])
    if not using_full_board:
        summary_df = filter_mlb_frame_to_active_slate(summary_df, team_col, opponent_col)
        if summary_df.empty:
            return []
    if not hitter_col:
        return []

    line_lookup, opponent_lookup = build_mlb_line_lookup()
    hitter_context_lookup = build_mlb_hitter_context_lookup()
    team_lookup = build_mlb_hitter_team_lookup()
    pitcher_context_lookup = build_mlb_pitcher_context_lookup()

    stat_configs = [
        ("Hits", "Hit Probability", "HIT", None),
        ("2+ Hits", "blended_hit_2plus_prob_v2", "HIT2", None),
        ("2+ Bases", "Total Bases >= 2", "TB", None),
        ("RBI", "RBI Probability", "RBI", None),
        ("Home Runs", "Home Run Probability", "HR", None),
        ("Stolen Bases", "Stolen Base Probability", "SB", None),
        ("Hitter Strikeouts", "Hitter Strikeout %", "K", None),
        ("Runs", "Runs Probability", "RUNS", None),
        ("Fantasy Points", "Fantasy Points", "FANTASY", None),
    ]

    records_by_key = {}
    for _, raw in summary_df.iterrows():
        row = raw.to_dict()
        player = normalize_text(row.get(hitter_col))
        if not player:
            continue
        player_key = player.lower()
        opponent_pitcher = mlb_clean_text(row.get(pitcher_col), fallback="Pitcher pending") if pitcher_col else "Pitcher pending"
        pitcher_context = pitcher_context_lookup.get(opponent_pitcher.lower(), {})
        hitter_context = hitter_context_lookup.get(player_key, {})
        source_team = mlb_clean_text(row.get(team_col), fallback="") if team_col else ""
        source_opponent = mlb_clean_text(row.get(opponent_col), fallback="") if opponent_col else ""
        for stat_label, prob_col, stat_code, default_line in stat_configs:
            if prob_col not in summary_df.columns:
                canonical_map = {
                    "Hit Probability": "hit_prob",
                    "blended_hit_2plus_prob_v2": "MC_Hit2Plus_Prob",
                    "Total Bases >= 2": "tb2_prob",
                    "RBI Probability": "rbi_prob",
                    "Home Run Probability": "hr_prob",
                    "Stolen Base Probability": "sb_prob",
                    "Hitter Strikeout %": "hitter_strikeout_pct",
                    "Projected Hitter Strikeouts": "projected_hitter_strikeouts",
                }
                mapped_col = canonical_map.get(prob_col)
                if mapped_col and mapped_col in summary_df.columns:
                    prob_col = mapped_col
                else:
                    continue
            if prob_col not in row:
                continue
            projection = safe_float(row.get(prob_col))
            blend_col, shadow_col, current_col = MLB_REALISM_STAT_FIELDS.get(
                stat_label, (None, None, None)
            )
            blend_value = safe_float(row.get(blend_col)) if blend_col else None
            shadow_value = safe_float(row.get(shadow_col)) if shadow_col else None
            current_value = safe_float(row.get(current_col)) if current_col else None
            if blend_value is not None:
                projection = blend_value
            if projection is None:
                continue
            sort_tiebreaker = mlb_first_numeric_from_row(
                row,
                MLB_HITTER_TIEBREAKER_COLUMNS.get(stat_label, ()),
            )
            line = line_lookup.get((player_key, stat_code), default_line)
            inferred_team = mlb_clean_text(pitcher_context.get("pitcher_opponent"), fallback="")
            inferred_opponent = mlb_clean_text(pitcher_context.get("pitcher_team"), fallback="")
            context_team = mlb_clean_text(hitter_context.get("team"), fallback="")
            context_opponent = mlb_clean_text(hitter_context.get("opponent"), fallback="")
            resolved_team = source_team or context_team or mlb_clean_text(team_lookup.get(player_key), fallback="") or inferred_team
            opponent = source_opponent or context_opponent or opponent_lookup.get((player_key, stat_code), "") or inferred_opponent or opponent_pitcher
            if stat_label == "Hitter Strikeouts" and prob_col in {"Hitter Strikeout %", "hitter_strikeout_pct"}:
                edge = round(projection - 50.0, 1)
                projection_display = pct_label(projection)
            elif stat_label == "Hitter Strikeouts":
                edge = round(projection - line, 2) if line is not None else None
                projection_display = metric_label(projection)
            elif stat_label == "Fantasy Points":
                edge = round(projection - line, 2) if line is not None else None
                projection_display = metric_label(projection)
            else:
                edge = round(projection - 50.0, 1)
                projection_display = pct_label(projection)
            confidence = mlb_projection_confidence(projection, edge)
            record = {
                "player": player,
                "team": resolved_team,
                "opponent": opponent,
                "stat": stat_label,
                "projection": projection,
                "projection_display": projection_display,
                "line": line,
                "edge": edge,
                "confidence": confidence,
                "lean": "Over" if edge is None or edge >= 0 else "Under",
                "outcome_blend": blend_value,
                "outcome_shadow": shadow_value,
                "outcome_current": current_value,
                "realism_source": "Blended shadow" if blend_value is not None else "Primary",
                "sort_projection": projection,
                "sort_tiebreaker": sort_tiebreaker if sort_tiebreaker is not None else 0,
                "sort_edge": abs(safe_float(edge, default=0)),
                "sort_confidence": confidence_rank(confidence),
            }
            key = (player_key, resolved_team.upper(), opponent.upper(), stat_label)
            current = records_by_key.get(key)
            if not current or (
                record["sort_projection"],
                record["sort_tiebreaker"],
            ) > (
                current["sort_projection"],
                current.get("sort_tiebreaker", 0),
            ):
                records_by_key[key] = record

    records = list(records_by_key.values())
    fantasy_rows = load_mlb_fantasy_projection_rows()
    if fantasy_rows:
        records.extend(fantasy_rows)
    records.sort(key=lambda item: (item["sort_projection"], item.get("sort_tiebreaker", 0), item["sort_edge"]), reverse=True)
    return records


def build_mlb_pitcher_projection_board():
    rows = []
    for item in load_mlb_pitcher_board()["records"]:
        rows.append({
            "player": mlb_clean_text(item.get("pitcher_name"), fallback="Pitcher"),
            "team": mlb_clean_text(item.get("team"), fallback=""),
            "opponent": mlb_clean_text(item.get("opponent"), fallback="Matchup pending"),
            "stat": "Strikeouts",
            "projection": safe_float(item.get("projected_ks")),
            "pitcher_k_percent_season": safe_float(item.get("pitcher_k_percent_season")),
            "opponent_hitter_k_percent": safe_float(item.get("opponent_hitter_k_percent")),
            "line": safe_float(item.get("sportsbook_line")),
            "edge": safe_float(item.get("edge")),
            "confidence": confidence_level(item.get("confidence")),
            "lean": normalize_text(item.get("recommended_play")).split(" ")[0] or "Lean",
            "sort_projection": safe_float(item.get("projected_ks"), default=0),
            "sort_edge": abs(safe_float(item.get("edge"), default=0)),
            "sort_confidence": confidence_rank(item.get("confidence")),
        })
        if safe_float(item.get("estimated_innings")) is not None and safe_float(item.get("projected_ks")) is not None:
            rows.append({
                "player": mlb_clean_text(item.get("pitcher_name"), fallback="Pitcher"),
                "team": mlb_clean_text(item.get("team"), fallback=""),
                "opponent": mlb_clean_text(item.get("opponent"), fallback="Matchup pending"),
                "stat": "Outs Recorded",
                "projection": safe_float(item.get("estimated_innings")) * 3,
                "pitcher_k_percent_season": safe_float(item.get("pitcher_k_percent_season")),
                "opponent_hitter_k_percent": safe_float(item.get("opponent_hitter_k_percent")),
                "line": None,
                "edge": None,
                "confidence": confidence_level(item.get("confidence")),
                "lean": "",
                "sort_projection": safe_float(item.get("estimated_innings"), default=0) * 3,
                "sort_edge": 0,
                "sort_confidence": confidence_rank(item.get("confidence")),
            })
    rows.sort(key=lambda item: (item["sort_projection"], item["sort_edge"]), reverse=True)
    return rows


def build_mlb_player_projection_profiles():
    profiles = {}
    source_paths = [MLB_FILES["hitters"], MLB_FILES["pitchers"], MLB_FILES["pitcher_predictions"], MLB_FILES["fantasy"]]

    def get_profile(player, team="", player_type="", opponent="", matchup="", confidence="Model View", source_file=None):
        key = normalize_profile_key(player, team)
        profile = profiles.setdefault(key, {
            "player": normalize_text(player),
            "player_type": player_type,
            "team": normalize_text(team).upper(),
            "opponent": normalize_text(opponent),
            "matchup": normalize_text(matchup, "Matchup pending"),
            "confidence": normalize_text(confidence, "Model View"),
            "hitter_stats": [],
            "pitcher_stats": [],
            "probabilities": [],
        })
        if player_type and player_type not in normalize_text(profile.get("player_type")):
            existing_type = normalize_text(profile.get("player_type"))
            profile["player_type"] = " / ".join([item for item in [existing_type, player_type] if item])
        if not profile.get("opponent") and opponent:
            profile["opponent"] = normalize_text(opponent)
        if profile.get("matchup") == "Matchup pending" and matchup:
            profile["matchup"] = normalize_text(matchup)
        return profile

    hitter_source = MLB_FILES["hitters_full"] if MLB_READER_MODE == "canonical" and MLB_FILES["hitters_full"].exists() else MLB_FILES["hitters"]
    hitters_df = read_csv_df(hitter_source)
    if not hitters_df.empty:
        hitter_col = find_first_column(hitters_df, ["Hitter", "hitter_name", "player_name"])
        team_col = find_first_column(hitters_df, ["Team", "team", "TEAM"])
        opponent_col = find_first_column(hitters_df, ["Opponent", "opponent", "opp", "matchup"])
        pitcher_col = find_first_column(hitters_df, ["Pitcher", "pitcher_name", "matchup_pitcher"])
        hitter_fields = [
            ("Hit Probability", ["Hit Probability", "hit_prob"], "probability"),
            ("2+ Hits Probability", ["blended_hit_2plus_prob_v2", "hit_2plus_prob"], "probability"),
            ("Total Bases Probability", ["Total Bases >= 2", "tb2_prob"], "probability"),
            ("Home Run Probability", ["Home Run Probability", "hr_prob"], "probability"),
            ("RBI Probability", ["RBI Probability", "rbi_prob"], "probability"),
            ("Stolen Base Probability", ["Stolen Base Probability", "sb_prob"], "probability"),
            ("Hitter Strikeout Projection", ["Projected Hitter Strikeouts", "projected_hitter_strikeouts"], "value"),
            ("Hitter Strikeout Probability", ["Hitter Strikeout %", "hitter_strikeout_pct"], "probability"),
            ("Lineup Spot", ["lineup_spot"], "value"),
        ]
        if hitter_col:
            for _, raw in hitters_df.iterrows():
                player = normalize_text(raw.get(hitter_col))
                if not player:
                    continue
                team = mlb_clean_text(raw.get(team_col), fallback="").upper() if team_col else ""
                opponent = mlb_clean_text(raw.get(opponent_col), fallback="") if opponent_col else ""
                pitcher = mlb_clean_text(raw.get(pitcher_col), fallback="") if pitcher_col else ""
                profile = get_profile(player, team, "Hitter", opponent or pitcher, opponent or pitcher or "Matchup pending", source_file=hitter_source)
                for label, columns, kind in hitter_fields:
                    column = find_first_column(hitters_df, columns)
                    if not column:
                        continue
                    append_profile_field(profile["probabilities" if kind == "probability" else "hitter_stats"], label, raw.get(column), kind, column)

    fantasy_df = read_csv_df(MLB_FILES["fantasy"])
    if not fantasy_df.empty:
        player_col = find_first_column(fantasy_df, ["player_name", "hitter_name", "player"])
        team_col = find_first_column(fantasy_df, ["team", "TEAM"])
        opponent_col = find_first_column(fantasy_df, ["opponent", "opp"])
        fantasy_fields = [
            ("Expected Plate Appearances", "expected_pa"),
            ("Fantasy Points", "fantasy_points"),
            ("Fantasy P10", "fantasy_points_p10"),
            ("Fantasy P50", "fantasy_points_p50"),
            ("Fantasy P90", "fantasy_points_p90"),
        ]
        if player_col:
            for _, raw in fantasy_df.iterrows():
                player = normalize_text(raw.get(player_col))
                if not player:
                    continue
                team = mlb_clean_text(raw.get(team_col), fallback="").upper() if team_col else ""
                opponent = mlb_clean_text(raw.get(opponent_col), fallback="") if opponent_col else ""
                profile = get_profile(player, team, "Hitter", opponent, opponent or "Matchup pending", confidence_level(raw.get("confidence")), MLB_FILES["fantasy"])
                for label, column in fantasy_fields:
                    if column in fantasy_df.columns:
                        append_profile_field(profile["hitter_stats"], label, raw.get(column), "value", column)

    pitcher_props_df = read_csv_df(MLB_FILES["pitchers"])
    if not pitcher_props_df.empty:
        pitcher_fields = [
            ("Strikeouts Projection", "projected_strikeouts", "value"),
            ("Outs Projection", "projected_outs", "value"),
            ("Projected IP", "projected_ip", "value"),
            ("Strikeouts P10", "floor_p10", "value"),
            ("Strikeouts P90", "ceiling_p90", "value"),
            ("Outs P10", "outs_floor_p10", "value"),
            ("Outs P90", "outs_ceiling_p90", "value"),
            ("Over 4.5 Strikeouts", "over_4_5_pct", "probability"),
            ("Over 5.5 Strikeouts", "over_5_5_pct", "probability"),
            ("Over 6.5 Strikeouts", "over_6_5_pct", "probability"),
            ("Over 7.5 Strikeouts", "over_7_5_pct", "probability"),
            ("Over 8.5 Strikeouts", "over_8_5_pct", "probability"),
            ("Best Over Probability", "best_over_prob_pct", "probability"),
        ]
        for _, raw in pitcher_props_df.iterrows():
            player = mlb_clean_text(raw.get("pitcher_name"), fallback="")
            if not player:
                continue
            team = mlb_clean_text(raw.get("team"), fallback="").upper()
            opponent = mlb_clean_text(raw.get("opponent"), fallback="")
            profile = get_profile(player, team, "Pitcher", opponent, opponent or "Matchup pending", confidence_level(raw.get("recommendation_confidence")), MLB_FILES["pitchers"])
            for label, column, kind in pitcher_fields:
                if column in pitcher_props_df.columns:
                    append_profile_field(profile["probabilities" if kind == "probability" else "pitcher_stats"], label, raw.get(column), kind, column)

    pitcher_predictions_df = read_csv_df(MLB_FILES["pitcher_predictions"])
    if not pitcher_predictions_df.empty:
        pitcher_col = find_first_column(pitcher_predictions_df, ["Pitcher", "pitcher_name", "player_name"])
        team_col = find_first_column(pitcher_predictions_df, ["Team", "team"])
        opponent_col = find_first_column(pitcher_predictions_df, ["Opponent", "opponent"])
        prediction_fields = [
            ("Model Strikeouts", "Model_Projected_Strikeouts", "value"),
            ("Model Outs", "Model_Projected_Outs", "value"),
            ("Projected IP", "Projected_IP", "value"),
            ("Sim Mean Strikeouts", "Sim_Mean_Strikeouts", "value"),
            ("Sim P10 Strikeouts", "Sim_P10_Strikeouts", "value"),
            ("Sim P90 Strikeouts", "Sim_P90_Strikeouts", "value"),
            ("Sim Mean Outs", "Sim_Mean_Outs", "value"),
            ("Sim P10 Outs", "Sim_P10_Outs", "value"),
            ("Sim P90 Outs", "Sim_P90_Outs", "value"),
            ("Over 4.5 Strikeouts", "Sim_Prob_Over_4_5", "probability"),
            ("Over 5.5 Strikeouts", "Sim_Prob_Over_5_5", "probability"),
            ("Over 6.5 Strikeouts", "Sim_Prob_Over_6_5", "probability"),
            ("Over 7.5 Strikeouts", "Sim_Prob_Over_7_5", "probability"),
            ("Over 8.5 Strikeouts", "Sim_Prob_Over_8_5", "probability"),
            ("Walk Rate", "Pitcher_BB_Pct", "probability"),
        ]
        if pitcher_col:
            for _, raw in pitcher_predictions_df.iterrows():
                player = mlb_clean_text(raw.get(pitcher_col), fallback="")
                if not player:
                    continue
                team = mlb_clean_text(raw.get(team_col), fallback="").upper() if team_col else ""
                opponent = mlb_clean_text(raw.get(opponent_col), fallback="") if opponent_col else ""
                profile = get_profile(player, team, "Pitcher", opponent, opponent or "Matchup pending", source_file=MLB_FILES["pitcher_predictions"])
                for label, column, kind in prediction_fields:
                    if column in pitcher_predictions_df.columns:
                        append_profile_field(profile["probabilities" if kind == "probability" else "pitcher_stats"], label, raw.get(column), kind, column)

    # Backfill from existing board records only when direct files are unavailable.
    for row in [] if profiles else build_mlb_hitter_projection_board():
        player = normalize_text(row.get("player"))
        if not player:
            continue
        profile = get_profile(player, row.get("team"), "Hitter", row.get("opponent"), row.get("opponent"), confidence_level(row.get("confidence")))
        label = normalize_text(row.get("stat")) or "Projection"
        kind = "probability" if label not in {"Hitter Strikeouts", "Fantasy Points"} else "value"
        append_profile_field(profile["probabilities" if kind == "probability" else "hitter_stats"], label, row.get("projection"), kind, label)

    for row in [] if profiles else build_mlb_pitcher_projection_board():
        player = normalize_text(row.get("player"))
        if not player:
            continue
        profile = get_profile(player, row.get("team"), "Pitcher", row.get("opponent"), row.get("opponent"), confidence_level(row.get("confidence")))
        append_profile_field(profile["pitcher_stats"], normalize_text(row.get("stat")) or "Projection", row.get("projection"), "value", row.get("stat"))

    records = []
    for profile in profiles.values():
        for group_key in ("hitter_stats", "pitcher_stats", "probabilities"):
            profile[group_key] = sorted(profile.get(group_key, []), key=lambda item: normalize_text(item.get("label")).lower())
        profile["stats"] = profile["hitter_stats"] + profile["pitcher_stats"]
        profile["stats_object"] = {
            normalize_text(item.get("label")): item.get("value")
            for item in profile["stats"]
            if normalize_text(item.get("label"))
        }
        profile["probabilities_object"] = {
            normalize_text(item.get("label")): item.get("value")
            for item in profile["probabilities"]
            if normalize_text(item.get("label"))
        }
        records.append(profile)
    records = sorted(records, key=lambda item: (item.get("team", ""), item.get("player", "")))
    teams = sorted({item["team"] for item in records if item.get("team")})
    last_updated = max(filter(None, [file_timestamp(path) for path in source_paths]), default=None)
    return {"records": records, "teams": teams, "source_labels": public_data_source_labels(source_paths), "last_updated": last_updated}


def mlb_system_rows():
    return [{"service": "mlb", "status": "available"}]


def clean_nba_best_bets_records(records):
    cleaned = []
    hidden = {"RAW_STAT", "EDGE", "ABS_EDGE", "STDDEV", "BET_CONFIDENCE", "CONFIDENCE_LABEL", "RESULT", "ACTUAL"}
    for row in records:
        cleaned.append({key: value for key, value in row.items() if key not in hidden})
    return cleaned


def latest_graded_nba_history():
    df = read_csv_df(HISTORY_PATH)
    if df.empty:
        return []
    latest = latest_rows_by_date(df, allowed_results_only=True)
    return records_from_df(latest)


def projection_view_records():
    df = read_csv_df(PROJECTIONS_PATH)
    if not df.empty:
        if "TEAM_ABBREVIATION" in df.columns and Path(TEAMS_TODAY_PATH).exists():
            teams_df = read_csv_df(TEAMS_TODAY_PATH)
            team_col = find_first_column(teams_df, ["TEAM_ABBREVIATION", "TEAM"])
            if team_col:
                slate = {normalize_text(team).upper() for team in teams_df[team_col].dropna().tolist()}
                if slate:
                    df = df[df["TEAM_ABBREVIATION"].astype(str).str.upper().isin(slate)].copy()
        return records_from_df(build_projection_app_view(df))
    fallback = read_csv_df(PROJECTIONS_APP_VIEW_PATH)
    return records_from_df(fallback)


def nba_projection_source_df():
    df = read_csv_df(PROJECTIONS_PATH)
    if df.empty:
        return pd.DataFrame()
    work = df.copy()
    if "TEAM_ABBREVIATION" in work.columns and Path(TEAMS_TODAY_PATH).exists():
        teams_df = read_csv_df(TEAMS_TODAY_PATH)
        team_col = find_first_column(teams_df, ["TEAM_ABBREVIATION", "TEAM"])
        if team_col:
            slate = {normalize_text(team).upper() for team in teams_df[team_col].dropna().tolist()}
            if slate:
                work = work[work["TEAM_ABBREVIATION"].astype(str).str.upper().isin(slate)].copy()
    return work.reset_index(drop=True)


def build_nba_line_lookup():
    df = read_csv_df(LINES_PATH)
    if df.empty:
        return {}
    player_col = find_first_column(df, ["PLAYER_NAME", "PLAYER", "player_name"])
    stat_col = find_first_column(df, ["STAT", "stat"])
    line_col = find_first_column(df, ["LINE", "line"])
    if not player_col or not stat_col or not line_col:
        return {}

    work = df.copy()
    board_col = find_first_column(work, ["UPDATED_AT_ET", "BOARD_TIME_ET", "updated_at", "board_time"])
    if board_col:
        work["_board_time"] = pd.to_datetime(work[board_col], errors="coerce")
        work = work.sort_values("_board_time", ascending=False, kind="stable", na_position="last")

    lookup = {}
    for _, raw in work.iterrows():
        player = normalize_text(raw.get(player_col)).lower()
        raw_stat = normalize_text(raw.get(stat_col)).upper()
        stat = NBA_LINE_STAT_MAP.get(raw_stat)
        if not player or not stat:
            continue
        lookup.setdefault((player, stat), safe_float(raw.get(line_col)))
    return lookup


def nba_normal_cdf(value):
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def nba_probability_at_or_above(mean, std, threshold):
    if mean is None or threshold is None:
        return None
    spread = safe_float(std)
    if spread is None or spread <= 0:
        return 1.0 if mean >= threshold else 0.0
    z_score = (threshold - mean) / spread
    probability = 1.0 - nba_normal_cdf(z_score)
    return min(max(probability, 0.0), 1.0)


def nba_threshold_target(stat_config, projection):
    thresholds = stat_config.get("thresholds", [])
    if projection is None or not thresholds:
        return None
    eligible = [value for value in thresholds if value <= projection]
    return eligible[-1] if eligible else thresholds[0]


def nba_threshold_label(stat_config, threshold):
    if threshold is None:
        return "n/a"
    label = stat_config["label"].lower()
    threshold_text = metric_label(threshold, digits=0 if float(threshold).is_integer() else 1)
    return f"{threshold_text}+ {label}"


def nba_rotation_label(value):
    text = normalize_text(value).strip().upper()
    return text.title() if text else "Rotation"


def nba_recent_minutes_delta(projected_minutes, last_five_minutes):
    if projected_minutes is None or last_five_minutes is None:
        return None
    return round(projected_minutes - last_five_minutes, 1)


def build_nba_projection_records():
    df = nba_projection_source_df()
    if df.empty:
        return []

    line_lookup = build_nba_line_lookup()
    records = []

    for _, raw in df.iterrows():
        player = normalize_text(raw.get("PLAYER_NAME"))
        team = normalize_text(raw.get("TEAM_ABBREVIATION")).upper()
        opponent = normalize_text(raw.get("OPPONENT")).upper()
        matchup = normalize_text(raw.get("MATCHUP"), default=f"{team} vs. {opponent}" if team and opponent else "Matchup pending")
        confidence = confidence_level(raw.get("CONFIDENCE_LABEL") or raw.get("MODEL_CONFIDENCE") or raw.get("BET_CONFIDENCE") or raw.get("CONFIDENCE"))
        confidence_score = safe_float(raw.get("CONFIDENCE") or raw.get("BET_CONFIDENCE"))
        active_probability = safe_float(raw.get("ACTIVE_PROB"))
        expected_minutes = safe_float(raw.get("MIN_PROJ") or raw.get("PRED_MIN"))
        last_five_minutes = safe_float(raw.get("AVG_MIN_LAST_5"))
        last_ten_minutes = safe_float(raw.get("AVG_MIN_LAST_10"))
        fantasy_projection = safe_float(raw.get("FANTASY_PROJ"))
        pace = safe_float(raw.get("EXPECTED_PACE"))
        pace_multiplier = safe_float(raw.get("PACE_MULTIPLIER"))
        margin = safe_float(raw.get("EXPECTED_TEAM_MARGIN"))
        blowout_risk = safe_float(raw.get("BLOWOUT_RISK"))
        market_total = safe_float(raw.get("MARKET_TOTAL"))
        injury_status = normalize_text(raw.get("INJURY_STATUS"), default="Active")
        rotation_tier = nba_rotation_label(raw.get("ROTATION_TIER"))
        injury_impact = safe_float(raw.get("TEAM_INJURY_IMPACT"))
        player_key = player.lower()

        for stat_config in NBA_STAT_CONFIGS:
            projection = safe_float(raw.get(stat_config["projection"]))
            if projection is None:
                continue
            median = safe_float(raw.get(stat_config["median"]), default=projection)
            floor = safe_float(raw.get(stat_config["floor"]))
            ceiling = safe_float(raw.get(stat_config["ceiling"]))
            std = safe_float(raw.get(stat_config["std"]))
            threshold = nba_threshold_target(stat_config, projection)
            probability = nba_probability_at_or_above(median or projection, std, threshold)
            line_value = line_lookup.get((player_key, stat_config["key"]))
            line_delta = round(projection - line_value, 2) if line_value is not None else None
            recent_minutes_delta = nba_recent_minutes_delta(expected_minutes, last_five_minutes)

            records.append({
                "player": player,
                "team": team,
                "opponent": opponent,
                "matchup": matchup,
                "confidence": confidence,
                "confidence_score": confidence_score,
                "confidence_rank": confidence_rank(confidence),
                "active_probability": active_probability,
                "injury_status": injury_status,
                "rotation_tier": rotation_tier,
                "pace": pace,
                "pace_multiplier": pace_multiplier,
                "expected_margin": margin,
                "blowout_risk": blowout_risk,
                "market_total": market_total,
                "team_injury_impact": injury_impact,
                "expected_minutes": expected_minutes,
                "last_five_minutes": last_five_minutes,
                "last_ten_minutes": last_ten_minutes,
                "recent_minutes_delta": recent_minutes_delta,
                "stat_key": stat_config["key"],
                "stat_label": stat_config["label"],
                "projection": projection,
                "median_projection": median,
                "floor_projection": floor,
                "ceiling_projection": ceiling,
                "range_display": f"{metric_label(floor)}-{metric_label(ceiling)}" if floor is not None and ceiling is not None else "n/a",
                "distribution_std": std,
                "fantasy_projection": fantasy_projection,
                "threshold": threshold,
                "threshold_label": nba_threshold_label(stat_config, threshold),
                "threshold_probability": probability,
                "sportsbook_line": line_value,
                "sportsbook_delta": line_delta,
                "sort_projection": projection,
                "sort_probability": probability if probability is not None else -1,
                "sort_minutes": expected_minutes if expected_minutes is not None else -1,
            })

    records.sort(
        key=lambda item: (
            item["sort_projection"],
            item["sort_probability"],
            item["sort_minutes"],
            item["player"],
        ),
        reverse=True,
    )
    return records


def build_nba_projection_snapshot(records, stat_keys=None, limit=3):
    if not records:
        return []
    snapshot = []
    desired_stats = stat_keys or NBA_HOME_SNAPSHOT_STATS
    for stat_key in desired_stats:
        stat_rows = [row for row in records if row["stat_key"] == stat_key]
        if not stat_rows:
            continue
        leaders = sorted(
            stat_rows,
            key=lambda item: (
                item["projection"] if item["projection"] is not None else -1,
                item["threshold_probability"] if item["threshold_probability"] is not None else -1,
            ),
            reverse=True,
        )[:limit]
        snapshot.append({"stat_key": stat_key, "stat_label": leaders[0]["stat_label"], "leaders": leaders})
    return snapshot


def build_nba_player_projection_profiles():
    df = read_csv_df(PROJECTIONS_PATH)
    source_path = Path(PROJECTIONS_PATH)
    if df.empty:
        return {"records": [], "teams": [], "source_label": public_data_source_label(source_path), "last_updated": file_timestamp(source_path)}

    profiles = {}
    projection_columns = [
        column for column in df.columns
        if column.endswith("_PROJ") or column.startswith("PRED_") or (
            column.startswith("SIM_") and any(column.endswith(suffix) for suffix in ("_P10", "_P50", "_P90", "_STD"))
        )
    ]
    probability_columns = [column for column in df.columns if column.endswith("_PROB") or column in {"ACTIVE_PROB", "BLOWOUT_RISK"}]
    confidence_columns = [column for column in ["CONFIDENCE_LABEL", "CONFIDENCE", "BET_CONFIDENCE", "MODEL_CONFIDENCE"] if column in df.columns]

    for _, raw in df.iterrows():
        player = normalize_text(raw.get("PLAYER_NAME"))
        if not player:
            continue
        team = normalize_text(raw.get("TEAM_ABBREVIATION")).upper()
        opponent = normalize_text(raw.get("OPPONENT")).upper()
        key = normalize_profile_key(player, team)
        profile = profiles.setdefault(key, {
            "player": player,
            "team": team,
            "opponent": opponent,
            "matchup": normalize_text(raw.get("MATCHUP"), default=f"{team} vs {opponent}" if team and opponent else "Matchup pending"),
            "confidence": confidence_level(raw.get("CONFIDENCE_LABEL") or raw.get("MODEL_CONFIDENCE") or raw.get("BET_CONFIDENCE") or raw.get("CONFIDENCE")),
            "stats": [],
            "probabilities": [],
            "confidence_fields": [],
        })
        for column in projection_columns:
            append_profile_field(profile["stats"], projection_display_label(column), raw.get(column), "value", column)
        for column in probability_columns:
            append_profile_field(profile["probabilities"], projection_display_label(column), raw.get(column), "probability", column)
        for column in confidence_columns:
            append_profile_field(profile["confidence_fields"], projection_display_label(column), raw.get(column), "value", column)

    records = finalize_player_profiles(profiles)
    teams = sorted({item["team"] for item in records if item.get("team")})
    return {"records": records, "teams": teams, "source_label": public_data_source_label(source_path), "last_updated": file_timestamp(source_path)}


def build_nba_best_bets_board():
    df = read_csv_df(BEST_BETS_OUTPUT_PATH)
    source_path = Path(BEST_BETS_OUTPUT_PATH)
    using_fallback = False

    if df.empty and Path(HISTORY_PATH).exists():
        history = read_csv_df(HISTORY_PATH)
        if not history.empty:
            latest = latest_rows_by_date(history, allowed_results_only=False)
            if not latest.empty:
                df = latest.copy()
                using_fallback = True
                source_path = Path(HISTORY_PATH)

    if df.empty:
        return {
            "records": [],
            "source_label": public_data_source_label(source_path),
            "last_updated": file_timestamp(source_path),
            "plays_shown": 0,
            "recent_hit_rate": None,
            "banner": "",
        }

    work = df.copy()
    if "ABS_EDGE" in work.columns:
        work["ABS_EDGE_SORT"] = pd.to_numeric(work["ABS_EDGE"], errors="coerce").fillna(0)
    else:
        work["ABS_EDGE_SORT"] = 0
    if "BET_CONFIDENCE" in work.columns:
        work["BET_CONFIDENCE_SORT"] = pd.to_numeric(work["BET_CONFIDENCE"], errors="coerce").fillna(0)
    else:
        work["BET_CONFIDENCE_SORT"] = 0
    work = work.sort_values(["BET_CONFIDENCE_SORT", "ABS_EDGE_SORT"], ascending=[False, False], kind="stable")

    rows = []
    for _, raw in work.iterrows():
        rows.append({
            "date": normalize_text(raw.get("DATE") or raw.get("date")),
            "player": normalize_text(raw.get("PLAYER") or raw.get("player")),
            "team": normalize_text(raw.get("TEAM") or raw.get("team")).upper(),
            "matchup": normalize_text(raw.get("MATCHUP") or raw.get("matchup")),
            "stat": normalize_text(raw.get("RAW_STAT") or raw.get("STAT") or raw.get("raw_stat") or raw.get("stat")),
            "bet": normalize_text(raw.get("BET") or raw.get("bet")),
            "line": safe_float(raw.get("LINE") if raw.get("LINE") is not None else raw.get("line")),
            "projection": safe_float(raw.get("PROJECTION") if raw.get("PROJECTION") is not None else raw.get("projection")),
            "edge": safe_float(raw.get("EDGE") if raw.get("EDGE") is not None else raw.get("edge")),
            "hit_rate": safe_float(raw.get("HIT_RATE") if raw.get("HIT_RATE") is not None else raw.get("hit_rate")),
            "confidence": confidence_level(raw.get("CONFIDENCE_LABEL") or raw.get("MODEL_CONFIDENCE") or raw.get("BET_CONFIDENCE") or raw.get("confidence_label")),
            "confidence_score": safe_float(raw.get("BET_CONFIDENCE")),
            "result": grade_result_label(raw.get("RESULT")) or "Pending",
        })

    history = read_csv_df(HISTORY_PATH)
    graded = history[history["result"].astype(str).str.upper().isin({"WIN", "LOSS"})].copy() if not history.empty and "result" in history.columns else pd.DataFrame()
    recent_hit_rate = None
    if not graded.empty:
        recent = graded.tail(min(len(graded), 15))
        wins = int((recent["result"].astype(str).str.upper() == "WIN").sum())
        total = int(recent["result"].astype(str).str.upper().isin({"WIN", "LOSS"}).sum())
        recent_hit_rate = (wins / total) if total else None

    return {
        "records": rows,
        "source_label": public_data_source_label(source_path),
        "last_updated": file_timestamp(source_path),
        "plays_shown": len(rows),
        "recent_hit_rate": recent_hit_rate,
        "banner": "Showing the latest available published top-play board." if using_fallback else "",
    }


def summarize_nba_window(history_df, days):
    if history_df.empty or "date" not in history_df.columns or "result" not in history_df.columns:
        return {"record": "0-0", "win_rate": None}
    cutoff = today_et() - timedelta(days=days - 1)
    work = history_df.copy()
    work["parsed_date"] = pd.to_datetime(work["date"], errors="coerce").dt.date
    work = work[work["parsed_date"].notna() & (work["parsed_date"] >= cutoff)]
    graded = work[work["result"].astype(str).str.upper().isin({"WIN", "LOSS"})].copy()
    wins = int((graded["result"].astype(str).str.upper() == "WIN").sum())
    losses = int((graded["result"].astype(str).str.upper() == "LOSS").sum())
    total = wins + losses
    return {
        "record": f"{wins}-{losses}",
        "win_rate": (wins / total) if total else None,
    }


def build_nba_record_board():
    history = read_csv_df(HISTORY_PATH)
    daily = read_csv_df(RECORD_SUMMARY_PATH)
    graded = history[history["result"].astype(str).str.upper().isin({"WIN", "LOSS", "PUSH"})].copy() if not history.empty and "result" in history.columns else pd.DataFrame()

    wins = int((graded["result"].astype(str).str.upper() == "WIN").sum()) if not graded.empty else 0
    losses = int((graded["result"].astype(str).str.upper() == "LOSS").sum()) if not graded.empty else 0
    pushes = int((graded["result"].astype(str).str.upper() == "PUSH").sum()) if not graded.empty else 0
    decisive_total = wins + losses
    recent7 = summarize_nba_window(history, 7)
    recent14 = summarize_nba_window(history, 14)
    recent30 = summarize_nba_window(history, 30)

    daily_rows = []
    if not daily.empty:
        work = daily.copy()
        work["parsed_date"] = pd.to_datetime(work["date"], errors="coerce")
        work = work.sort_values("parsed_date", ascending=False, kind="stable")
        for _, raw in work.iterrows():
            wins_value = safe_int(raw.get("wins") if raw.get("wins") is not None else raw.get("WIN"))
            losses_value = safe_int(raw.get("losses") if raw.get("losses") is not None else raw.get("LOSS"))
            total_value = safe_int(raw.get("total"), default=wins_value + losses_value)
            daily_rows.append({
                "date": normalize_text(raw.get("date")),
                "wins": wins_value,
                "losses": losses_value,
                "total": total_value,
                "win_rate": safe_float(raw.get("win_pct")),
            })

    recent_results = []
    if not graded.empty:
        work = graded.copy()
        work["parsed_date"] = pd.to_datetime(work["date"], errors="coerce")
        work = work.sort_values(["parsed_date"], ascending=False, kind="stable")
        for _, raw in work.head(12).iterrows():
            recent_results.append({
                "date": normalize_text(raw.get("date")),
                "player": normalize_text(raw.get("player")),
                "team": normalize_text(raw.get("team")).upper(),
                "stat": normalize_text(raw.get("raw_stat") or raw.get("stat")),
                "bet": normalize_text(raw.get("bet")),
                "projection": safe_float(raw.get("projection")),
                "actual": safe_float(raw.get("actual")),
                "result": grade_result_label(raw.get("result")),
            })

    last_updated = max(filter(None, [file_timestamp(HISTORY_PATH), file_timestamp(RECORD_SUMMARY_PATH)]), default=None)
    return {
        "summary": {
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "win_rate": (wins / decisive_total) if decisive_total else None,
            "recent7": recent7,
            "recent14": recent14,
            "recent30": recent30,
        },
        "records": daily_rows,
        "recent_results": recent_results,
        "source_label": public_data_source_label(RECORD_SUMMARY_PATH),
        "last_updated": last_updated,
        "plays_tracked": len(graded),
    }


def read_nba_summary():
    best_bets = records_from_df(read_csv_df(BEST_BETS_OUTPUT_PATH))
    projections = build_nba_projection_records()
    record = read_csv_df(RECORD_SUMMARY_PATH)
    latest_record = records_from_df(record.tail(1))
    return {
        "best_bets_count": len(best_bets),
        "projections_count": len(projections),
        "record_days": len(record),
        "latest_record": latest_record[0] if latest_record else {},
    }


def read_ufc_summary():
    payload = read_json(UFC_PAGE_SPECS["fights"]["path"])
    fights = payload.get("fights", []) if isinstance(payload, dict) else []
    event = payload.get("event", {}) if isinstance(payload, dict) else {}
    props = read_csv_df(UFC_PAGE_SPECS["props"]["path"])
    top_pick = fights[0].get("predicted_winner", "n/a") if fights else "n/a"
    top_confidence = fights[0].get("predicted_winner_pct", "n/a") if fights else "n/a"
    return {
        "event_name": event.get("name", "n/a"),
        "fight_count": len(fights),
        "top_pick": top_pick,
        "top_confidence": top_confidence,
        "props_count": len(props),
    }


def render_ufc_finish_breakdown(fight):
    method_probabilities = fight.get("method_probabilities") if isinstance(fight, dict) else {}
    if not isinstance(method_probabilities, dict):
        method_probabilities = {}

    items = [
        ("Decision", method_probabilities.get("decision_pct")),
        ("KO / TKO", method_probabilities.get("ko_tko_pct")),
        ("Submission", method_probabilities.get("submission_pct")),
        ("Inside Distance", method_probabilities.get("inside_distance_pct")),
    ]
    cells = []
    for label, value in items:
        if safe_float(value) is None:
            continue
        cells.append(
            "<div class='ufc-finish-cell'>"
            f"<span>{escape(label)}</span>"
            f"<strong>{escape(pct_label(value))}</strong>"
            "</div>"
        )

    if not cells:
        return ""

    return (
        "<div class='ufc-finish-block'>"
        "<div class='ufc-finish-title'>How The Fight Ends</div>"
        "<div class='ufc-finish-grid'>"
        + "".join(cells)
        + "</div></div>"
    )


def read_mlb_summary():
    best_bets = load_mlb_best_bets()
    pitchers = load_mlb_pitcher_board()
    history = load_mlb_history_board()
    record = load_mlb_record_board()
    return {
        "best_bets_count": best_bets["plays_shown"],
        "pitcher_count": pitchers["plays_shown"],
        "history_count": history["plays_shown"],
        "record_summary": record["summary"],
    }


def pga_available_rounds():
    publish_state = read_json(PGA_PUBLISH_STATE_PATH)
    rounds = publish_state.get("available_rounds", [])
    if isinstance(rounds, list):
        return sorted({round_number for round_number in (safe_int(value) for value in rounds) if round_number})
    return []


def pga_published_round():
    publish_state = read_json(PGA_PUBLISH_STATE_PATH)
    return safe_int(publish_state.get("selected_round"), default=0) or None


def normalize_pga_best_bet_record(item, fallback_round=None):
    prop_type_raw = normalize_text(item.get("prop_type")).strip()
    prop_type_key = prop_type_raw.lower().replace(" ", "_")
    line_value = safe_float(item.get("line_value"))
    sim_value = safe_float(item.get("sim_value"))
    confidence = safe_float(item.get("confidence"))
    payout = safe_float(item.get("payout"))
    if prop_type_key in PGA_INVALID_PROP_TYPES:
        return None
    if line_value is None or sim_value is None or confidence is None or payout is None:
        return None
    round_value = safe_int(item.get("round_number"), default=fallback_round or 0) or fallback_round
    return {
        "golfer_name": normalize_text(item.get("golfer_name")),
        "prop_type": prop_type_raw.replace("_", " ").title(),
        "bet_direction": normalize_text(item.get("bet_direction")).title(),
        "line_value": line_value,
        "sim_value": sim_value,
        "confidence": confidence,
        "payout": payout,
        "round_number": round_value,
    }


def normalize_pga_available_prop(item, fallback_round=None):
    prop_type_raw = normalize_text(item.get("prop_type")).strip()
    prop_type_key = prop_type_raw.lower().replace(" ", "_")
    if prop_type_key in PGA_INVALID_PROP_TYPES:
        return None
    line_value = safe_float(item.get("line_value"))
    over_payout = safe_float(item.get("over_payout"))
    under_payout = safe_float(item.get("under_payout"))
    if line_value is None:
        return None
    return {
        "golfer_name": normalize_text(item.get("golfer_name")),
        "prop_type": prop_type_raw.replace("_", " ").title(),
        "bet_direction": normalize_text(item.get("bet_direction")) or "Available",
        "line_value": line_value,
        "sim_value": None,
        "confidence": None,
        "payout": None,
        "over_payout": over_payout,
        "under_payout": under_payout,
        "round_number": safe_int(item.get("round_number"), default=fallback_round or 0) or fallback_round,
        "is_available_prop": True,
    }


def load_pga_available_props(round_number=None):
    if not PGA_PROCESSED_ODDS_DIR.exists():
        return []
    leaderboard_df = read_csv_df(PGA_RESULTS_PATH)
    if leaderboard_df.empty:
        return []
    sim_lookup = {}
    for _, raw in leaderboard_df.iterrows():
        golfer_name = normalize_text(raw.get("golfer_name"))
        if not golfer_name:
            continue
        sim_lookup[golfer_name.lower()] = {
            "avg_round_score": safe_float(raw.get("avg_round_score")),
            "avg_birdies": safe_float(raw.get("avg_birdies")),
        }
    candidates = []
    if round_number is not None:
        candidates.extend(sorted(PGA_PROCESSED_ODDS_DIR.glob(f"pga_props_*_R{round_number}.json")))
    candidates.extend(sorted(PGA_PROCESSED_ODDS_DIR.glob("pga_props_*.json")))
    seen_paths = set()
    for path in reversed(candidates):
        if path in seen_paths:
            continue
        seen_paths.add(path)
        payload = read_json(path)
        prop_bets = payload.get("prop_bets", []) if isinstance(payload, dict) else []
        records = []
        for item in prop_bets:
            record = normalize_pga_available_prop(item, fallback_round=round_number)
            if not record:
                continue
            sim_data = sim_lookup.get(normalize_text(record.get("golfer_name")).lower(), {})
            prop_type = normalize_text(record.get("prop_type")).lower()
            sim_value = None
            if prop_type == "Total Score".lower():
                avg_round_score = sim_data.get("avg_round_score")
                sim_value = avg_round_score + 72 if avg_round_score is not None else None
            elif prop_type == "Birdies Or Better".lower():
                sim_value = sim_data.get("avg_birdies")
            if sim_value is None:
                continue
            edge = round(sim_value - record["line_value"], 2)
            direction = "Over" if edge > 0 else "Under"
            confidence_score = abs(edge)
            confidence = "High" if confidence_score >= 1.0 else "Medium" if confidence_score >= 0.5 else "Low"
            records.append({
                "prop": f"{record['golfer_name']} {direction} {metric_label(record['line_value'])} {record['prop_type']}",
                "confidence": confidence,
                "_confidence_score": confidence_score,
                "_prop": record["prop_type"],
            })
        if records:
            records.sort(key=lambda item: (item["_confidence_score"], item["prop"]), reverse=True)
            return records[:20]
    return []


def load_pga_best_bets(round_number=None, round_only=False):
    available_rounds = pga_available_rounds()
    published_round = pga_published_round()
    selected_round = round_number if round_number in available_rounds else published_round
    payload = read_json(PGA_PUBLISHED_BEST_BETS_PATH)

    if isinstance(payload, list) and payload:
        records = [record for record in (normalize_pga_best_bet_record(item, fallback_round=published_round) for item in payload) if record]
        if records:
            return {
                "records": records,
                "source_label": public_data_source_label(PGA_PUBLISHED_BEST_BETS_PATH),
                "last_updated": file_timestamp(PGA_PUBLISHED_BEST_BETS_PATH),
                "selected_round": published_round,
                "is_round_specific": published_round is not None,
                "is_available_props": False,
            }

    empty_source_label = public_data_source_label(PGA_PUBLISHED_BEST_BETS_PATH)
    fallback_props = load_pga_available_props(selected_round)
    if fallback_props:
        return {
            "records": fallback_props,
            "source_label": empty_source_label,
            "last_updated": None,
            "selected_round": selected_round,
            "is_round_specific": False,
            "is_available_props": True,
        }
    return {
        "records": [],
        "source_label": empty_source_label,
        "last_updated": None,
        "selected_round": selected_round,
        "is_round_specific": False,
        "is_available_props": False,
    }


def load_pga_leaderboard():
    df = read_csv_df(PGA_RESULTS_PATH)
    if df.empty:
        return {"records": [], "source_label": public_data_source_label(PGA_RESULTS_PATH), "last_updated": file_timestamp(PGA_RESULTS_PATH)}

    work = df.copy()
    sort_col = "win_perc" if "win_perc" in work.columns else work.columns[0]
    if sort_col in work.columns:
        work = work.sort_values(sort_col, ascending=False, kind="stable")

    records = []
    for _, raw in work.head(20).iterrows():
        row = raw.to_dict()
        records.append({
            "golfer_name": normalize_text(row.get("golfer_name")),
            "win_perc": safe_float(row.get("win_perc")),
            "top5_perc": safe_float(row.get("top5_perc")),
            "top10_perc": safe_float(row.get("top10_perc")),
            "made_cut_perc": safe_float(row.get("made_cut_perc")),
            "avg_round_score": safe_float(row.get("avg_round_score")),
            "avg_birdies": safe_float(row.get("avg_birdies")),
        })
    return {
        "records": records,
        "source_label": public_data_source_label(PGA_RESULTS_PATH),
        "last_updated": file_timestamp(PGA_RESULTS_PATH),
    }


def build_pga_player_projection_profiles():
    leaderboard = load_pga_leaderboard()
    metadata = read_json(PGA_TOURNAMENT_METADATA_PATH)
    profiles = {}
    for row in leaderboard.get("records", []):
        golfer = normalize_text(row.get("golfer_name"))
        if not golfer:
            continue
        profile = profiles.setdefault(normalize_profile_key(golfer), {
            "player": golfer,
            "player_type": "Golfer",
            "team": "",
            "opponent": "",
            "matchup": normalize_text(metadata.get("tournament_name"), "Current tournament"),
            "confidence": "Model View",
            "stats": [],
            "probabilities": [],
            "confidence_fields": [],
        })
        for label, key, kind in [
            ("Win Probability", "win_perc", "probability"),
            ("Top 5 Probability", "top5_perc", "probability"),
            ("Top 10 Probability", "top10_perc", "probability"),
            ("Made Cut Probability", "made_cut_perc", "probability"),
            ("Average Round Score", "avg_round_score", "value"),
            ("Average Birdies", "avg_birdies", "value"),
        ]:
            append_profile_field(profile["probabilities" if kind == "probability" else "stats"], label, row.get(key), kind, key)
    records = finalize_player_profiles(profiles)
    return {
        "records": records,
        "teams": [],
        "source_label": leaderboard.get("source_label"),
        "last_updated": leaderboard.get("last_updated"),
    }


def load_pga_summary(round_number=None):
    metadata = read_json(PGA_TOURNAMENT_METADATA_PATH)
    config = read_json(PGA_CONFIG_PATH)
    available_rounds = pga_available_rounds()
    current_round = pga_published_round()
    selected_round = round_number if round_number in available_rounds else current_round
    best_bets = load_pga_best_bets(selected_round)
    round_best_bets = load_pga_best_bets(selected_round, round_only=True)
    leaderboard = load_pga_leaderboard()
    favorite = leaderboard["records"][0] if leaderboard["records"] else {}
    top_bet = round_best_bets["records"][0] if round_best_bets["records"] else (best_bets["records"][0] if best_bets["records"] else {})
    return {
        "tournament_name": metadata.get("tournament_name") or "PGA Dashboard",
        "start_date": metadata.get("start_date"),
        "end_date": metadata.get("end_date"),
        "simulation_mode": normalize_text(config.get("simulation_mode")).replace("_", " ").title() or "Tournament Level",
        "simulations_run": safe_int(config.get("num_simulations"), default=0),
        "best_bets": best_bets,
        "round_best_bets": round_best_bets,
        "leaderboard": leaderboard,
        "available_rounds": available_rounds,
        "selected_round": selected_round,
        "current_round": current_round,
        "favorite": favorite,
        "top_bet": top_bet,
    }


def pga_system_status():
    return {"ok": True, "service": "pga", "status": "available"}


def render_root_nav(active_path):
    items = []
    for label, href in ROOT_NAV_ITEMS:
        css = "top-link active" if href == active_path or (href != "/" and active_path.startswith(href)) else "top-link"
        items.append(f"<a class='{css}' href='{href}'>{escape(label)}</a>")
    return "<div class='top-links'>" + "".join(items) + "</div>"


def render_footer():
    year = now_et().year
    return (
        "<footer class='site-footer'>"
        "<div class='footer-shell'>"
        "<div class='footer-brand'>"
        "<img class='footer-logo' src='/brand/logo.png' alt='EdgeRanked SportsAI logo'>"
        "<div><span>EdgeRanked<span class='brand-accent'>AI</span></span><div class='footer-note'>Institutional-grade sports intelligence and probability modeling.</div></div>"
        "</div>"
        "<div class='footer-links'>"
        "<div class='footer-col'>"
        "<h4>Platform</h4>"
        "<a href='/nba'>NBA</a>"
        "<a href='/mlb'>MLB</a>"
        "<a href='/wnba'>WNBA</a>"
        "<a href='/pga'>PGA</a>"
        "<a href='/ufc'>UFC</a>"
        "</div>"
        "<div class='footer-col'>"
        "<h4>Resources</h4>"
        "<a href='/about'>About</a>"
        "</div>"
        "<div class='footer-col'>"
        "<h4>Legal</h4>"
        "<a href='/privacy-policy'>Privacy Policy</a>"
        "<a href='/terms'>Terms of Use</a>"
        "<a href='/disclaimer'>Disclaimer</a>"
        "</div>"
        "</div>"
        "<div class='footer-meta'>"
        f"<p class='footer-copy'>&copy; {year} EdgeRanked. All rights reserved.</p>"
        f"<p class='footer-copy'>For educational and entertainment purposes only. Not financial, gambling, or legal advice.</p>"
        "</div>"
        "</div>"
        "</footer>"
    )


def render_subnav(items, active_path):
    links = []
    for label, href in items:
        css = "sub-link active" if href == active_path else "sub-link"
        links.append(f"<a class='{css}' href='{href}'>{escape(label)}</a>")
    return "<div class='sub-links'>" + "".join(links) + "</div>"


def render_mlb_nav(active_path):
    primary = render_subnav(MLB_PRIMARY_NAV, active_path if active_path in dict(MLB_PRIMARY_NAV).values() else "/mlb/projections" if active_path in MLB_HITTER_ROUTES else active_path)
    if active_path in MLB_HITTER_ROUTES:
        return primary + render_subnav(MLB_HITTER_NAV, active_path)
    return primary


def render_stat_cards(cards, compact=False):
    css = "metric-grid compact" if compact else "metric-grid"
    body = []
    for label, value, caption in cards:
        body.append(
            "<article class='metric-card'>"
            f"<div class='metric-label'>{escape(str(label))}</div>"
            f"<div class='metric-value'>{escape(str(value))}</div>"
            f"<p class='metric-caption'>{escape(str(caption))}</p>"
            "</article>"
        )
    return f"<div class='{css}'>" + "".join(body) + "</div>"


def render_page_actions(actions):
    links = []
    for label, href, style in actions:
        links.append(f"<a class='cta-btn {style}' href='{href}'>{escape(label)}</a>")
    return "<div class='cta-row'>" + "".join(links) + "</div>"


def render_empty_state(title, message, detail):
    return (
        "<section class='panel empty-panel'>"
        f"<div class='eyebrow'>{escape(title)}</div>"
        f"<h2>{escape(message)}</h2>"
        f"<p class='muted'>{escape(detail)}</p>"
        "</section>"
    )


def render_banner(text):
    if not text:
        return ""
    return f"<section class='notice-banner'>{escape(text)}</section>"


def render_badge(value, kind="confidence"):
    label = normalize_text(value) or "n/a"
    if kind == "confidence":
        tier = confidence_level(label).lower()
    elif kind == "result":
        tier = normalize_text(value).lower() or "neutral"
        if tier not in {"win", "loss", "push", "pending"}:
            tier = "neutral"
    else:
        tier = "neutral"
    return f"<span class='badge badge-{tier}'>{escape(label)}</span>"


def format_cell(value, fmt):
    if fmt == "badge":
        return render_badge(value, "confidence")
    if fmt == "result":
        return render_badge(value, "result")
    if fmt == "pct":
        return escape(pct_label(value))
    if fmt == "num":
        return escape(metric_label(value))
    if fmt == "int":
        return escape(str(safe_int(value)))
    return escape(normalize_text(value) or "n/a")


def render_data_table(title, subtitle, rows, columns, empty_message, empty_detail):
    if not rows:
        return render_empty_state(title, empty_message, empty_detail)

    header = "".join(f"<th>{escape(label)}</th>" for label, _, _ in columns)
    body_rows = []
    for row in rows:
        cells = []
        for label, key, fmt in columns:
            rendered = format_cell(row.get(key), fmt)
            cells.append(f"<td data-label='{escape(label)}'>{rendered}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    subtitle_html = f"<p class='muted'>{escape(subtitle)}</p>" if subtitle else ""
    return (
        "<section class='panel'>"
        f"<div class='panel-head'><h2>{escape(title)}</h2>{subtitle_html}</div>"
        "<div class='table-shell'><table><thead><tr>"
        f"{header}"
        "</tr></thead><tbody>"
        f"{''.join(body_rows)}"
        "</tbody></table></div></section>"
    )


def render_meta_strip(meta):
    return ""


def render_mlb_top_play_cards(rows):
    if not rows:
        return render_empty_state(
            "Top Plays Today",
            "No plays are currently available.",
            "Today's board is still being generated. Check back shortly.",
        )
    cards = []
    for row in rows:
        cards.append(
            "<article class='play-card'>"
            f"<div class='play-top'><div><div class='play-name'>{escape(row['player'])}</div><div class='play-sub'>{escape(row['team'])} vs {escape(row['opponent'])}</div></div>{render_badge(row['confidence'])}</div>"
            f"<div class='play-grid'>"
            f"<div><span>Stat</span><strong>{escape(row['stat_type'])}</strong></div>"
            f"<div><span>Line</span><strong>{escape(metric_label(row['sportsbook_line']))}</strong></div>"
            f"<div><span>Projection</span><strong>{escape(metric_label(row['projection']))}</strong></div>"
            f"<div><span>Play</span><strong>{escape(row['recommended_play'])}</strong></div>"
            "</div>"
            f"<p class='muted'>{escape(row['reason'])}</p>"
            "</article>"
        )
    return "<section class='panel'><div class='panel-head'><div><div class='eyebrow'>Top Plays Today</div><h2>Premium MLB board</h2></div><p class='muted'>The strongest current MLB edges ranked by model confidence and edge strength.</p></div><div class='play-grid-shell'>" + "".join(cards) + "</div></section>"


def render_home_mlb_featured_panel(rows):
    featured_rows = rows[:3]
    if not featured_rows:
        featured_rows = [
            {"player": "Aaron Civale", "recommended_play": "Strikeouts Over 4.5", "projection": 6.2, "edge": 1.7, "confidence": "High"},
            {"player": "Taylor Ward", "recommended_play": "Hits Over 0.5", "projection": 1.1, "edge": 0.6, "confidence": "Medium"},
        ]
    cards = []
    for row in featured_rows:
        cards.append(
            "<article class='play-card'>"
            f"<div class='play-name'>{escape(normalize_text(row.get('player')))} - {escape(normalize_text(row.get('recommended_play')))}</div>"
            "<div class='play-grid'>"
            f"<div><span>Projection</span><strong>{escape(metric_label(row.get('projection')))}</strong></div>"
            f"<div><span>Edge</span><strong>{escape(metric_label(row.get('edge')))}</strong></div>"
            f"<div><span>Confidence</span><strong>{escape(normalize_text(row.get('confidence')) or 'n/a')}</strong></div>"
            "</div>"
            "</article>"
        )
    return (
        "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>MLB Featured</div><h2>Today\u2019s Top MLB Edges</h2></div>"
        "<p class='muted'>Highest-confidence plays from today\u2019s MLB board</p></div>"
        "<div class='play-grid-shell'>"
        + "".join(cards)
        + "</div>"
        "<div class='cta-row'><a class='cta-btn secondary' href='/mlb/best-bets'>View Full MLB Board &rarr;</a></div>"
        "</section>"
    )


def render_mlb_confidence_badge(value):
    tier = confidence_level(value)
    label = {"High": "Elite", "Medium": "Strong", "Low": "Live"}.get(tier, "Live")
    return f"<span class='badge mlb-confidence-badge badge-{tier.lower()}'>{escape(label)}</span>"


def render_mlb_projection_table(title, subtitle, rows, scope_id, entity_label="Player", include_lean=True, include_search=False, extra_columns=None, initial_limit=30, default_stat=None, min_team_rows=3):
    if not rows:
        return render_empty_state(
            title,
            f"No {title.lower()} are currently available.",
            "The latest MLB projection files are still being generated. Check back shortly.",
        )
    extra_columns = extra_columns or []

    body_rows = []
    for row in rows:
        player = normalize_text(row.get("player"))
        team = normalize_text(row.get("team")).upper()
        team_key = "".join(ch for ch in team.lower() if ch.isalnum())
        opponent = mlb_clean_text(row.get("opponent"), fallback="Matchup pending")
        stat = normalize_text(row.get("stat"))
        projection = safe_float(row.get("projection"))
        line = safe_float(row.get("line"))
        edge = safe_float(row.get("edge"))
        confidence = normalize_text(row.get("confidence")) or "Low"
        lean = normalize_text(row.get("lean"))
        cells = [
            f"<td data-label='{escape(entity_label)}'><strong class='mlb-player-name'>{escape(player or entity_label)}</strong></td>",
            f"<td data-label='Team'>{escape(team or '—')}</td>",
            f"<td data-label='Opponent'>{escape(opponent)}</td>",
            f"<td data-label='Stat'>{escape(stat or 'N/A')}</td>",
            f"<td data-label='Projection'><strong class='mlb-projection-value'>{escape(normalize_text(row.get('projection_display')) or metric_label(projection))}</strong></td>",
        ]
        for label, key, render_type in extra_columns:
            raw_value = row.get(key)
            if render_type == "pct":
                display_value = pct_label(raw_value)
            elif render_type == "num":
                display_value = metric_label(raw_value)
            else:
                display_value = normalize_text(raw_value, "n/a")
            cells.append(f"<td data-label='{escape(label)}'>{escape(display_value)}</td>")
        cells.append(f"<td data-label='Confidence'>{render_mlb_confidence_badge(confidence)}</td>")
        if include_lean:
            cells.append(f"<td data-label='Lean'><span class='mlb-lean-pill'>{escape(lean or 'Lean')}</span></td>")
        body_rows.append(
            "<tr "
            f"data-player='{escape(player.lower())}' "
            f"data-team='{escape(team)}' "
            f"data-team-key='{escape(team_key)}' "
            f"data-stat='{escape(stat.lower())}' "
            f"data-profile-key='{escape(normalize_profile_key(player, team))}' "
            f"data-projection='{safe_float(row.get('sort_projection'), default=-9999)}' "
            f"data-edge='{safe_float(row.get('sort_edge'), default=0)}' "
            f"data-confidence='{safe_float(row.get('sort_confidence'), default=0)}'>"
            + "".join(cells)
            + "</tr>"
        )

    lean_header = "<th>Lean</th>" if include_lean else ""
    extra_headers = "".join(f"<th>{escape(label)}</th>" for label, _, _ in extra_columns)
    return (
        "<section class='panel mlb-board-panel'>"
        f"<div class='panel-head'><div><div class='eyebrow'>MLB</div><h2>{escape(title)}</h2></div>"
        f"<p class='muted'>{escape(subtitle)}</p></div>"
        f"<div class='table-shell mlb-table-shell'><table class='mlb-projection-table' id='{escape(scope_id)}-table'><thead><tr>"
        f"<th>{escape(entity_label)}</th><th>Team</th><th>Opponent</th><th>Stat</th><th>Projection</th>{extra_headers}<th>Confidence</th>{lean_header}"
        "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div></section>"
    )


def render_mlb_projection_cards(title, subtitle, rows, scope_id, entity_label="Player", extra_columns=None, default_stat=None, debug_route=None, debug_category=None):
    rows = filter_mlb_hitter_projection_rows(rows, default_stat)
    if not rows:
        return render_empty_state(
            title,
            f"No {title.lower()} are currently available.",
            "The latest MLB projection files are still being generated. Check back shortly.",
        )
    extra_columns = extra_columns or []
    debug_comment = ""
    if default_stat:
        debug_comment = log_mlb_hitter_category_debug(
            debug_route or scope_id,
            debug_category or default_stat,
            default_stat,
            rows,
        )

    teams = sorted({normalize_text(row.get("team")).upper() for row in rows if normalize_text(row.get("team"))})

    from collections import OrderedDict
    player_groups = OrderedDict()
    for row in rows:
        player = normalize_text(row.get("player"))
        team = normalize_text(row.get("team")).upper()
        opponent = mlb_clean_text(row.get("opponent"), fallback="Matchup pending")
        key = (player.lower(), team, opponent)
        if key not in player_groups:
            player_groups[key] = {
                "player": player,
                "team": team,
                "opponent": opponent,
                "rows": [],
            }
        player_groups[key]["rows"].append(row)

    team_options = "".join(f'<option value="{escape(team)}">{escape(team)}</option>' for team in teams)
    team_filter_html = (
        '<div class="mlb-team-filter">'
        f'<label class="filter-field" for="{escape(scope_id)}-team-filter"><span>Team</span>'
        f'<select id="{escape(scope_id)}-team-filter" class="mlb-team-select" data-card-filter="{escape(scope_id)}">'
        '<option value="ALL">All Teams</option>'
        f"{team_options}"
        '</select></label>'
        '</div>'
    )

    cards = []
    for key, group in player_groups.items():
        player = group["player"]
        team = group["team"]
        opponent = group["opponent"]

        confidences = [normalize_text(r.get("confidence")) or "Low" for r in group["rows"]]
        best_confidence = max(confidences, key=lambda c: {"High": 3, "Medium": 2, "Low": 1}.get(confidence_level(c), 0))

        meta_chips = ""
        if extra_columns and group["rows"]:
            first_row = group["rows"][0]
            chips = []
            for label, key_name, render_type in extra_columns:
                raw_value = first_row.get(key_name)
                if render_type == "pct":
                    display_value = pct_label(raw_value)
                elif render_type == "num":
                    display_value = metric_label(raw_value)
                else:
                    display_value = normalize_text(raw_value, "n/a")
                chips.append(f'<span class="meta-chip">{escape(label)} {escape(display_value)}</span>')
            if chips:
                meta_chips = '<div class="card-meta">' + "".join(chips) + "</div>"

        primary_html = ""
        if default_stat and group["rows"]:
            primary_row = group["rows"][0]
            primary_stat = normalize_text(primary_row.get("stat"), default_stat)
            primary_value = normalize_text(primary_row.get("projection_display")) or metric_label(safe_float(primary_row.get("projection")))
            line_val = safe_float(primary_row.get("line"))
            edge_val = safe_float(primary_row.get("edge"))
            support_items = []
            if line_val is not None:
                support_items.append(f"Line {metric_label(line_val)}")
            if edge_val is not None:
                support_items.append(f"Edge {metric_label(edge_val)}")
            support_html = f'<div class="primary-support">{escape(" | ".join(support_items))}</div>' if support_items else ""
            primary_html = (
                '<div class="primary-stat">'
                f'<span>{escape(primary_stat)}</span>'
                f'<strong>{escape(primary_value)}</strong>'
                f'{support_html}'
                '</div>'
            )

        stat_rows_html = []
        stat_names = {normalize_text(row.get("stat")) for row in group["rows"] if normalize_text(row.get("stat"))}
        limited_coverage = stat_names == {"Fantasy Points"}
        rows_for_stat_list = [] if default_stat else group["rows"]
        for row in rows_for_stat_list:
            stat = normalize_text(row.get("stat"))
            proj = normalize_text(row.get("projection_display")) or metric_label(safe_float(row.get("projection")))
            line_val = safe_float(row.get("line"))
            line = metric_label(line_val) if line_val is not None else "—"
            edge_val = safe_float(row.get("edge"))
            edge = metric_label(edge_val) if edge_val is not None else "—"
            lean = normalize_text(row.get("lean")) or "—"
            stat_rows_html.append(
                f'<div class="stat-row">'
                f'<span class="stat-name">{escape(stat)}</span>'
                f'<span class="stat-val">{escape(proj)}</span>'
                f'<span class="stat-line">{escape(line)}</span>'
                f'<span class="stat-edge">{escape(edge)}</span>'
                f'<span class="stat-lean">{escape(lean)}</span>'
                f'</div>'
            )

        cards.append(
            f'<article class="play-card" data-player="{escape(player.lower())}" data-team="{escape(team)}">'
            f'<div class="play-top"><div><div class="play-name">{escape(player or entity_label)}</div>'
            f'<div class="play-sub">{escape(team or "—")} vs {escape(opponent)}</div></div>'
            f'{render_mlb_confidence_badge(best_confidence)}</div>'
            f'{"<div class=\"card-meta\"><span class=\"meta-chip limited-chip\">Limited stat coverage</span></div>" if limited_coverage else ""}'
            f'{meta_chips}'
            f'{primary_html}'
            f'<div class="stat-rows">'
            f'{"".join(stat_rows_html)}'
            f'</div>'
            f'</article>'
        )

    return (
        debug_comment
        +
        '<section class="panel">'
        f'<div class="panel-head"><div><div class="eyebrow">MLB</div><h2>{escape(title)}</h2></div>'
        f'<p class="muted">{escape(subtitle)}</p></div>'
        f'{team_filter_html}'
        f'<p class="muted projection-summary" id="{escape(scope_id)}-summary">Showing {len(player_groups)} players.</p>'
        f'<div class="play-grid-shell" id="{escape(scope_id)}-cards">'
        f'{"".join(cards)}'
        f'</div></section>'
        f'''<style>
.mlb-team-filter {{ max-width: 280px; margin: 14px 0 16px; }}
.mlb-team-select {{ width: 100%; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--line); background: rgba(10, 15, 28, 0.92); color: #fff; font: inherit; }}
.card-meta {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }}
.meta-chip {{ display: inline-flex; align-items: center; padding: 4px 10px; border-radius: 999px; border: 1px solid rgba(59, 130, 246, 0.22); background: rgba(59, 130, 246, 0.1); color: #dbeafe; font-size: 11px; font-weight: 700; letter-spacing: 0.04em; }}
.limited-chip {{ border-color: rgba(245, 158, 11, 0.28); background: rgba(245, 158, 11, 0.10); color: #fcd34d; }}
.primary-stat {{ display: grid; gap: 5px; margin: 10px 0 8px; }}
.primary-stat span {{ color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; }}
.primary-stat strong {{ color: #fff; font-size: 28px; line-height: 1; letter-spacing: 0; }}
.primary-support {{ color: var(--muted); font-size: 12px; font-weight: 700; }}
.stat-rows {{ display: grid; gap: 0px; margin-top: 8px; }}
.stat-row {{ display: grid; grid-template-columns: 1.4fr 1fr 0.7fr 0.7fr 0.7fr; gap: 8px; align-items: center; padding: 8px 0; border-top: 1px solid rgba(30, 41, 59, 0.6); font-size: 13px; }}
.stat-row:first-child {{ border-top: none; padding-top: 0; }}
.stat-row span {{ color: var(--muted); font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }}
.stat-row .stat-name {{ color: #fff; font-weight: 800; font-size: 14px; text-transform: none; letter-spacing: normal; }}
.stat-row .stat-val {{ color: #fff; font-weight: 800; font-size: 14px; }}
</style>'''
        f'''<script>
(() => {{
  const container = document.getElementById("{scope_id}-cards");
  if (!container) return;
  const cards = Array.from(container.querySelectorAll(".play-card"));
  const teamSelect = document.getElementById("{scope_id}-team-filter");
  const summary = document.getElementById("{scope_id}-summary");

  let activeTeam = "ALL";

  function apply() {{
    const visible = cards.filter((card) => {{
      return activeTeam === "ALL" || card.dataset.team === activeTeam;
    }});

    cards.forEach((card) => {{
      const show = visible.includes(card);
      card.hidden = !show;
      card.style.display = show ? "" : "none";
    }});

    const parts = [`Showing ${{visible.length}} of ${{cards.length}} players`];
    if (activeTeam !== "ALL") parts.push(`team: ${{activeTeam}}`);
    summary.textContent = parts.join(" | ");
  }}

  teamSelect?.addEventListener("change", () => {{
    activeTeam = teamSelect.value || "ALL";
    apply();
  }});

  apply();
}})();
</script>'''
    )


def mlb_hitter_realism_columns(rows):
    if not rows:
        return []
    return [
        ("Blend", "outcome_blend", "pct"),
        ("Shadow", "outcome_shadow", "pct"),
        ("Current", "outcome_current", "pct"),
        ("Realism", "realism_source", "text"),
    ]


def render_mlb_projection_snapshot(hitter_rows, pitcher_rows):
    broad_hitter_count = len({normalize_text(row.get("player")) for row in hitter_rows if normalize_text(row.get("player"))})
    pitcher_count = len({normalize_text(row.get("player")) for row in pitcher_rows if normalize_text(row.get("player"))})
    stat_mix = len({normalize_text(row.get("stat")) for row in hitter_rows if normalize_text(row.get("stat"))})
    top_projection = max((safe_float(row.get("projection"), default=0) for row in hitter_rows), default=0)
    return render_stat_cards([
        ("Hitters Modeled", broad_hitter_count, "Valid hitter projections currently surfaced from today's MLB export."),
        ("Pitchers Modeled", pitcher_count, "Pitcher projection rows currently available on the live board."),
        ("Hitter Stats", stat_mix, "Distinct hitter stat markets currently exposed on the page."),
        ("Top Hitter Projection", pct_label(top_projection), "Highest active hitter projection currently displayed on the slate."),
    ], compact=True)


def render_mlb_player_profile_explorer(payload):
    records = payload.get("records", []) if isinstance(payload, dict) else []
    if not records:
        return ""
    profile_map = {}
    for row in records:
        profile_map[normalize_profile_key(row.get("player"), row.get("team"))] = row
    payload_json = json.dumps(json_ready(records)).replace("</", "<\\/")
    return (
        f"<script type='application/json' id='mlb-profile-data'>{payload_json}</script>"
        """
<script>
(() => {
  const dataNode = document.getElementById("mlb-profile-data");
  if (!dataNode) return;
  const records = JSON.parse(dataNode.textContent || "[]");
  const profileByKey = new Map(records.map((record) => [`${String(record.player || "").trim().toLowerCase().replace(/\\s+/g, " ")}|${String(record.team || "").trim().toUpperCase()}`, record]));
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  const normalizePlayer = (value) => String(value || "").trim().toLowerCase().replace(/\\s+/g, " ");
  const normalizeTeam = (value) => String(value || "").trim().toUpperCase();

  function fieldGrid(title, fields) {
    if (!fields || !fields.length) return "";
    return `<div class="profile-field-group"><h3>${escapeHtml(title)}</h3><div class="profile-field-grid">${fields.map((field) => `<div class="profile-field"><span>${escapeHtml(field.label)}</span><strong>${escapeHtml(field.display)}</strong></div>`).join("")}</div></div>`;
  }

  function profileHtml(record) {
    const context = [record.team, record.opponent || record.matchup].filter(Boolean).join(" / ");
    return `
      <td colspan="99">
        <div class="mlb-inline-profile">
          <div class="profile-card-head">
            <div><div class="eyebrow">Player Stat Profile</div><h3>${escapeHtml(record.player)}</h3><p class="muted">${escapeHtml(context || "Model View")}</p></div>
            <span class="badge badge-medium">${escapeHtml(record.confidence || "Model View")}</span>
          </div>
          ${fieldGrid("Hitter Stats", record.hitter_stats)}
          ${fieldGrid("Pitcher Stats", record.pitcher_stats)}
          ${fieldGrid("Probability", record.probabilities)}
        </div>
      </td>
    `;
  }

  function profileForRow(row) {
    const key = `${normalizePlayer(row.dataset.player)}|${normalizeTeam(row.dataset.team)}`;
    return profileByKey.get(key) || records.find((record) => normalizePlayer(record.player) === normalizePlayer(row.dataset.player));
  }

  function toggleProfile(row) {
    const next = row.nextElementSibling;
    if (next && next.classList.contains("mlb-profile-detail-row")) {
      next.remove();
      row.classList.remove("profile-expanded");
      return;
    }
    const record = profileForRow(row);
    if (!record) return;
    const detailRow = document.createElement("tr");
    detailRow.className = "mlb-profile-detail-row";
    detailRow.innerHTML = profileHtml(record);
    row.insertAdjacentElement("afterend", detailRow);
    row.classList.add("profile-expanded");
  }

  document.addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-player]");
    if (!row || !row.closest(".mlb-board-panel")) return;
    if (row.classList.contains("mlb-profile-detail-row")) return;
    toggleProfile(row);
  });
})();
</script>
"""
    )


def render_mlb_compact_top_plays(rows):
    compact_rows = []
    for row in rows[:6]:
        compact_rows.append({
            "player": normalize_text(row.get("player")),
            "stat_type": normalize_text(row.get("stat_type")),
            "projection": safe_float(row.get("projection")),
            "sportsbook_line": safe_float(row.get("sportsbook_line")),
            "edge": safe_float(row.get("edge")),
            "confidence": normalize_text(row.get("confidence")),
            "recommended_play": normalize_text(row.get("recommended_play")),
        })
    return render_data_table(
        "Top Plays Summary",
        "A smaller edge snapshot kept below the full projection boards.",
        compact_rows,
        [
            ("Player", "player", "text"),
            ("Stat", "stat_type", "text"),
            ("Projection", "projection", "num"),
            ("Line", "sportsbook_line", "num"),
            ("Edge", "edge", "num"),
            ("Confidence", "confidence", "badge"),
            ("Play", "recommended_play", "text"),
        ],
        "No MLB top plays are currently available.",
        "Today's best-bet summary is still being generated. Check back shortly.",
    )


def render_performance_summary(summary, title="Performance Snapshot", body="Tracked MLB performance across the full graded history."):
    cards = [
        ("Total Wins", summary.get("total_wins", 0), "All graded MLB wins tracked so far."),
        ("Total Losses", summary.get("total_losses", 0), "All graded MLB losses tracked so far."),
        ("Win Rate", f"{summary.get('win_rate', 0)}%", "Overall win rate across resolved bets."),
        ("Last 7 Days", summary.get("last_7_days", "0-0"), "Resolved MLB record over the last 7 days."),
        ("Last 30 Days", summary.get("last_30_days", "0-0"), "Resolved MLB record over the last 30 days."),
        ("Current Streak", summary.get("current_streak", "No active streak"), "Current resolved streak based on the latest results."),
    ]
    return "<section class='panel'><div class='panel-head'><h2>" + escape(title) + "</h2><p class='muted'>" + escape(body) + "</p></div>" + render_stat_cards(cards) + "</section>"


def render_resource_cards(cards):
    body = []
    for title, description, href, meta in cards:
        meta_html = f"<div class='resource-meta'>{escape(meta)}</div>" if meta else ""
        body.append(
            f"<a class='resource-card' href='{href}'>"
            f"<strong>{escape(title)}</strong>"
            f"<p>{escape(description)}</p>"
            f"{meta_html}"
            "</a>"
        )
    return "<div class='resource-grid'>" + "".join(body) + "</div>"


def render_waitlist_status(kind, message):
    if not message:
        return ""
    css = "status-card status-success" if kind == "success" else "status-card status-info"
    return f"<section class='{css}'><p>{escape(message)}</p></section>"


def render_pricing_cards(cards):
    body = []
    for name, price, description, bullets, featured in cards:
        featured_class = " pricing-card-featured" if featured else ""
        bullet_html = "".join(f"<div class='pricing-bullet'>{escape(item)}</div>" for item in bullets)
        body.append(
            f"<article class='pricing-card{featured_class}'>"
            f"<div class='pricing-name'>{escape(name)}</div>"
            f"<div class='pricing-price'>{escape(price)}</div>"
            f"<p class='muted'>{escape(description)}</p>"
            f"<div class='pricing-bullets'>{bullet_html}</div>"
            "<div class='cta-row'>"
            f"<a class='cta-btn {'primary' if featured else 'secondary'}' href='/mlb'>Start Here</a>"
            "</div>"
            "</article>"
        )
    return "<div class='pricing-grid'>" + "".join(body) + "</div>"


def render_quote_cards(quotes):
    body = []
    for quote, who, meta in quotes:
        body.append(
            "<article class='quote-card'>"
            f"<p class='quote-text'>{escape(quote)}</p>"
            f"<div class='quote-who'>{escape(who)}</div>"
            f"<div class='quote-meta'>{escape(meta)}</div>"
            "</article>"
        )
    return "<div class='quote-grid'>" + "".join(body) + "</div>"


def render_marketing_card(title, description, bullets, button_label="Join Waitlist", form_html=""):
    bullet_html = "".join(f"<li>{escape(item)}</li>" for item in bullets)
    form_block = form_html or ""
    return (
        "<section class='pricing-hero'>"
        "<div class='pricing-emblem-wrap'><img class='pricing-emblem' src='/brand/emblem.png' alt='EdgeRanked emblem'></div>"
        "<div class='pricing-kicker'>Open Beta</div>"
        f"<h2>{escape(title)}</h2>"
        f"<p class='muted pricing-copy'>{escape(description)}</p>"
        "<article class='pricing-card pricing-card-featured pricing-card-single'>"
        "<div class='pricing-name'>Join the EdgeRankedAI Waitlist</div>"
        "<div class='waitlist-free-label'>Free public access is live during beta testing.</div>"
        "<ul class='pricing-list'>"
        f"{bullet_html}"
        "</ul>"
        f"{form_block}"
        "<div class='contact-panel'>"
        "<div class='contact-title'>Contact</div>"
        f"<p class='muted'>Questions before launch? Reach us at <a href='mailto:{WAITLIST_CONTACT_EMAIL}'>{WAITLIST_CONTACT_EMAIL}</a>.</p>"
        "</div>"
        f"<p class='pricing-footnote'>{escape(button_label)} for early access, launch updates, and premium subscriber tools.</p>"
        "</article>"
        "</section>"
    )


def render_waitlist_form(form_values=None):
    values = form_values or {}
    return (
        "<form class='waitlist-form' method='post' action='/waitlist'>"
        "<div class='form-grid'>"
        "<label class='form-field'>"
        "<span>Name</span>"
        f"<input type='text' name='name' required maxlength='120' value='{escape(normalize_text(values.get('name')))}' placeholder='Your name'>"
        "</label>"
        "<label class='form-field'>"
        "<span>Email</span>"
        f"<input type='email' name='email' required maxlength='200' value='{escape(normalize_text(values.get('email')))}' placeholder='you@example.com'>"
        "</label>"
        "</div>"
        "<label class='form-field'>"
        "<span>Message or interest</span>"
        f"<textarea name='message' rows='4' maxlength='1000' placeholder='Tell us which tools or sports you want first.'>{escape(normalize_text(values.get('message')))}</textarea>"
        "</label>"
        "<input type='hidden' name='source_page' value='/waitlist'>"
        "<div class='cta-row'>"
        "<button class='cta-btn primary pricing-button' type='submit'>Join Waitlist</button>"
        "</div>"
        "</form>"
    )


def build_waitlist_page(form_values=None, submit_state=None):
    form_values = form_values or {}
    submit_state = submit_state or {}
    body = (
        render_waitlist_status(submit_state.get("kind"), submit_state.get("message"))
        + render_marketing_card(
            "Join the EdgeRankedAI Waitlist",
            "Join the waitlist for early access, launch updates, and premium subscriber tools.",
            [
                "Free public access during beta testing for NBA, MLB, PGA, and UFC dashboards",
                "Priority updates as new models and premium tools are released",
                "A direct line for launch announcements and subscriber onboarding",
            ],
            form_html=render_waitlist_form(form_values),
        )
    )
    return render_layout(
        "Join the EdgeRankedAI Waitlist",
        "Join the waitlist for early access, launch updates, and premium subscriber tools.",
        body,
        "/waitlist",
        hero_kicker="Open Beta",
    )


def render_text_sections(title, last_updated=None, intro=None, callout=None, sections=None):
    sections = sections or []
    last_updated_html = f"<p class='muted legal-updated'>Last Updated: {escape(last_updated)}</p>" if last_updated else ""
    intro_html = f"<p class='muted legal-intro'>{escape(intro)}</p>" if intro else ""
    callout_html = f"<section class='legal-callout'><p>{escape(callout)}</p></section>" if callout else ""
    body = []
    for heading, text in sections:
        body.append(
            "<section class='legal-section'>"
            f"<h3>{escape(heading)}</h3>"
            f"<p>{escape(text)}</p>"
            "</section>"
        )
    return (
        "<section class='legal-shell'>"
        f"<h2>{escape(title)}</h2>"
        f"{last_updated_html}"
        f"{callout_html}"
        f"{intro_html}"
        "<div class='legal-card'>"
        f"{''.join(body)}"
        "</div>"
        "</section>"
    )


def render_json_panel(title, subtitle, data):
    return (
        "<section class='panel'>"
        f"<div class='panel-head'><div><h2>{escape(title)}</h2></div><p class='muted'>{escape(subtitle)}</p></div>"
        f"<pre>{escape(json.dumps(json_ready(data), indent=2))}</pre>"
        "</section>"
    )


def render_ufc_fight_cards(fights):
    if not fights:
        return render_empty_state(
            "Fight Forecasts",
            "No UFC fight forecasts are currently available.",
            "The current event payload has not been published yet.",
        )
    cards = []
    for fight in fights[:10]:
        if not isinstance(fight, dict):
            continue
        fighter_name = normalize_text(fight.get("predicted_winner")) or normalize_text(fight.get("fighter_red")) or "Fight"
        probability = fight.get("predicted_winner_pct")
        cards.append(
            "<article class='play-card'>"
            f"<div class='play-top'><div><div class='play-name'>{escape(fighter_name)}</div><div class='play-sub'>{escape(normalize_text(fight.get('fight_title')) or 'Fight Forecast')}</div></div>{render_badge(fight.get('confidence_tier') or 'Live', 'confidence')}</div>"
            "<div class='play-grid'>"
            "<div><span>Fighter Name</span>"
            f"<strong>{escape(fighter_name)}</strong></div>"
            "<div><span>Prop</span><strong>Win</strong></div>"
            f"<div><span>Probability</span><strong>{escape(pct_label(probability))}</strong></div>"
            "</div>"
            f"{render_ufc_finish_breakdown(fight)}"
            "</article>"
        )
    return "<section class='panel'><div class='panel-head'><div><div class='eyebrow'>Fight Card</div><h2>Current UFC card</h2></div><p class='muted'>Simple model probabilities for the current published card.</p></div><div class='play-grid-shell'>" + "".join(cards) + "</div></section>"


def build_ufc_max_round_lookup():
    payload = read_json(UFC_PAGE_SPECS["fights"]["path"])
    fights = payload.get("fights", []) if isinstance(payload, dict) else []
    lookup = {}
    for fight in fights:
        if not isinstance(fight, dict):
            continue
        fight_id = normalize_text(fight.get("fight_id"))
        if not fight_id:
            continue
        card_label = normalize_text(fight.get("card_label")).lower()
        max_rounds = 5 if card_label == "main event" else 3
        lookup[fight_id] = max_rounds
    return lookup


def ufc_prop_fighter_name(row):
    projection_player = normalize_text(row.get("projection_player"))
    if projection_player:
        return projection_player
    selection = normalize_text(row.get("selection")).lower()
    red = normalize_text(row.get("fighter_red"))
    blue = normalize_text(row.get("fighter_blue"))
    if selection == "red" and red:
        return red
    if selection == "blue" and blue:
        return blue
    market_label = normalize_text(row.get("market_label"))
    if red and red.lower() in market_label.lower():
        return red
    if blue and blue.lower() in market_label.lower():
        return blue
    return f"{red} vs {blue}".strip(" vs") or "Fight"


def ufc_prop_label(row):
    label = normalize_text(row.get("market_label"))
    line = safe_float(row.get("line"))
    if line is None:
        return label or normalize_text(row.get("market_type")) or "Prop"
    return f"{label} ({metric_label(line)})" if label else metric_label(line)


def build_ufc_player_projection_profiles():
    payload = read_json(UFC_PAGE_SPECS["fights"]["path"])
    fights = payload.get("fights", []) if isinstance(payload, dict) else []
    props = read_csv_df(UFC_PAGE_SPECS["props"]["path"])
    profiles = {}

    for fight in fights:
        fight_title = normalize_text(fight.get("fight_title")) or "Fight"
        event_name = normalize_text(fight.get("event_name") or payload.get("event", {}).get("name") if isinstance(payload, dict) else "")
        red = normalize_text(fight.get("red_fighter") or fight.get("fighter_red") or fight.get("red_name"))
        blue = normalize_text(fight.get("blue_fighter") or fight.get("fighter_blue") or fight.get("blue_name"))
        for fighter, opponent, win_key in [(red, blue, "red_win_pct"), (blue, red, "blue_win_pct")]:
            if not fighter:
                continue
            profile = profiles.setdefault(normalize_profile_key(fighter), {
                "player": fighter,
                "player_type": "Fighter",
                "team": "",
                "opponent": opponent,
                "matchup": fight_title,
                "event": event_name,
                "confidence": confidence_level(fight.get("confidence_tier")),
                "stats": [],
                "probabilities": [],
                "confidence_fields": [],
            })
            append_profile_field(profile["probabilities"], "Win Probability", fight.get(win_key), "probability", win_key)
            append_profile_field(profile["probabilities"], "KO / TKO Probability", fight.get("ko_tko_pct"), "probability", "ko_tko_pct")
            append_profile_field(profile["probabilities"], "Submission Probability", fight.get("submission_pct"), "probability", "submission_pct")
            append_profile_field(profile["probabilities"], "Decision Probability", fight.get("decision_pct"), "probability", "decision_pct")
            append_profile_field(profile["stats"], "Fight Time Minutes", fight.get("fight_time_mins"), "value", "fight_time_mins")
            append_profile_field(profile["confidence_fields"], "Confidence", fight.get("confidence_tier"), "value", "confidence_tier")

    if not props.empty:
        for _, raw in props.iterrows():
            fighter = ufc_prop_fighter_name(raw)
            if not fighter:
                continue
            key = normalize_profile_key(fighter)
            red = normalize_text(raw.get("fighter_red"))
            blue = normalize_text(raw.get("fighter_blue"))
            opponent = normalize_text(raw.get("projection_opponent")) or (blue if red.lower() == fighter.lower() else red)
            profile = profiles.setdefault(key, {
                "player": fighter,
                "player_type": "Fighter",
                "team": "",
                "opponent": opponent,
                "matchup": f"{red} vs {blue}".strip(" vs") or "Fight",
                "event": normalize_text(raw.get("event_name")),
                "confidence": "Model View",
                "stats": [],
                "probabilities": [],
                "confidence_fields": [],
            })
            append_profile_field(profile["probabilities"], ufc_prop_label(raw), raw.get("probability"), "probability", raw.get("market_type"))

    records = finalize_player_profiles(profiles)
    records = sorted(records, key=lambda item: item.get("player", ""))
    sources = [UFC_PAGE_SPECS["fights"]["path"], UFC_PAGE_SPECS["props"]["path"]]
    last_updated = max(filter(None, [file_timestamp(path) for path in [UFC_PAGE_SPECS["fights"]["path"], UFC_PAGE_SPECS["props"]["path"]]]), default=None)
    return {"records": records, "teams": [], "source_labels": public_data_source_labels(sources), "last_updated": last_updated}


def render_ufc_props_table(rows):
    preferred = []
    fallback = []
    max_round_lookup = build_ufc_max_round_lookup()
    for row in rows:
        source = normalize_text(row.get("source")).lower()
        market_type = normalize_text(row.get("market_type")).lower()
        line_value = safe_float(row.get("line"))
        if market_type == "total_rounds" and line_value is not None:
            fight_id = normalize_text(row.get("fight_id"))
            max_rounds = max_round_lookup.get(fight_id, 3)
            if line_value > max_rounds:
                continue
        normalized = {
            "fighter_name": ufc_prop_fighter_name(row),
            "prop": ufc_prop_label(row),
            "probability": row.get("probability"),
        }
        if "prize" in source:
            preferred.append(normalized)
        else:
            fallback.append(normalized)
    cleaned = preferred or fallback
    cleaned.sort(key=lambda item: safe_float(item.get("probability")) or 0, reverse=True)
    return render_data_table(
        "UFC Props",
        "Published PrizePicks props are shown when available. Simulation props are used as a fallback.",
        cleaned,
        [("Fighter Name", "fighter_name", "text"), ("Prop", "prop", "text"), ("Probability", "probability", "pct")],
        "No UFC PrizePicks props are currently available.",
        "The current UFC export does not include any live PrizePicks or simulation props yet.",
    )


def render_path_panel(path):
    return ""


def render_player_profile_explorer(title, subtitle, payload, scope_id, entity_label="Player", team_label="Team"):
    records = payload.get("records", []) if isinstance(payload, dict) else []
    if not records:
        return render_empty_state(
            "Model Coverage",
            f"No {entity_label.lower()} profiles are currently available.",
            "The existing projection output files do not currently contain supported player-level rows for this view.",
        )

    teams = payload.get("teams", [])
    options = []
    for index, row in enumerate(records):
        label_parts = [normalize_text(row.get("player"), entity_label)]
        team = normalize_text(row.get("team"))
        if team:
            label_parts.append(team)
        player_type = normalize_text(row.get("player_type"))
        if player_type:
            label_parts.append(player_type)
        options.append(
            f"<option value='{index}' data-team='{escape(team.upper())}' data-player='{escape(normalize_player_key(row.get('player')))}'>{escape(' - '.join(label_parts))}</option>"
        )
    team_options = "".join(f"<option value='{escape(team)}'>{escape(team)}</option>" for team in teams)
    payload_json = json.dumps(json_ready(records)).replace("</", "<\\/")
    return (
        "<section class='panel player-profile-panel'>"
        f"<div class='panel-head'><div><div class='eyebrow'>Projection Explorer</div><h2>{escape(title)}</h2></div>"
        f"<p class='muted'>{escape(subtitle)}</p></div>"
        "<div class='filter-toolbar player-profile-controls'>"
        f"<label class='filter-field'><span>Search {escape(entity_label.lower())}</span><input id='{escape(scope_id)}-search' type='search' placeholder='Search by name'></label>"
        f"<label class='filter-field'><span>{escape(team_label)}</span><select id='{escape(scope_id)}-team'><option value='ALL'>All</option>{team_options}</select></label>"
        f"<label class='filter-field player-select-field'><span>{escape(entity_label)}</span><select id='{escape(scope_id)}-player'><option value=''>Select {escape(entity_label.lower())}</option>{''.join(options)}</select></label>"
        f"<div class='filter-field'><span>Reset</span><button class='cta-btn secondary filter-reset-btn' id='{escape(scope_id)}-reset' type='button'>Show Full Board</button></div>"
        "</div>"
        f"<div class='player-profile-card' id='{escape(scope_id)}-profile'></div>"
        f"<script type='application/json' id='{escape(scope_id)}-data'>{payload_json}</script>"
        f"""
<script>
(() => {{
  const dataNode = document.getElementById("{scope_id}-data");
  const playerSelect = document.getElementById("{scope_id}-player");
  const teamSelect = document.getElementById("{scope_id}-team");
  const searchInput = document.getElementById("{scope_id}-search");
  const profileNode = document.getElementById("{scope_id}-profile");
  const resetButton = document.getElementById("{scope_id}-reset");
  if (!dataNode || !playerSelect || !profileNode) return;
  const records = JSON.parse(dataNode.textContent || "[]");
  const placeholder = playerSelect.querySelector("option[value='']")?.cloneNode(true);
  const allOptions = Array.from(playerSelect.options).filter((option) => option.value !== "").map((option) => option.cloneNode(true));
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[char]));
  function fieldGrid(title, fields) {{
    if (!fields || !fields.length) return "";
    return `<div class="profile-field-group"><h3>${{escapeHtml(title)}}</h3><div class="profile-field-grid">${{fields.map((field) => `<div class="profile-field"><span>${{escapeHtml(field.label)}}</span><strong>${{escapeHtml(field.display)}}</strong></div>`).join("")}}</div></div>`;
  }}
  function renderProfile(indexValue) {{
    if (indexValue === "" || indexValue === undefined || indexValue === null) {{
      clearProfile();
      return;
    }}
    const record = records[Number.parseInt(indexValue || "0", 10)] || records[0];
    if (!record) {{
      clearProfile();
      return;
    }}
    const context = [record.player_type, record.team, record.opponent || record.matchup || record.event].filter(Boolean).join(" / ");
    profileNode.innerHTML = `
      <div class="profile-card-head">
        <div><div class="eyebrow">Player Stat Profile</div><h3>${{escapeHtml(record.player)}}</h3><p class="muted">${{escapeHtml(context || "Model View")}}</p></div>
        <span class="badge badge-medium">${{escapeHtml(record.confidence || "Model View")}}</span>
      </div>
      ${{fieldGrid("Projected Stats", record.stats)}}
      ${{fieldGrid("Probability", record.probabilities)}}
      ${{fieldGrid("Confidence", record.confidence_fields)}}
    `;
    profileNode.hidden = false;
  }}
  function clearProfile() {{
    playerSelect.value = "";
    profileNode.hidden = true;
    profileNode.innerHTML = "";
  }}
  function applyFilters() {{
    const team = (teamSelect?.value || "ALL").toUpperCase();
    const query = (searchInput?.value || "").trim().toLowerCase();
    const filtered = allOptions.filter((option) => {{
      const record = records[Number.parseInt(option.value || "0", 10)] || {{}};
      const matchesTeam = team === "ALL" || (option.dataset.team || "").toUpperCase() === team;
      const matchesQuery = !query || String(record.player || "").toLowerCase().includes(query);
      return matchesTeam && matchesQuery;
    }});
    playerSelect.replaceChildren(...[placeholder, ...filtered.map((option) => option.cloneNode(true))].filter(Boolean));
    clearProfile();
  }}
  function selectByPlayerName(playerName) {{
    const target = String(playerName || "").trim().toLowerCase();
    if (!target) return;
    const option = Array.from(playerSelect.options).find((item) => item.dataset.player === target);
    if (option) {{
      playerSelect.value = option.value;
      renderProfile(option.value);
      profileNode.scrollIntoView({{ behavior: "smooth", block: "nearest" }});
    }}
  }}
  playerSelect.addEventListener("change", () => renderProfile(playerSelect.value));
  teamSelect?.addEventListener("change", applyFilters);
  searchInput?.addEventListener("input", applyFilters);
  resetButton?.addEventListener("click", () => {{
    if (teamSelect) teamSelect.value = "ALL";
    if (searchInput) searchInput.value = "";
    applyFilters();
  }});
  document.addEventListener("click", (event) => {{
    const row = event.target.closest("tr[data-player]");
    if (!row) return;
    selectByPlayerName(row.dataset.player);
  }});
  applyFilters();
}})();
</script>
"""
        "</section>"
    )


def render_nba_projection_table(rows):
    if not rows:
        return render_empty_state(
            "Projection Explorer",
            "No NBA projections are currently available.",
            "The current NBA projection file has not been loaded yet.",
        )

    stat_options = sorted({row["stat_key"]: row["stat_label"] for row in rows}.items(), key=lambda item: item[1])
    team_options = sorted({row["team"] for row in rows if row["team"]})
    header_cells = [
        "<th>Player</th>",
        "<th>Stat</th>",
        "<th>Projection</th>",
        "<th>Probability</th>",
        "<th>Minutes</th>",
        "<th>Context</th>",
    ]

    body_rows = []
    for row in rows:
        probability = pct_label(row["threshold_probability"]) if row["threshold_probability"] is not None else "n/a"

        body_rows.append(
            "<tr "
            f"class='nba-player-row' "
            f"data-player='{escape(row['player'])}' "
            f"data-team='{escape(row['team'])}' "
            f"data-nba-filter-target='1' "
            f"data-stat='{escape(row['stat_key'])}' "
            f"data-matchup='{escape(row['matchup'].lower())}' "
            f"data-opponent='{escape(row['opponent'].lower())}' "
            f"data-projection='{row['projection'] if row['projection'] is not None else ''}' "
            f"data-probability='{row['threshold_probability'] if row['threshold_probability'] is not None else ''}' "
            f"data-minutes='{row['expected_minutes'] if row['expected_minutes'] is not None else ''}' "
            f"data-confidence-rank='{row['confidence_rank']}'>"
            + "<td data-label='Player'><div class='player-cell'><div class='player-main'>"
            + escape(row["player"])
            + "</div></div></td>"
            + "<td data-label='Stat'><div class='stat-chip'>"
            + escape(row["stat_label"])
            + "</div></td>"
            + "<td data-label='Projection'><div class='projection-main'>"
            + escape(metric_label(row["projection"]))
            + "</td>"
            + "<td data-label='Probability'><div class='projection-main'>"
            + escape(probability)
            + "</div></td>"
            + "<td data-label='Minutes'><div class='projection-main'>"
            + escape(metric_label(row["expected_minutes"]))
            + "</div></td>"
            + "<td data-label='Context'>"
            + render_badge(row["confidence"], "confidence")
            + "</td>"
            + "</tr>"
        )

    team_select = "".join(f"<option value='{escape(team)}'>{escape(team)}</option>" for team in team_options)
    stat_select = "".join(f"<option value='{escape(key)}'>{escape(label)}</option>" for key, label in stat_options)
    sort_select = "".join(
        f"<option value='{escape(value)}'>{escape(label)}</option>"
        for value, label in [
            ("projection", "Projection"),
            ("probability", "Probability"),
            ("confidence", "Confidence"),
            ("minutes", "Minutes"),
            ("player", "Player"),
            ("team", "Team"),
        ]
    )

    total_players = len({row["player"] for row in rows})
    total_teams = len({row["team"] for row in rows})
    total_stats = len({row["stat_key"] for row in rows})

    return (
        "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Projection Explorer</div><h2>Full-slate player intelligence</h2></div>"
        "<p class='muted'>This board now runs off the full NBA projection source, not the reduced app-view subset. Team filtering shows every projected player available in the underlying slate file.</p></div>"
        + render_stat_cards([
            ("Modeled Players", str(total_players), "Players currently included in the full simulation output."),
            ("Projection Rows", str(len(rows)), "Player-stat combinations available for browsing and sorting."),
            ("Teams Live", str(total_teams), "Teams active in the current slate file."),
            ("Stats Covered", str(total_stats), "Projection markets available across the explorer."),
        ], compact=True)
        + "<div class='filter-toolbar five-up'>"
        "<label class='filter-field'><span>Team</span><select id='nba-team-filter'><option value='ALL'>All Teams</option>"
        + team_select
        + "</select></label>"
        "<label class='filter-field'><span>Stat</span><select id='nba-stat-filter'><option value='ALL'>All Stats</option>"
        + stat_select
        + "</select></label>"
        "<label class='filter-field'><span>Sort By</span><select id='nba-sort-field'>"
        + sort_select
        + "</select></label>"
        "<label class='filter-field'><span>Direction</span><select id='nba-sort-direction'><option value='desc'>High to Low</option><option value='asc'>Low to High</option></select></label>"
        "<div class='filter-field'><span>Reset</span><button class='cta-btn secondary filter-reset-btn' id='nba-reset-filters' type='button'>Reset Filters</button></div>"
        "</div>"
        f"<p class='muted projection-summary' id='nba-projection-summary'>Showing {len(rows)} rows across {total_players} players.</p>"
        "<div class='table-shell analytics-table-shell'><table id='nba-projection-table'><thead><tr>"
        + "".join(header_cells)
        + "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div>"
        "<style>[hidden]{display:none !important;}</style>"
        "</section>"
        """
<script>
(() => {
  const table = document.getElementById("nba-projection-table");
  if (!table) return;

  const tbody = table.querySelector("tbody");
  const targets = Array.from(document.querySelectorAll('[data-nba-filter-target="1"]'));
  const teamFilter = document.getElementById("nba-team-filter");
  const statFilter = document.getElementById("nba-stat-filter");
  const sortField = document.getElementById("nba-sort-field");
  const sortDirection = document.getElementById("nba-sort-direction");
  const resetButton = document.getElementById("nba-reset-filters");
  const summary = document.getElementById("nba-projection-summary");
  let rafId = 0;

  function numericValue(row, key) {
    const value = Number.parseFloat(row.dataset[key] || "");
    return Number.isNaN(value) ? -Infinity : value;
  }

  function textValue(row, key) {
    return (row.dataset[key] || "").toLowerCase();
  }

  function sortValue(row, key) {
    if (key === "player" || key === "team") return textValue(row, key);
    if (key === "confidence") return Number.parseFloat(row.dataset.confidenceRank || "0");
    return numericValue(row, key);
  }

  function applyFiltersAndSort() {
    const team = String(teamFilter.value || "ALL").trim().toUpperCase();
    const stat = String(statFilter.value || "ALL").trim().toUpperCase();
    const sortKey = sortField.value || "projection";
    const direction = sortDirection.value === "asc" ? 1 : -1;

    const visibleRows = targets.filter((row) => {
      const matchesTeam = team === "ALL" || String(row.dataset.team || "").trim().toUpperCase() === team;
      const matchesStat = stat === "ALL" || String(row.dataset.stat || "").trim().toUpperCase() === stat;
      return matchesTeam && matchesStat;
    });

    visibleRows.sort((a, b) => {
      const left = sortValue(a, sortKey);
      const right = sortValue(b, sortKey);
      if (typeof left === "string" || typeof right === "string") {
        const stringDelta = String(left).localeCompare(String(right)) * direction;
        if (stringDelta !== 0) return stringDelta;
        return textValue(a, "player").localeCompare(textValue(b, "player"));
      }
      const numericDelta = (left - right) * direction;
      if (numericDelta !== 0) return numericDelta;
      return textValue(a, "player").localeCompare(textValue(b, "player"));
    });

    targets.forEach((row) => {
      row.hidden = true;
      row.style.display = "none";
    });
    visibleRows.forEach((row) => {
      row.hidden = false;
      row.style.display = "";
      if (row.tagName === "TR" && row.parentNode === tbody) {
        tbody.appendChild(row);
      }
    });

    const playerCount = new Set(visibleRows.map((row) => row.dataset.player || "")).size;
    const summaryBits = [`Showing ${visibleRows.length} row${visibleRows.length === 1 ? "" : "s"}`, `${playerCount} player${playerCount === 1 ? "" : "s"}`];
    if (team !== "ALL") summaryBits.push(`team ${team}`);
    if (stat !== "ALL" && statFilter.selectedIndex >= 0) summaryBits.push(statFilter.options[statFilter.selectedIndex].text);
    summary.textContent = summaryBits.join(" | ");
  }

  function scheduleApply() {
    if (rafId) window.cancelAnimationFrame(rafId);
    rafId = window.requestAnimationFrame(applyFiltersAndSort);
  }

  [teamFilter, statFilter, sortField, sortDirection].forEach((control) => {
    control.addEventListener("change", scheduleApply);
    control.addEventListener("input", scheduleApply);
  });

  resetButton.addEventListener("click", () => {
    teamFilter.value = "ALL";
    statFilter.value = "ALL";
    sortField.value = "projection";
    sortDirection.value = "desc";
    scheduleApply();
  });

  applyFiltersAndSort();
})();
</script>
"""
    )


def render_nba_projection_snapshot(snapshot_cards):
    if not snapshot_cards:
        return render_empty_state(
            "Top Projection Snapshot",
            "No projection leaders are currently available.",
            "Snapshot cards will populate once the latest projection file is loaded.",
        )

    cards_html = []
    for card in snapshot_cards:
        leader_items = []
        for index, leader in enumerate(card["leaders"], start=1):
            leader_items.append(
                "<li class='leader-item'>"
                + f"<span class='leader-rank'>{index}</span>"
                + "<div class='leader-copy'><div class='leader-name'>"
                + escape(leader["player"])
                + "</div><div class='leader-meta'>"
                + escape(leader["team"])
                + " | "
                + escape(metric_label(leader["projection"]))
                + " | "
                + escape(leader["threshold_label"])
                + " at "
                + escape(pct_label(leader["threshold_probability"]))
                + "</div></div>"
                + "</li>"
            )
        cards_html.append(
            "<article class='leader-card'>"
            + "<div class='leader-card-head'><div class='eyebrow'>Snapshot</div><h3>"
            + escape(card["stat_label"])
            + "</h3></div><ol class='leader-list'>"
            + "".join(leader_items)
            + "</ol></article>"
        )

    return (
        "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Top Player Projection Snapshot</div><h2>Where the slate leads by category</h2></div>"
        "<p class='muted'>Leaders are pulled across points, rebounds, assists, 3PM, defensive events, combo stats, fantasy output, and workload so the page feels like a true projection engine instead of a single-market board.</p></div>"
        "<div class='leader-grid'>"
        + "".join(cards_html)
        + "</div></section>"
    )


def render_nba_best_bets_summary(board, title="Supporting Top Plays Layer", subtitle="Sportsbook-facing picks remain available, but the main focus stays on projections, value, and verified results."):
    rows = board.get("records", [])[:4]
    if not rows:
        return render_empty_state(
            title,
            "No NBA top plays are currently available.",
            "The supporting top-plays layer will appear once the latest board is published.",
        )

    cards = []
    for row in rows:
        cards.append(
            "<article class='play-card signal-card-quiet'>"
            + "<div class='play-top'><div><div class='play-name'>"
            + escape(row["player"])
            + "</div><div class='play-sub'>"
            + escape(row["team"])
            + " | "
            + escape(row["matchup"])
            + "</div></div>"
            + render_badge(row["confidence"], "confidence")
            + "</div>"
            + "<div class='play-grid'>"
            + "<div><span>Model Projection</span><strong>"
            + escape(metric_label(row["projection"]))
            + "</strong></div>"
            + "<div><span>Stat</span><strong>"
            + escape(row["stat"])
            + "</strong></div>"
            + "<div><span>Sportsbook Line</span><strong>"
            + escape(metric_label(row["line"]))
            + "</strong></div>"
            + "<div><span>Recent Hit Rate</span><strong>"
            + escape(pct_label(row["hit_rate"]))
            + "</strong></div>"
            + "</div><p class='muted'>"
            + escape(row["bet"] or "Model signal")
            + " | Line and pick language are shown as secondary context only."
            + "</p></article>"
        )

    summary_caption = "n/a"
    if board.get("recent_hit_rate") is not None:
        summary_caption = pct_label(board["recent_hit_rate"])

    return (
        "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Secondary Layer</div><h2>"
        + escape(title)
        + "</h2></div><p class='muted'>"
        + escape(subtitle)
        + "</p></div>"
        + render_stat_cards([
            ("Top Plays Published", str(board.get("plays_shown", 0)), "Top-play rows currently available from the published board."),
            ("Recent Graded Hit Rate", summary_caption, "Computed from the most recent graded NBA history rows."),
            ("Last Updated", format_timestamp(board.get("last_updated")), "Timestamp of the current top-plays source file."),
        ], compact=True)
        + "<div class='play-grid-shell'>"
        + "".join(cards)
        + "</div></section>"
    )


def render_nba_record_panel(record_data):
    summary = record_data.get("summary", {})
    daily_rows = record_data.get("records", [])
    recent_rows = record_data.get("recent_results", [])

    daily_table = render_data_table(
        "Daily Performance Ledger",
        "Recent day-by-day tracked NBA performance from the published record summary file.",
        daily_rows,
        [("Date", "date", "text"), ("Wins", "wins", "text"), ("Losses", "losses", "text"), ("Tracked", "total", "text"), ("Win Rate", "win_rate", "pct")],
        "No NBA record data is currently available.",
        "The latest NBA record summary file has not been loaded yet.",
    )

    recent_results_table = render_data_table(
        "Recent Verified Results",
        "Latest graded outcomes pulled directly from NBA bet history.",
        recent_rows,
        [("Date", "date", "text"), ("Player", "player", "text"), ("Team", "team", "text"), ("Stat", "stat", "text"), ("Bet", "bet", "text"), ("Projection", "projection", "num"), ("Actual", "actual", "num"), ("Result", "result", "result")],
        "No graded NBA history rows are currently available.",
        "Verified results will appear here once graded history exists.",
    )

    return (
        "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Verified Results</div><h2>Performance as a trust driver</h2></div>"
        "<p class='muted'>Results stay visible beside the NBA projections so the board stays accountable, current, and verifiable.</p></div>"
        + "</section>"
        + daily_table
        + recent_results_table
    )


def render_nba_best_bets_table(board):
    rows = board.get("records", [])
    if not rows:
        return render_empty_state(
            "NBA Top Plays",
            "No NBA top plays are currently available.",
            "The supporting top-plays board has not been generated yet.",
        )

    table_rows = []
    for row in rows:
        table_rows.append({
            "player": row["player"],
            "team": row["team"],
            "matchup": row["matchup"],
            "stat": row["stat"],
            "projection": row["projection"],
            "line": row["line"],
            "edge": row["edge"],
            "hit_rate": row["hit_rate"],
            "confidence": row["confidence"],
            "result": row["result"],
        })

    return (
        "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Top Plays</div><h2>Highest-Value Lines</h2></div>"
        "<p class='muted'>This page displays the lines with the highest current value based on the model's pricing and confidence framework.</p></div>"
        + (f"<section class='notice-banner'>{escape(board.get('banner'))}</section>" if board.get('banner') else "")
        + "</section>"
        + render_data_table(
            "NBA Top Plays",
            "Projection remains primary, with confidence and recent hit rate ahead of line context.",
            table_rows,
            [("Player", "player", "text"), ("Team", "team", "text"), ("Matchup", "matchup", "text"), ("Stat", "stat", "text"), ("Projection", "projection", "num"), ("Confidence", "confidence", "badge"), ("Hit Rate", "hit_rate", "pct"), ("Line", "line", "num"), ("Edge", "edge", "num"), ("Result", "result", "result")],
            "No NBA top plays are currently available.",
            "The current NBA top-plays board has not been generated yet.",
        )
    )


def render_layout(title, subtitle, body_html, active_path, section_nav=None, hero_kicker=None, hero_media_html=""):
    section_nav_html = section_nav or ""
    kicker = hero_kicker or "Premium Sports Analytics"
    return f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-L9N5JKN47H"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', 'G-L9N5JKN47H');
  </script>
  <style>
    :root {{
      --bg: #020617;
      --surface: #0b1220;
      --surface-strong: #060b17;
      --surface-soft: rgba(15, 23, 42, 0.72);
      --ink: #f8fafc;
      --muted: #94a3b8;
      --line: #1f2937;
      --accent: #3b82f6;
      --accent-strong: #2563eb;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --shadow: 0 24px 60px rgba(2, 8, 23, 0.5);
      --radius-xl: 28px;
      --radius-lg: 24px;
      --radius-md: 16px;
    }}
    * {{ box-sizing: border-box; }}
    html {{ background: var(--bg); color-scheme: dark; }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at 50% 0%, rgba(59, 130, 246, 0.12), transparent 30%),
        radial-gradient(circle at 85% 20%, rgba(59, 130, 246, 0.08), transparent 22%),
        var(--bg);
      color: var(--ink);
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    a {{ color: inherit; }}
    img {{ display: block; }}
    .site-nav {{
      position: sticky;
      top: 0;
      z-index: 50;
      border-bottom: 1px solid var(--line);
      background: rgba(2, 6, 23, 0.84);
      backdrop-filter: blur(18px);
    }}
    .nav-shell, .shell, .footer-shell {{
      width: min(1280px, calc(100% - 24px));
      margin: 0 auto;
    }}
    .nav-shell {{
      min-height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 10px 0;
    }}
    .nav-brand {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      text-decoration: none;
    }}
    .nav-logo {{
      width: 32px;
      height: 32px;
      object-fit: contain;
    }}
    .nav-wordmark {{
      color: #fff;
      font-size: 20px;
      font-weight: 700;
      letter-spacing: -0.04em;
      white-space: nowrap;
    }}
    .brand-accent {{ color: var(--accent); }}
    .shell {{
      padding: 24px 0 48px;
    }}
    .hero {{
      position: relative;
      overflow: hidden;
      background: linear-gradient(180deg, rgba(15, 23, 42, 0.98), rgba(2, 6, 23, 0.98));
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      border-radius: var(--radius-xl);
      padding: 24px;
      margin-bottom: 22px;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -8% -36% auto;
      width: 420px;
      height: 420px;
      background: radial-gradient(circle, rgba(59,130,246,0.14) 0%, transparent 70%);
      pointer-events: none;
    }}
    .brand-row {{
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 18px;
    }}
    .top-links, .sub-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .top-link, .sub-link, .cta-btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      text-decoration: none;
      border-radius: 14px;
      border: 1px solid var(--line);
      padding: 10px 16px;
      font-size: 13px;
      font-weight: 600;
      background: rgba(15, 23, 42, 0.7);
      color: var(--muted);
      transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
    }}
    .top-link:hover, .sub-link:hover, .cta-btn:hover {{
      transform: translateY(-1px);
      border-color: rgba(59, 130, 246, 0.35);
      color: #fff;
    }}
    .top-link.active, .sub-link.active, .cta-btn.primary {{
      color: #fff;
      background: var(--surface);
      border-color: rgba(59, 130, 246, 0.18);
    }}
    .cta-btn.secondary {{
      background: rgba(18, 25, 41, 0.9);
      color: #fff;
      border-color: var(--line);
    }}
    .hero-copy {{
      max-width: 760px;
      margin-bottom: 10px;
    }}
    h1, h2, h3, p {{ margin: 0; }}
    h1 {{
      font-size: clamp(42px, 6vw, 72px);
      line-height: 1.02;
      letter-spacing: -0.05em;
      margin-bottom: 12px;
      max-width: 12ch;
      color: #fff;
    }}
    h2 {{
      font-size: clamp(24px, 3vw, 34px);
      line-height: 1.05;
      letter-spacing: -0.04em;
      color: #fff;
    }}
    h3 {{
      color: #fff;
    }}
    .hero-sub, .muted {{
      color: var(--muted);
      line-height: 1.65;
      font-size: 15px;
    }}
    .hero-sub {{
      font-size: 18px;
      max-width: 56ch;
    }}
    .cta-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }}
    .hero-kicker, .eyebrow, .pricing-kicker {{
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 8px;
    }}
    .hero-emblem {{
      width: 88px;
      height: auto;
      margin: 0 0 22px;
      filter: drop-shadow(0 0 18px rgba(59,130,246,0.32));
    }}
    .content {{
      display: grid;
      gap: 20px;
    }}
    .content > * {{
      min-width: 0;
    }}
    .split {{
      display: grid;
      grid-template-columns: minmax(0, 1.08fr) minmax(0, 0.92fr);
      gap: 20px;
      align-items: start;
    }}
    .stack {{
      display: grid;
      gap: 18px;
      min-width: 0;
    }}
    .panel {{
      background: var(--surface-soft);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      border-radius: var(--radius-lg);
      padding: 24px;
      min-width: 0;
    }}
    .panel-head {{
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 16px;
      margin-bottom: 18px;
    }}
    .notice-banner {{
      padding: 14px 18px;
      border-radius: 16px;
      background: rgba(59, 130, 246, 0.08);
      border: 1px solid rgba(59, 130, 246, 0.2);
      color: #dbeafe;
      font-weight: 700;
    }}
    .status-card {{
      padding: 16px 18px;
      border-radius: 16px;
      border: 1px solid rgba(59, 130, 246, 0.22);
      background: rgba(59, 130, 246, 0.08);
      color: #dbeafe;
    }}
    .status-success {{
      border-color: rgba(16, 185, 129, 0.25);
      background: rgba(16, 185, 129, 0.1);
      color: #d1fae5;
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }}
    .metric-grid.compact {{
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    }}
    .metric-card {{
      background: rgba(15, 23, 42, 0.72);
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      padding: 18px;
    }}
    .metric-label {{
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-weight: 800;
      color: var(--muted);
      margin-bottom: 10px;
    }}
    .metric-value {{
      font-size: clamp(25px, 3vw, 36px);
      font-weight: 800;
      line-height: 1;
      letter-spacing: -0.03em;
      color: #fff;
    }}
    .metric-caption {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }}
    .resource-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 14px;
    }}
    .resource-card {{
      display: block;
      text-decoration: none;
      background: linear-gradient(180deg, rgba(15,23,42,0.98), rgba(2,6,23,0.98));
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 18px;
      transition: transform 0.15s ease, border-color 0.15s ease;
    }}
    .resource-card:hover {{
      transform: translateY(-2px);
      border-color: rgba(59, 130, 246, 0.34);
    }}
    .resource-card strong {{
      display: block;
      font-size: 17px;
      margin-bottom: 10px;
      color: #fff;
    }}
    .resource-card p {{
      color: var(--muted);
      line-height: 1.55;
      margin-bottom: 12px;
    }}
    .resource-meta {{
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }}
    .table-shell {{
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: rgba(10, 15, 28, 0.72);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      padding: 14px 14px;
      text-align: left;
      border-bottom: 1px solid rgba(30, 41, 59, 0.8);
      white-space: nowrap;
      vertical-align: top;
    }}
    td {{
      color: #d7e0ee;
    }}
    th {{
      position: sticky;
      top: 0;
      z-index: 1;
      background: rgba(10, 15, 28, 0.96);
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }}
    tbody tr:nth-child(even) {{
      background: rgba(255, 255, 255, 0.01);
    }}
    tbody tr:hover {{
      background: rgba(59, 130, 246, 0.06);
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 78px;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.10em;
      text-transform: uppercase;
      border: 1px solid transparent;
    }}
    .badge-high {{
      background: rgba(16, 185, 129, 0.12);
      color: #a7f3d0;
      border-color: rgba(16, 185, 129, 0.18);
    }}
    .badge-medium, .badge-pending, .badge-neutral {{
      background: rgba(59, 130, 246, 0.1);
      color: #bfdbfe;
      border-color: rgba(59, 130, 246, 0.18);
    }}
    .badge-low {{
      background: rgba(245, 158, 11, 0.10);
      color: #fcd34d;
      border-color: rgba(245, 158, 11, 0.16);
    }}
    .badge-win {{
      background: rgba(16, 185, 129, 0.12);
      color: #a7f3d0;
      border-color: rgba(16, 185, 129, 0.18);
    }}
    .badge-loss {{
      background: rgba(239, 68, 68, 0.12);
      color: #fca5a5;
      border-color: rgba(239, 68, 68, 0.16);
    }}
    .badge-push {{
      background: rgba(59, 130, 246, 0.10);
      color: #bfdbfe;
      border-color: rgba(59, 130, 246, 0.16);
    }}
    .play-grid-shell {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
    }}
    .play-card {{
      background: linear-gradient(180deg, rgba(18,25,41,0.98), rgba(10,15,28,0.98));
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      padding: 18px;
    }}
    .play-top {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
      margin-bottom: 14px;
    }}
    .play-name {{
      font-size: 18px;
      font-weight: 800;
      line-height: 1.15;
      color: #fff;
    }}
    .play-sub {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
    }}
    .play-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }}
    .play-grid span {{
      display: block;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }}
    .play-grid strong {{
      font-size: 16px;
      line-height: 1.2;
      color: #fff;
    }}
    .ufc-finish-block {{
      margin-top: 6px;
      padding-top: 14px;
      border-top: 1px solid rgba(30, 41, 59, 0.85);
    }}
    .ufc-finish-title {{
      margin-bottom: 10px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .ufc-finish-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .ufc-finish-cell {{
      padding: 12px;
      border-radius: 14px;
      border: 1px solid rgba(59, 130, 246, 0.16);
      background: rgba(10, 15, 28, 0.68);
    }}
    .ufc-finish-cell span {{
      display: block;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      line-height: 1.35;
    }}
    .ufc-finish-cell strong {{
      color: #fff;
      font-size: 15px;
      line-height: 1.2;
    }}
    .empty-panel {{
      text-align: center;
      padding: 42px 26px;
      background: linear-gradient(180deg, rgba(18,25,41,0.98), rgba(10,15,28,0.98));
    }}
    .meta-panel {{
      padding: 16px 18px;
    }}
    .meta-strip {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
    }}
    .meta-chip {{
      padding: 14px 16px;
      border-radius: 14px;
      border: 1px solid rgba(59, 130, 246, 0.16);
      background: linear-gradient(180deg, rgba(10,15,28,0.92), rgba(18,25,41,0.92));
    }}
    .meta-chip span {{
      display: block;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .meta-chip strong {{
      color: #fff;
      font-size: 15px;
      line-height: 1.4;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      border-radius: var(--radius-md);
      border: 1px solid var(--line);
      background: rgba(10, 15, 28, 0.9);
      padding: 18px;
      color: #dbe7f5;
      font-size: 13px;
      line-height: 1.6;
      overflow-x: auto;
    }}
    .pricing-grid, .quote-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
    }}
    .pricing-card, .quote-card {{
      background: linear-gradient(180deg, rgba(18,25,41,0.98), rgba(10,15,28,0.98));
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      padding: 20px;
    }}
    .pricing-card-featured {{
      border-color: rgba(59, 130, 246, 0.42);
      box-shadow: 0 18px 36px rgba(37, 99, 235, 0.18);
    }}
    .pricing-name {{
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 10px;
    }}
    .pricing-price {{
      font-size: 34px;
      font-weight: 800;
      letter-spacing: -0.04em;
      margin-bottom: 10px;
      color: #fff;
    }}
    .pricing-price span {{
      font-size: 16px;
      color: var(--muted);
      font-weight: 500;
      margin-left: 4px;
    }}
    .pricing-bullets {{
      display: grid;
      gap: 8px;
      margin-top: 14px;
    }}
    .pricing-bullet {{
      padding: 10px 12px;
      border-radius: 12px;
      background: rgba(59, 130, 246, 0.08);
      color: #dbeafe;
      font-size: 13px;
      font-weight: 600;
    }}
    .quote-text {{
      color: #dbe7f5;
      line-height: 1.65;
      font-size: 15px;
      margin-bottom: 16px;
    }}
    .quote-who {{
      font-weight: 800;
      margin-bottom: 4px;
      color: #fff;
    }}
    .quote-meta {{
      color: var(--muted);
      font-size: 13px;
    }}
    .path {{
      color: var(--muted);
      font-size: 12px;
      font-family: Menlo, Monaco, monospace;
      word-break: break-word;
      margin-top: 12px;
    }}
    .pricing-hero {{
      max-width: 720px;
      margin: 0 auto;
      text-align: center;
    }}
    .pricing-emblem-wrap {{
      display: flex;
      justify-content: center;
      margin-bottom: 20px;
    }}
    .pricing-emblem {{
      width: 72px;
      height: 72px;
      object-fit: contain;
      filter: drop-shadow(0 0 18px rgba(59,130,246,0.34));
    }}
    .pricing-copy {{
      margin: 0 auto 28px;
      max-width: 56ch;
    }}
    .waitlist-free-label {{
      margin-bottom: 18px;
      color: #dbeafe;
      font-size: 15px;
      font-weight: 700;
    }}
    .pricing-card-single {{
      text-align: left;
      padding: 28px;
    }}
    .pricing-list {{
      list-style: none;
      padding: 0;
      margin: 24px 0 0;
      display: grid;
      gap: 14px;
    }}
    .pricing-list li {{
      display: flex;
      align-items: center;
      gap: 10px;
      color: #dbe7f5;
    }}
    .pricing-list li::before {{
      content: "\\2713";
      color: var(--accent);
      font-weight: 800;
    }}
    .pricing-button {{
      width: 100%;
      padding-top: 14px;
      padding-bottom: 14px;
      font-size: 16px;
      appearance: none;
      cursor: pointer;
    }}
    .pricing-footnote {{
      margin-top: 14px;
      color: var(--muted);
      font-size: 12px;
      text-align: center;
    }}
    .waitlist-form {{
      display: grid;
      gap: 16px;
      margin-top: 22px;
    }}
    .form-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .form-field, .filter-field {{
      display: grid;
      gap: 8px;
    }}
    .form-field span, .filter-field span {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .form-field input, .form-field textarea, .filter-field select, .filter-field input {{
      width: 100%;
      padding: 14px 16px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: rgba(10, 15, 28, 0.92);
      color: #fff;
      font: inherit;
      resize: vertical;
    }}
    .form-field input:focus, .form-field textarea:focus, .filter-field select:focus, .filter-field input:focus {{
      outline: none;
      border-color: rgba(59, 130, 246, 0.55);
      box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
    }}
    .contact-panel {{
      margin-top: 18px;
      padding: 16px 18px;
      border-radius: 14px;
      border: 1px solid rgba(59, 130, 246, 0.16);
      background: rgba(10, 15, 28, 0.55);
    }}
    .contact-title {{
      margin-bottom: 8px;
      color: #fff;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .contact-panel a {{
      color: #dbeafe;
    }}
    .filter-toolbar {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 16px;
    }}
    .filter-toolbar.five-up {{
      grid-template-columns: repeat(5, minmax(0, 1fr));
    }}
    .player-profile-controls {{
      grid-template-columns: minmax(180px, 1fr) minmax(140px, 0.45fr) minmax(220px, 1.1fr) minmax(140px, 0.45fr);
    }}
    .player-select-field {{
      min-width: 0;
    }}
    .player-profile-card {{
      display: grid;
      gap: 18px;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: rgba(10, 15, 28, 0.72);
    }}
    .player-profile-card[hidden] {{
      display: none;
    }}
    .profile-card-head {{
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 16px;
    }}
    .profile-card-head h3 {{
      font-size: 24px;
      line-height: 1.1;
      margin-bottom: 6px;
    }}
    .profile-field-group {{
      display: grid;
      gap: 10px;
    }}
    .profile-field-group h3 {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .profile-field-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;
    }}
    .profile-field {{
      padding: 12px;
      border: 1px solid rgba(59, 130, 246, 0.16);
      border-radius: 12px;
      background: rgba(18, 25, 41, 0.9);
      min-width: 0;
    }}
    .profile-field span {{
      display: block;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.10em;
      line-height: 1.35;
      text-transform: uppercase;
    }}
    .profile-field strong {{
      color: #fff;
      font-size: 16px;
      line-height: 1.2;
      word-break: break-word;
    }}
    .filter-reset-btn {{
      width: 100%;
      min-height: 50px;
    }}
    .projection-summary {{
      margin-bottom: 16px;
    }}
    .mlb-board-panel {{
      padding: 18px;
      background:
        linear-gradient(180deg, rgba(15, 23, 37, 0.98), rgba(7, 12, 22, 0.98)),
        radial-gradient(circle at top left, rgba(16, 185, 129, 0.08), transparent 30%);
      border-color: rgba(148, 163, 184, 0.16);
    }}
    .mlb-board-panel .panel-head {{
      margin-bottom: 14px;
    }}
    .mlb-board-panel .filter-toolbar {{
      gap: 10px;
      margin-bottom: 12px;
    }}
    .mlb-board-panel .projection-summary {{
      margin-bottom: 10px;
      font-size: 12px;
    }}
    .mlb-table-shell {{
      background: rgba(2, 6, 15, 0.64);
      border-color: rgba(148, 163, 184, 0.14);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
    }}
    .mlb-projection-table {{
      font-size: 12px;
    }}
    .mlb-projection-table th {{
      padding: 11px 12px;
      background: rgba(3, 7, 18, 0.98);
      color: #93a4bc;
    }}
    .mlb-projection-table td {{
      padding: 11px 12px;
      color: #dce6f3;
      border-bottom-color: rgba(30, 41, 59, 0.58);
      vertical-align: middle;
    }}
    .mlb-projection-table tbody tr {{
      background: linear-gradient(90deg, rgba(15, 23, 42, 0.52), rgba(2, 6, 15, 0.18));
    }}
    .mlb-projection-table tbody tr:hover {{
      background: linear-gradient(90deg, rgba(16, 185, 129, 0.08), rgba(59, 130, 246, 0.06));
    }}
    .mlb-projection-table tbody tr[data-player] {{
      cursor: pointer;
    }}
    .mlb-projection-table tbody tr.profile-expanded {{
      background: linear-gradient(90deg, rgba(59, 130, 246, 0.10), rgba(16, 185, 129, 0.06));
    }}
    .mlb-profile-detail-row td {{
      white-space: normal;
      padding: 0;
      background: rgba(2, 6, 15, 0.74);
    }}
    .mlb-inline-profile {{
      display: grid;
      gap: 16px;
      padding: 18px;
      border-top: 1px solid rgba(59, 130, 246, 0.22);
      background: linear-gradient(180deg, rgba(10, 15, 28, 0.86), rgba(15, 23, 42, 0.86));
    }}
    .mlb-player-name {{
      display: inline-block;
      color: #ffffff;
      font-size: 13px;
      letter-spacing: -0.01em;
    }}
    .mlb-projection-value {{
      display: inline-flex;
      min-width: 58px;
      justify-content: center;
      padding: 7px 10px;
      border-radius: 12px;
      background: linear-gradient(180deg, rgba(16, 185, 129, 0.18), rgba(16, 185, 129, 0.06));
      border: 1px solid rgba(16, 185, 129, 0.24);
      color: #d1fae5;
      font-size: 15px;
      font-weight: 900;
      letter-spacing: -0.02em;
    }}
    .mlb-confidence-badge {{
      min-width: 70px;
      padding: 7px 10px;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
    }}
    .mlb-lean-pill {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 54px;
      padding: 7px 10px;
      border-radius: 999px;
      background: rgba(59, 130, 246, 0.10);
      border: 1px solid rgba(59, 130, 246, 0.18);
      color: #dbeafe;
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .analytics-table-shell table {{
      min-width: 1060px;
    }}
    .player-cell, .cell-stack {{
      display: grid;
      gap: 6px;
    }}
    .player-main, .projection-main {{
      color: #fff;
      font-weight: 800;
      font-size: 17px;
      line-height: 1.1;
    }}
    .player-meta {{
      color: #cbd5e1;
      font-size: 13px;
      line-height: 1.5;
    }}
    .cell-support {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
      white-space: normal;
    }}
    .subdued-line {{
      opacity: 0.82;
    }}
    .stat-chip {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: fit-content;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(59, 130, 246, 0.12);
      border: 1px solid rgba(59, 130, 246, 0.22);
      color: #dbeafe;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .leader-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 14px;
    }}
    .leader-card {{
      background: linear-gradient(180deg, rgba(18,25,41,0.98), rgba(10,15,28,0.98));
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      padding: 18px;
    }}
    .leader-card-head {{
      margin-bottom: 14px;
    }}
    .leader-list {{
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 12px;
    }}
    .leader-item {{
      display: grid;
      grid-template-columns: 34px minmax(0, 1fr);
      gap: 12px;
      align-items: start;
    }}
    .leader-rank {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      border-radius: 50%;
      border: 1px solid rgba(59, 130, 246, 0.25);
      background: rgba(59, 130, 246, 0.1);
      color: #dbeafe;
      font-weight: 800;
    }}
    .leader-copy {{
      display: grid;
      gap: 4px;
    }}
    .leader-name {{
      color: #fff;
      font-weight: 800;
    }}
    .leader-meta {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }}
    .signal-card-quiet {{
      background: linear-gradient(180deg, rgba(16,21,35,0.98), rgba(10,15,28,0.98));
      border-color: rgba(30, 41, 59, 0.9);
    }}
    .projection-stat-col.stat-active {{
      background: rgba(59, 130, 246, 0.12);
      color: #fff;
    }}
    .projection-stat-col.stat-hidden {{
      display: none;
    }}
    .results-frame {{
      width: 100%;
      min-height: 1400px;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: #fff;
    }}
    .legal-shell {{
      max-width: 920px;
      margin: 0 auto;
    }}
    .legal-shell h2 {{
      margin-bottom: 18px;
    }}
    .legal-card {{
      background: var(--surface-soft);
      border: 1px solid var(--line);
      border-radius: var(--radius-xl);
      padding: 28px;
      display: grid;
      gap: 24px;
    }}
    .legal-updated, .legal-intro {{
      margin-bottom: 18px;
    }}
    .legal-callout {{
      margin: 0 0 18px;
      padding: 22px;
      border-radius: var(--radius-lg);
      border: 1px solid rgba(59, 130, 246, 0.24);
      background: rgba(59, 130, 246, 0.08);
    }}
    .legal-callout p {{
      color: #fff;
      font-size: 18px;
      font-weight: 700;
      line-height: 1.6;
    }}
    .legal-section h3 {{
      margin-bottom: 10px;
      font-size: 20px;
    }}
    .legal-section p {{
      color: #cbd5e1;
      line-height: 1.8;
    }}
    .site-footer {{
      border-top: 1px solid var(--line);
      padding: 32px 0 44px;
      background: rgba(2, 6, 23, 0.95);
    }}
    .footer-shell {{
      display: grid;
      grid-template-columns: 1.1fr 1.4fr;
      gap: 24px;
      align-items: start;
    }}
    .footer-brand {{
      display: inline-flex;
      align-items: flex-start;
      gap: 10px;
      color: #fff;
      font-weight: 700;
    }}
    .footer-note {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 500;
    }}
    .footer-logo {{
      width: 28px;
      height: 28px;
      object-fit: contain;
    }}
    .footer-links {{
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 24px;
      color: var(--muted);
      font-size: 14px;
    }}
    .footer-col {{
      display: grid;
      gap: 8px;
      min-width: 140px;
    }}
    .footer-col h4 {{
      margin: 0 0 2px;
      color: #fff;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
    }}
    .footer-links a {{
      text-decoration: none;
      color: var(--muted);
    }}
    .footer-links a:hover {{
      color: #fff;
    }}
    .footer-meta {{
      grid-column: 1 / -1;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 10px;
      padding-top: 12px;
      border-top: 1px solid rgba(31, 41, 55, 0.8);
    }}
    .footer-copy {{
      color: #64748b;
      font-size: 12px;
    }}
    @media (max-width: 980px) {{
      .split {{
        grid-template-columns: 1fr;
      }}
      .brand-row {{
        flex-direction: column;
        align-items: start;
      }}
      .hero {{
        padding: 22px;
      }}
      .panel {{
        padding: 18px;
      }}
      .panel-head {{
        flex-direction: column;
        align-items: start;
      }}
      .ufc-finish-grid {{
        grid-template-columns: 1fr 1fr;
      }}
      .table-shell {{
        overflow-x: visible;
        border: none;
        background: transparent;
      }}
      table, thead, tbody, th, td, tr {{
        display: block;
      }}
      thead {{
        position: absolute;
        width: 1px;
        height: 1px;
        margin: -1px;
        overflow: hidden;
      }}
      tbody {{
        display: grid;
        gap: 12px;
      }}
      tr {{
        display: grid;
        gap: 8px;
        padding: 14px;
        border-radius: 16px;
        border: 1px solid var(--line);
        background: var(--surface-strong);
      }}
      td {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        padding: 2px 0;
        border: 0;
        white-space: normal;
      }}
      td::before {{
        content: attr(data-label);
        flex: 0 0 46%;
        color: var(--muted);
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 0.10em;
        text-transform: uppercase;
      }}
      .play-grid {{
        grid-template-columns: 1fr;
      }}
      .mlb-board-panel {{
        padding: 14px;
      }}
      .mlb-projection-table tbody {{
        gap: 10px;
      }}
      .mlb-projection-table tr {{
        gap: 7px;
        padding: 13px;
        border-color: rgba(148, 163, 184, 0.14);
        background:
          linear-gradient(180deg, rgba(15, 23, 42, 0.96), rgba(2, 6, 15, 0.96)),
          radial-gradient(circle at top right, rgba(16, 185, 129, 0.08), transparent 40%);
      }}
      .mlb-projection-table td::before {{
        flex-basis: 42%;
      }}
      .mlb-projection-value {{
        min-width: 64px;
        font-size: 16px;
      }}
      .shell {{
        padding: 18px 0 44px;
      }}
      .nav-shell {{
        align-items: flex-start;
        flex-direction: column;
      }}
      .nav-brand {{
        width: 100%;
        justify-content: space-between;
      }}
      .top-links {{
        width: 100%;
      }}
      .results-frame {{
        min-height: 960px;
      }}
      .form-grid, .filter-toolbar {{
        grid-template-columns: 1fr;
      }}
      .analytics-table-shell {{
        overflow-x: auto;
        border: 1px solid var(--line);
        background: rgba(10, 15, 28, 0.72);
      }}
      .analytics-table-shell table {{
        display: table;
        min-width: 980px;
      }}
      .analytics-table-shell thead {{
        position: static;
        width: auto;
        height: auto;
        margin: 0;
        overflow: visible;
        display: table-header-group;
      }}
      .analytics-table-shell tbody {{
        display: table-row-group;
      }}
      .analytics-table-shell tr {{
        display: table-row;
        padding: 0;
        border-radius: 0;
        border: 0;
        background: transparent;
      }}
      .analytics-table-shell th,
      .analytics-table-shell td {{
        display: table-cell;
        padding: 14px 14px;
        border-bottom: 1px solid rgba(30, 41, 59, 0.8);
        white-space: nowrap;
        vertical-align: top;
      }}
      .analytics-table-shell td::before {{
        content: none;
      }}
      .analytics-table-shell .player-cell,
      .analytics-table-shell .cell-stack {{
        display: grid;
      }}
      .footer-shell {{
        grid-template-columns: 1fr;
        text-align: left;
      }}
      .footer-links {{
        justify-content: flex-start;
      }}
      .footer-meta {{
        justify-content: flex-start;
      }}
    }}
  </style>

<style>
</style>


<script
  async
  crossorigin="anonymous"
  data-clerk-publishable-key="pk_live_Y2xlcmsuZWRnZXJhbmtlZGFpLmNvbSQ"
  src="https://clerk.edgerankedai.com/npm/@clerk/clerk-js@latest/dist/clerk.browser.js">
</script>
<script src="/static/auth_gate.js"></script>

</head>
<body>
  <nav class="site-nav">
    <div class="nav-shell">
      <a class="nav-brand" href="/">
        <img class="nav-logo" src="/brand/logo.png" alt="EdgeRanked SportsAI logo">
        <span class="nav-wordmark">EdgeRanked<span class="brand-accent">SportsAI</span></span>
      </a>
      {render_root_nav(active_path)}
      <a class="cta-btn primary" href='/sign-up'>Create Account</a> <a class='cta-btn secondary' href='/sign-in'>Sign In</a></a>
    </div>
  </nav>
  <div class="shell">
    <section class="hero">
      <div class="brand-row">
        <div class="hero-copy">
          {hero_media_html}
          <div class="hero-kicker">{escape(kicker)}</div>
          <h1>{escape(title)}</h1>
          <p class="hero-sub">{escape(subtitle)}</p>
        </div>
      </div>
      {section_nav_html}
    </section>
    <main class="content">
      {body_html}
    </main>
  </div>
  {render_footer()}
<script src="/static/auth_nav.js"></script>
</body>
</html>"""


def get_mlb_dataset(spec_key):
    kind = MLB_PAGE_SPECS[spec_key]["kind"]
    if kind == "mlb_best_bets":
        data = load_mlb_best_bets()
        data["kind"] = kind
        return data
    if kind == "mlb_pitchers":
        data = load_mlb_pitcher_board()
        data["kind"] = kind
        return data
    if kind == "mlb_history":
        data = load_mlb_history_board()
        data["kind"] = kind
        return data
    if kind == "mlb_graded":
        data = load_mlb_graded_board()
        data["kind"] = kind
        return data
    if kind == "mlb_record":
        data = load_mlb_record_board()
        data["kind"] = kind
        return data
    if kind == "mlb_hitter_full":
        source_path = MLB_OUTPUT_DIR / "hitter_predictions_full.csv"
        if not source_path.exists():
            source_path = MLB_FILES["hitters_full"] if MLB_READER_MODE == "canonical" and MLB_FILES["hitters_full"].exists() else MLB_FILES["hitters"]
        return {
            "kind": kind,
            "records": build_mlb_hitter_projection_board(),
            "source_label": "mlb_projections",
            "last_updated": file_timestamp(source_path),
        }
    if kind in MLB_HITTER_CATEGORY_STATS:
        source_path = MLB_OUTPUT_DIR / "hitter_predictions_full.csv"
        if not source_path.exists():
            source_path = MLB_FILES["hitters_full"] if MLB_READER_MODE == "canonical" and MLB_FILES["hitters_full"].exists() else MLB_FILES["hitters"]
        target_stat = MLB_HITTER_CATEGORY_STATS[kind]
        records = filter_mlb_hitter_projection_rows(build_mlb_hitter_projection_board(), target_stat)
        log_mlb_hitter_category_debug(MLB_PAGE_SPECS[spec_key]["api_route"], kind, target_stat, records)
        return {
            "kind": kind,
            "records": records,
            "source_label": "mlb_projections",
            "last_updated": file_timestamp(source_path),
        }
    if kind == "mlb_lines":
        source_path = MLB_FILES["normalized_lines"]
        lines_df = read_csv_df(source_path)
        if lines_df.empty:
            source_path = MLB_FILES["lines"]
            lines_df = read_csv_df(source_path)
        if not lines_df.empty:
            lines_df = lines_df[lines_df.apply(mlb_line_is_clean_display_row, axis=1)].copy()
        return {"kind": kind, "records": records_from_df(lines_df.head(50)), "source_label": public_data_source_label(source_path), "last_updated": file_timestamp(source_path)}
    if kind == "mlb_tracking":
        hitter_tracking = read_csv_df(MLB_FILES["hitter_tracking"])
        pitcher_tracking = read_csv_df(MLB_FILES["pitcher_tracking"])
        return {
            "kind": kind,
            "hitters": records_from_df(latest_rows_by_date(hitter_tracking, allowed_results_only=False).head(25)),
            "pitchers": records_from_df(latest_rows_by_date(pitcher_tracking, allowed_results_only=False).head(25)),
            "source_label": public_data_source_label(MLB_FILES["hitter_tracking"]),
            "last_updated": max(filter(None, [file_timestamp(MLB_FILES["hitter_tracking"]), file_timestamp(MLB_FILES["pitcher_tracking"])]), default=None),
        }
    return {"kind": kind, "records": mlb_system_rows(), "source_label": "mlb_system", "last_updated": max(filter(None, [file_timestamp(path) for path in MLB_FILES.values()]), default=None)}


def get_nba_dataset(spec_key):
    spec = NBA_PAGE_SPECS[spec_key]
    if spec_key == "projections":
        records = build_nba_projection_records()
        return {
            "kind": "table",
            "records": records,
            "title": spec["title"],
            "description": spec["description"],
            "source_label": "nba_projections",
            "last_updated": file_timestamp(PROJECTIONS_PATH),
        }
    if spec_key in {"history", "graded"}:
        return {"kind": "table", "records": latest_graded_nba_history(), "title": spec["title"], "description": spec["description"]}
    if spec_key == "best_bets":
        board = build_nba_best_bets_board()
        board.update({"kind": "table", "title": spec["title"], "description": spec["description"]})
        return board
    if spec_key == "record":
        board = build_nba_record_board()
        board.update({"kind": "table", "title": spec["title"], "description": spec["description"]})
        return board
    if spec_key == "system":
        return {"kind": "table", "records": [{"service": "nba", "status": "available"}], "title": spec["title"], "description": spec["description"]}
    return {"kind": "table", "records": records_from_df(read_csv_df(spec["path"])), "title": spec["title"], "description": spec["description"]}


def get_ufc_dataset(spec_key):
    spec = UFC_PAGE_SPECS[spec_key]
    if spec_key == "fights":
        return {"kind": "json", "data": read_json(spec["path"]), "title": spec["title"], "description": spec["description"]}
    if spec_key == "system":
        return {"kind": "table", "records": [{"service": "ufc", "status": "available"}], "title": spec["title"], "description": spec["description"]}
    return {"kind": "table", "records": records_from_df(read_csv_df(spec["path"])), "title": spec["title"], "description": spec["description"]}


def build_home_page():
    body = (
        render_banner("Free public access is live during beta testing. Premium memberships are coming soon.")
        + "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Open Beta</div><h2>Free public access is live during beta testing.</h2></div>"
        "<p class='muted'>Access NBA, MLB, UFC, and PGA dashboards now while we prepare launch updates and premium tools.</p></div>"
        + render_page_actions([
            ("View NBA Intelligence", "/nba", "primary"),
            ("View Methodology", "/about", "secondary"),
        ])
        + "</section>"
        + "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Trust Metrics</div><h2>Sharper data. Faster decisions.</h2></div>"
        "<p class='muted'>Daily AI-driven projections, top plays, and fully tracked results across MLB, NBA, UFC, and PGA.</p></div>"
        + render_stat_cards([
            ("Tracked Win Rate", "Live", "Results stay visible beside the model boards."),
            ("Active Streak", "W4", "Current roll across published tracked results."),
            ("Props Scanned Today", "1,402", "Daily model coverage across the active slate."),
            ("Models Active", "4", "NBA, MLB, UFC, and PGA pages stay updated."),
        ], compact=True)
        + "</section>"
        + "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Select Dashboard</div><h2>Choose your sport</h2></div>"
        "<p class='muted'>Open the sport you want and jump straight into the latest board, projections, and results.</p></div>"
        + render_resource_cards([
            ("NBA", "Player projections, matchup intelligence, verified results, and full-slate player analytics", "/nba", "Live"),
            ("MLB", "Strikeout board, hitter targets, daily premium edges", "/mlb", "Live"),
            ("WNBA", "Player projections, top plays, and verified results", "/wnba", "Live"),
            ("PGA", "Matchup edges, finishing targets, strokes gained projections", "/pga", "New"),
            ("UFC", "Fight forecasts, prop edges, finish probability", "/ufc", "Live"),
        ])
        + "</section>"
    )
    hero_media_html = "<img class='hero-emblem' src='/brand/emblem.png' alt='EdgeRanked emblem'>"
    return render_layout(
        "EdgeRanked AI | Premium Sports Analytics",
        "Daily AI-driven projections, top plays, and fully tracked results across MLB, NBA, UFC, and PGA.",
        body,
        "/",
        hero_kicker="Open Beta",
        hero_media_html=hero_media_html,
    )


def build_about_page():
    body = (
        "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>About</div><h2>Built for serious bettors and data-first sports fans.</h2></div>"
        "<p class='muted'>EdgeRanked SportsAI transforms raw model output into clean, actionable boards across MLB, NBA, UFC, and PGA with transparent performance tracking.</p></div>"
        + render_stat_cards([
            ("Model-Driven", "Data-Backed Accuracy", "Every board is powered by real projection models and live data inputs."),
            ("Transparent Results", "Accountable Reporting", "Tracked outcomes and win-rate visibility stay visible across the site."),
            ("Updated Daily", "Built for Daily Use", "Sport-specific dashboards refresh for repeat day-to-day use."),
        ])
        + "</section>"
    )
    return render_layout("About EdgeRanked AI", "A premium sports analytics platform built around model-driven projections, transparent results, and daily decision-ready boards.", body, "/about", hero_kicker="About")


def build_nba_home():
    projection_rows = build_nba_projection_records()
    best_bets_board = build_nba_best_bets_board()
    record_board = build_nba_record_board()
    snapshot_cards = build_nba_projection_snapshot(projection_rows)
    projection_updated = file_timestamp(PROJECTIONS_PATH)

    unique_players = len({row["player"] for row in projection_rows})
    unique_teams = len({row["team"] for row in projection_rows})
    unique_stats = len({row["stat_key"] for row in projection_rows})

    body = (
        render_banner("Projection-first NBA intelligence is live. This section now prioritizes model output, range, confidence, and verified accountability over sportsbook-first presentation.")
        + render_page_actions([
            ("Open Full Projection Explorer", "/nba/projections", "primary"),
        ])
        + "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Daily Slate</div><h2>Premium projection board</h2></div>"
        "<p class='muted'>The NBA experience is rebuilt around full-slate simulation output, distribution-aware probabilities, matchup context, and transparent results reporting.</p></div>"
        + render_stat_cards([
            ("Modeled Players", str(unique_players), "Players included in the current projection file."),
            ("Teams Live", str(unique_teams), "Active teams in the current NBA slate."),
            ("Markets Surfaced", str(unique_stats), "Browsable stat categories powered by the simulation output."),
            ("Projection Update", format_timestamp(projection_updated), "Freshness of the main NBA projection source."),
        ])
        + "</section>"
        + render_nba_projection_snapshot(snapshot_cards)
        + "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Full Projection Access</div><h2>Explore the full player pool</h2></div>"
        "<p class='muted'>Browse every projected team, player, and stat from the full NBA source file with search, premium filters, and probability-aware sorting. Filtered team views now use the complete underlying dataset instead of a reduced featured subset.</p></div>"
        + render_page_actions([
            ("Go to Projection Explorer", "/nba/projections", "primary"),
            ("Jump to Top Plays", "/nba/best-bets", "secondary"),
        ])
        + "</section>"
        + render_nba_record_panel(record_board)
        + render_nba_best_bets_summary(best_bets_board)
    )
    return render_layout(
        "NBA Projection Center",
        "Daily player projections, probabilities, matchup intelligence, and verified results powered by EdgeRanked",
        body,
        "/nba",
        render_subnav(NBA_NAV_ITEMS, "/nba"),
        hero_kicker="NBA",
    )


def build_ufc_home():
    payload = read_json(UFC_PAGE_SPECS["fights"]["path"])
    body = (
        render_ufc_fight_cards(payload.get("fights", []) if isinstance(payload, dict) else [])
        + render_player_profile_explorer(
            "Fighter Model Coverage",
            "Select a fighter to review the fight context, available projection fields, and probabilities from the published UFC outputs.",
            build_ufc_player_projection_profiles(),
            "ufc-profile",
            entity_label="Fighter",
            team_label="Group",
        )
    )
    return render_layout("UFC", "Fight forecasts, prop probabilities, and model-driven card analysis.", body, "/ufc", render_subnav(UFC_NAV_ITEMS, "/ufc"))


def build_mlb_home():
    best_bets = load_mlb_best_bets()
    hitter_rows = build_mlb_hitter_projection_board()
    pitcher_rows = build_mlb_pitcher_projection_board()

    quick_links = """
    <section class='panel'>
      <h2>MLB Snapshot</h2>
      <p class='muted'>Quick view of today’s strongest MLB projection signals. Use the full boards for deeper player-by-player filtering.</p>
      <div class='cta-row'>
        <a class='cta-btn primary' href='/mlb/hitter-board'>Full Hitter Board</a>
        <a class='cta-btn secondary' href='/mlb/pitcher-strikeouts'>Pitcher Board</a>
        <a class='cta-btn secondary' href='/mlb/weather'>Weather Impact</a>
      </div>
    </section>
    """

    body = (
        render_banner(best_bets["banner"])
        + quick_links
        + render_mlb_projection_snapshot(hitter_rows, pitcher_rows)
        + render_mlb_compact_top_plays(best_bets["top_plays"])
    )

    return render_layout("MLB Snapshot", "Today’s MLB projection overview powered by EdgeRanked.", body, "/mlb", render_mlb_nav("/mlb"))



def build_pricing_page(form_values=None, submit_state=None):
    body = (
        render_banner("Premium memberships are coming soon. Join the waitlist for launch updates and early access.")
        + "<section class='pricing-hero'>"
        + "<div class='pricing-emblem-wrap'><img class='pricing-emblem' src='/brand/emblem.png' alt='EdgeRanked emblem'></div>"
        + "<div class='pricing-kicker'>Elite Access</div>"
        + "<h2>Unlock your edge</h2>"
        + "<p class='muted pricing-copy'>One membership for full access to our AI models, daily projections, and tracked results.</p>"
        + "<article class='pricing-card pricing-card-featured pricing-card-single'>"
        + "<div class='pricing-name'>All-Access Membership</div>"
        + "<div class='pricing-price'>$19.99<span>/month</span></div>"
        + "<ul class='pricing-list'>"
        + "<li>Full NBA, MLB, UFC, and PGA boards</li>"
        + "<li>Live model confidence ratings</li>"
        + "<li>Daily projection and results updates</li>"
        + "<li>Priority access to new features</li>"
        + "</ul>"
        + render_page_actions([
            ("Start Membership", "/waitlist", "primary"),
        ])
        + "<p class='pricing-footnote'>Cancel anytime. Secure payment via Stripe.</p>"
        + "</article>"
        + "</section>"
    )
    return render_layout(
        "EdgeRanked AI | Membership",
        "One simple membership for full access to our AI models, daily projections, and tracked results.",
        body,
        "/pricing",
        hero_kicker="Membership",
    )


def build_results_page():
    body = (
        "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Results</div><h2>Results</h2></div>"
        "<p class='muted'>Tracked outcomes and recent performance.</p></div>"
        "<iframe class='results-frame' src='/results/raw' title='EdgeRanked live results'></iframe>"
        "</section>"
    )
    return render_layout("Results", "Tracked outcomes and recent performance.", body, "/results", hero_kicker="Results")


def render_pga_round_links(summary, base_route):
    items = [("Latest", base_route)] + [
        (f"Round {round_value}", f"{base_route}?round={round_value}")
        for round_value in summary["available_rounds"]
    ]
    active = f"{base_route}?round={summary['selected_round']}" if summary["selected_round"] else base_route
    return render_subnav(items, active)


def pga_best_bets_columns():
    return [
        ("Golfer", "golfer_name", "text"),
        ("Round", "round_number", "int"),
        ("Prop", "prop_type", "text"),
        ("Direction", "bet_direction", "text"),
        ("Line", "line_value", "num"),
        ("Simulation", "sim_value", "num"),
        ("Confidence", "confidence", "num"),
        ("Payout", "payout", "num"),
    ]


def pga_available_props_columns():
    return [
        ("Prop", "prop", "text"),
        ("Confidence", "confidence", "badge"),
    ]


def pga_leaderboard_columns():
    return [
        ("Golfer", "golfer_name", "text"),
        ("Win %", "win_perc", "pct"),
        ("Top 5 %", "top5_perc", "pct"),
        ("Top 10 %", "top10_perc", "pct"),
        ("Cut %", "made_cut_perc", "pct"),
        ("Avg Round", "avg_round_score", "num"),
        ("Avg Birdies", "avg_birdies", "num"),
    ]


def build_pga_page(round_number=None):
    summary = load_pga_summary(round_number)
    round_top_bet = summary["round_best_bets"]["records"][0] if summary["round_best_bets"]["records"] else {}
    best_round_prop_value = "Round props pending"
    if round_top_bet:
        golfer = normalize_text(round_top_bet.get("golfer_name"))
        direction = normalize_text(round_top_bet.get("bet_direction"))[:1].upper()
        line = metric_label(round_top_bet.get("line_value"))
        if golfer and direction and line != "n/a":
            best_round_prop_value = f"{golfer} {direction} {line}"
    cards = [
        ("Tournament", summary["tournament_name"], "Current PGA event loaded into the golf model."),
        ("Simulation Mode", summary["simulation_mode"], "The mode currently backing the published PGA board."),
        ("Best Round Prop", best_round_prop_value, "Highest confidence round prop"),
        ("Favorite", normalize_text(summary["favorite"].get("golfer_name"), "Awaiting results"), "Top golfer by current win probability in the latest export."),
        (
            "Best Bet",
            normalize_text(summary["top_bet"].get("golfer_name"), "Awaiting bets"),
            "Current top PGA prop. Round props are prioritized when a round-specific board is available.",
        ),
        ("Round Board", f"Round {summary['selected_round']}" if summary["selected_round"] else "Pending", "Latest valid round-specific board when available."),
    ]
    top_golfers = summary["leaderboard"]["records"][:6]
    top_golfer_rows = []
    for row in top_golfers:
        top_golfer_rows.append({
            "Golfer": normalize_text(row.get("golfer_name")),
            "Win %": pct_label(row.get("win_perc")),
            "Top 10 %": pct_label(row.get("top10_perc")),
            "Cut %": pct_label(row.get("made_cut_perc")),
            "Avg Round": metric_label(row.get("avg_round_score")),
        })

    body = (
        render_stat_cards(cards)
        + render_page_actions([
            ("View Best Bets", "/pga/best-bets", "primary"),
            ("View Leaderboard", "/pga/leaderboard", "secondary"),
        ])
        + render_data_table(
            "Projected Tournament Leaders",
            "The strongest current tournament outlooks based on the latest published simulation.",
            top_golfer_rows,
            [("Golfer", "Golfer", "text"), ("Win %", "Win %", "text"), ("Top 10 %", "Top 10 %", "text"), ("Cut %", "Cut %", "text"), ("Avg Round", "Avg Round", "text")],
            "No PGA projections are currently available.",
            "Publish the latest PGA simulation output to show projected leaders here.",
        )
        + render_player_profile_explorer(
            "Golfer Model Coverage",
            "Select a golfer to inspect the tournament probabilities and projection fields already present in the published PGA simulation file.",
            build_pga_player_projection_profiles(),
            "pga-profile",
            entity_label="Golfer",
            team_label="Group",
        )
        + render_resource_cards([
            ("PGA Round Best Bets", "Round-by-round golf props with simulation values and confidence.", f"/pga/best-bets" + (f"?round={summary['selected_round']}" if summary['selected_round'] else ""), f"{len(summary['round_best_bets']['records'])} plays"),
            ("Tournament Leaderboard", "Latest simulated tournament win, top-5, and cut percentages.", "/pga/leaderboard", f"{len(summary['leaderboard']['records'])} golfers"),
        ])
    )
    return render_layout("PGA", "Round projections, matchup edges, and finishing position targets.", body, "/pga", render_subnav(PGA_NAV_ITEMS, "/pga"), hero_kicker="PGA")


def build_pga_best_bets_page(round_number=None):
    summary = load_pga_summary(round_number)
    round_board = summary["round_best_bets"]
    round_display = f"Round {summary['selected_round']}" if summary["selected_round"] else "Round board pending"
    showing_available_props = bool(round_board.get("is_available_props"))
    body = (
        render_pga_round_links(summary, "/pga/best-bets")
        + render_stat_cards([
            ("Tournament", summary["tournament_name"], "Current event tied to the saved PGA outputs."),
            ("Round", round_display, "The latest valid round-specific prop board currently being shown."),
            ("Plays Shown", len(round_board["records"]), "Current PGA props available on the published board."),
        ], compact=True)
        + (
            render_data_table(
                "Top PGA Props" if showing_available_props else "PGA Round Best Bets",
                "Current PGA props ranked by simulation-based confidence." if showing_available_props else "Round-specific golf props with line, simulation value, and confidence.",
                round_board["records"],
                pga_available_props_columns() if showing_available_props else pga_best_bets_columns(),
                "No PGA round props are currently available.",
                "Publish a round-specific file such as best_bets_R1.json through best_bets_R4.json to populate this page.",
            )
            if round_board["records"]
            else render_empty_state(
                "PGA Round Best Bets",
                "No round-specific PGA props are currently available.",
                "This page only displays published round files. Generic tournament best bets are not shown here until a valid round-specific board exists.",
            )
        )
    )
    return render_layout("PGA Best Bets", "Round-specific golf props in the same EdgeRanked layout used across the site.", body, "/pga/best-bets", render_subnav(PGA_NAV_ITEMS, "/pga/best-bets"), hero_kicker="PGA")


def build_pga_leaderboard_page(round_number=None):
    summary = load_pga_summary(round_number)
    body = (
        render_stat_cards([
            ("Tournament", summary["tournament_name"], "Current event tied to the saved PGA simulation output."),
            ("Favorite", normalize_text(summary["favorite"].get("golfer_name"), "Awaiting results"), "Top golfer by current win probability."),
            ("Golfers", len(summary["leaderboard"]["records"]), "Rows currently published into the PGA leaderboard view."),
        ], compact=True)
        + render_data_table(
            "Tournament Outlook",
            "Latest simulated leaderboard probabilities from the golf model export.",
            summary["leaderboard"]["records"],
            pga_leaderboard_columns(),
            "No PGA simulation output is currently available.",
            "Publish the latest tournament simulation export to show projected leaderboard data here.",
        )
    )
    return render_layout("PGA Leaderboard", "Tournament win, placement, and cut probabilities from the latest PGA simulation.", body, "/pga/leaderboard", render_subnav(PGA_NAV_ITEMS, "/pga/leaderboard"), hero_kicker="PGA")


def build_privacy_policy_page():
    return render_layout(
        "Privacy Policy",
        "How EdgeRanked AI collects, uses, and protects member information.",
        render_text_sections(
            "Privacy Policy",
            last_updated="April 7, 2026",
            sections=[
                ("1. Information We Collect", "EdgeRanked AI collects only the information necessary to provide our analytics services. This includes your email address, account login credentials, and usage activity while logged into the platform. Billing information is processed directly by our payment partners and is not stored on our servers."),
                ("2. How We Use Information", "We use your data strictly to manage your subscription access, provide technical support, send essential account updates, and improve the performance of our model boards."),
                ("3. Payment Processing", "EdgeRanked AI utilizes secure third-party payment processors. We do not store, access, or process your credit card numbers or banking details directly."),
                ("4. Cookies and Analytics", "We utilize cookies and analytics tools to understand how users interact with our dashboards, ensuring we maintain a smooth, responsive experience for all members."),
                ("5. Contact", f"If you have questions regarding your data, please contact our support team at {SUPPORT_EMAIL}."),
            ],
        ),
        "/privacy-policy",
        hero_kicker="Legal",
    )


def build_terms_page():
    return render_layout(
        "Terms of Use",
        "Membership terms for the live EdgeRanked SportsAI website.",
        render_text_sections(
            "Terms of Use",
            sections=[
                ("1. Subscription Access", "Membership grants full, unrestricted access to all EdgeRanked AI model boards and dashboards for $19.99/month. Your subscription is valid for the duration of the paid billing period."),
                ("2. Billing and Cancellation", "Subscriptions are recurring. You may cancel at any time through your account settings. Access remains active through the remainder of your current billing cycle."),
                ("3. Informational Use Only", "All projections, model outputs, and data points are provided for informational and entertainment purposes only. EdgeRanked AI does not provide financial or betting advice. Past performance does not guarantee future outcomes."),
                ("4. Intellectual Property", "All content, proprietary models, dashboard designs, and methodologies are the exclusive intellectual property of EdgeRanked AI. Unauthorized distribution is strictly prohibited."),
            ],
        ),
        "/terms",
        hero_kicker="Legal",
    )


def build_disclaimer_page():
    return render_layout(
        "Disclaimer",
        "Important usage and responsible gaming disclosures for the website.",
        render_text_sections(
            "Disclaimer",
            callout="All sports projections, model outputs, edges, and top plays are provided strictly for informational and entertainment purposes. No outcome is guaranteed. Past results do not guarantee future performance. Users are solely responsible for their own decisions.",
            sections=[
                ("Responsible Gaming", "We strongly advocate for responsible participation. You must be 21+ or the legal age in your jurisdiction to participate in any real-money sports wagering. Never wager more than you can afford to lose. If you or someone you know has a gambling problem, please seek help immediately via local support resources."),
            ],
        ),
        "/disclaimer",
        hero_kicker="Legal",
    )


def build_mlb_dataset_page(spec_key):
    spec = MLB_PAGE_SPECS[spec_key]
    data = get_mlb_dataset(spec_key)
    title = spec["title"]
    subtitle = spec["description"]
    nav = render_mlb_nav(spec["route"])

    if spec_key == "best_bets":
        record = load_mlb_record_board()
        body = (
            render_banner(data["banner"])
            + render_meta_strip(data)
            + render_mlb_top_play_cards(data["top_plays"])
            + render_performance_summary(record["summary"], "Performance Snapshot", "Trust builder: current record, recent form, and streak alongside the live board.")
            + render_data_table(
                "Full MLB Best Bets Board",
                "A premium board layout with only the most important columns in the ideal reading order.",
                data["records"],
                [
                    ("Player / Pitcher", "player", "text"),
                    ("Team", "team", "text"),
                    ("Opponent", "opponent", "text"),
                    ("Stat Type", "stat_type", "text"),
                    ("Sportsbook Line", "sportsbook_line", "num"),
                    ("Projection", "projection", "num"),
                    ("Edge", "edge", "num"),
                    ("Confidence", "confidence", "badge"),
                    ("Recommended Play", "recommended_play", "text"),
                    ("Reason", "reason", "text"),
                ],
                "No plays are currently available.",
                "Today's board is still being generated. Check back shortly.",
            )
        )
        return render_layout(title, subtitle, body, spec["route"], nav)

    if spec_key == "pitcher_strikeouts":
        pitcher_rows = build_mlb_pitcher_projection_board()
        pitcher_extra_columns = [("Pitcher K%", "pitcher_k_percent_season", "pct"), ("Opponent Hitter K%", "opponent_hitter_k_percent", "pct")]
        body = (
            render_banner(data["banner"])
            + render_mlb_projection_cards(
                "Pitcher Projection Board",
                "Projection-first pitcher rows for strikeouts and workload-driven markets.",
                pitcher_rows,
                "mlb-pitcher-projections",
                entity_label="Pitcher",
                extra_columns=pitcher_extra_columns,
            )
        )
        return render_layout(title, subtitle, body, spec["route"], nav)

    if spec_key in {"history", "graded"}:
        body = (
            render_banner(data["banner"])
            + render_meta_strip(data)
            + render_data_table(
                "Latest Completed MLB Board" if spec_key == "history" else "Latest Graded Results",
                "Resolved bets are surfaced in a cleaner accountability-first layout.",
                data["records"],
                [
                    ("Date", "date", "text"),
                    ("Player / Pitcher", "player", "text"),
                    ("Team", "team", "text"),
                    ("Opponent", "opponent", "text"),
                    ("Stat Type", "stat_type", "text"),
                    ("Line", "line", "num"),
                    ("Projection", "projection", "num"),
                    ("Play", "play", "text"),
                    ("Actual", "actual", "num"),
                    ("Result", "result", "result"),
                ],
                "No plays are currently available.",
                "The latest completed MLB board has not been written yet. Check back shortly.",
            )
        )
        return render_layout(title, subtitle, body, spec["route"], nav)

    if spec_key == "record":
        body = (
            render_banner(data["banner"])
            + render_meta_strip(data)
            + render_performance_summary(data["summary"], "Performance Summary", "Prominent performance reporting across full history and recent windows.")
            + render_data_table(
                "Daily Market Results",
                "Daily performance by market from the tracked MLB summary file.",
                data["records"],
                [
                    ("Date", "date", "text"),
                    ("Market", "market", "text"),
                    ("Bets", "bets", "int"),
                    ("Wins", "wins", "int"),
                    ("Losses", "losses", "int"),
                    ("Pushes", "pushes", "int"),
                    ("Win Rate", "win_rate", "text"),
                ],
                "No record data is currently available.",
                "Tracked MLB record rows will appear here once the first graded results are written.",
            )
        )
        return render_layout(title, subtitle, body, spec["route"], nav)

    if spec_key == "hitter_full":
        hitter_rows = build_mlb_hitter_projection_board()
        body = (
            render_mlb_projection_cards(
                "Full Hitter Board",
                "Full slate hitter projections across all available categories, with projection kept primary and lines shown as supporting context.",
                hitter_rows,
                "mlb-hitter-full",
                entity_label="Player",
            )
        )
        return render_layout(title, subtitle, body, spec["route"], nav)

    if spec_key in {"projections", "two_plus_hits", "two_plus_bases", "rbi_targets", "hitter_strikeouts", "stolen_bases", "hr_targets"}:
        hitter_rows = build_mlb_hitter_projection_board()
        target_stat = MLB_HITTER_PAGE_STATS[spec_key]
        rows = hitter_rows
        title_map = {
            "projections": "Hitter Projection Board",
            "two_plus_hits": "2+ Hit Board",
            "two_plus_bases": "2+ Bases Board",
            "rbi_targets": "RBI Board",
            "hitter_strikeouts": "Hitter Strikeout Board",
            "stolen_bases": "Stolen Base Board",
            "hr_targets": "Home Run Board",
        }
        body = (
            render_mlb_projection_cards(
                title_map[spec_key],
                "Expanded hitter projections across the slate, with projection kept primary and lines shown as supporting context.",
                rows,
                f"mlb-{spec_key}",
                entity_label="Player",
                default_stat=target_stat,
                debug_route=spec["route"],
                debug_category=spec_key,
            )
        )
        return render_layout(title, subtitle, body, spec["route"], nav)

    if spec_key == "lines":
        body = render_data_table(
            "Current MLB Lines",
            subtitle,
            data["records"],
            [(key, key, "text") for key in (data["records"][0].keys() if data["records"] else ["Board"])],
            "No line data is currently available.",
            "The current MLB line feed has not been loaded yet.",
        )
        return render_layout(title, subtitle, body, spec["route"], nav)

    if spec_key == "injuries":
        body = (
            render_data_table(
                "Latest Hitter Tracking Snapshot",
                "Most recent hitter tracking rows.",
                data.get("hitters", []),
                [(key, key, "text") for key in (data.get("hitters", [{}])[0].keys() if data.get("hitters") else ["Board"])],
                "No hitter tracking rows are currently available.",
                "Tracking exports will populate here once available.",
            )
            + render_data_table(
                "Latest Pitcher Tracking Snapshot",
                "Most recent pitcher tracking rows.",
                data.get("pitchers", []),
                [(key, key, "text") for key in (data.get("pitchers", [{}])[0].keys() if data.get("pitchers") else ["Board"])],
                "No pitcher tracking rows are currently available.",
                "Tracking exports will populate here once available.",
            )
        )
        return render_layout(title, subtitle, body, spec["route"], nav)

    body = render_data_table(
        "MLB System Status",
        subtitle,
        data["records"],
        [("File", "file", "text"), ("Exists", "exists", "text"), ("Updated", "updated", "text"), ("Path", "path", "text")],
        "No system data is currently available.",
        "Backing file metadata will appear here once available.",
    )
    return render_layout(title, subtitle, body, spec["route"], nav)


def build_nba_dataset_page(spec_key):
    spec = NBA_PAGE_SPECS[spec_key]
    data = get_nba_dataset(spec_key)
    nav_target = spec["route"] if spec_key != "system" else "/nba"
    rows = data.get("records", [])
    columns = [(key, key, "text") for key in (rows[0].keys() if rows else ["Board"])]
    header = (
        "<section class='panel'><div class='panel-head'><div><div class='eyebrow'>NBA</div><h2>"
        + escape(spec["title"])
        + "</h2></div><p class='muted'>"
        + escape(spec["description"])
        + "</p></div></section>"
    )
    if data["kind"] == "json":
        body = header + render_json_panel(spec["title"], spec["description"], data["data"])
    elif spec_key == "record":
        body = header + render_nba_record_panel(data)
    elif spec_key == "best_bets":
        body = header + render_nba_best_bets_table(data)
    elif spec_key == "projections":
        body = (
            header
            + render_nba_projection_table(rows)
        )
    else:
        body = (
            header
            + render_data_table(spec["title"], spec["description"], rows, columns, "No NBA data is currently available.", "The latest NBA file has not been loaded yet.")
        )
    return render_layout(spec["title"], spec["description"], body, spec["route"], render_subnav(NBA_NAV_ITEMS, nav_target))


def build_ufc_dataset_page(spec_key):
    if spec_key in {"backtest"}:
        return build_ufc_home()
    spec = UFC_PAGE_SPECS[spec_key]
    data = get_ufc_dataset(spec_key)
    nav_target = spec["route"] if spec_key != "system" else "/ufc"
    header = (
        "<section class='panel'><div class='panel-head'><div><div class='eyebrow'>UFC</div><h2>"
        + escape(spec["title"])
        + "</h2></div><p class='muted'>"
        + escape(spec["description"])
        + "</p></div></section>"
    )
    if data["kind"] == "json":
        payload = data["data"] if isinstance(data["data"], dict) else {}
        body = header + render_ufc_fight_cards(payload.get("fights", []))
    elif spec_key == "props":
        body = header + render_ufc_props_table(data["records"])
    else:
        rows = data["records"]
        columns = [(key, key, "text") for key in (rows[0].keys() if rows else ["Board"])]
        body = (
            header
            + render_data_table(spec["title"], spec["description"], rows, columns, "No UFC data is currently available.", "The latest UFC file has not been loaded yet.")
        )
    return render_layout(spec["title"], spec["description"], body, spec["route"], render_subnav(UFC_NAV_ITEMS, nav_target))


def create_app():
    flask_app = Flask(__name__)

    def handle_waitlist_submission():
        form_values = {
            "name": normalize_text(request.form.get("name")),
            "email": normalize_text(request.form.get("email")),
            "message": normalize_text(request.form.get("message")),
        }
        source_page = normalize_text(request.form.get("source_page"), "/waitlist")

        if not form_values["name"] or not form_values["email"]:
            return build_waitlist_page(
                form_values=form_values,
                submit_state={"kind": "info", "message": "Please provide both your name and email to join the waitlist."},
            )

        result = save_waitlist_submission(form_values["name"], form_values["email"], form_values["message"], source_page=source_page)
        if result == "duplicate":
            return build_waitlist_page(
                form_values=form_values,
                submit_state={"kind": "info", "message": "That email is already on the waitlist. You’re all set for future launch updates."},
            )

        return build_waitlist_page(
            form_values={},
            submit_state={"kind": "success", "message": "Thanks for joining the waitlist. We’ll reach out when premium access opens."},
        )

    @flask_app.get("/brand/logo.png")
    def brand_logo():
        return send_from_directory(BRAND_ASSETS_DIR, BRAND_LOGO_FILE)

    @flask_app.get("/brand/emblem.png")
    def brand_emblem():
        return send_from_directory(BRAND_ASSETS_DIR, BRAND_LOGO_FILE)

    @flask_app.get("/api/health")
    def health():
        return jsonify({"ok": True, "timestamp": now_et().isoformat()})

    @flask_app.after_request
    def add_no_cache_headers(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @flask_app.get("/")
    def root():
        return build_home_page()

    @flask_app.get("/about")
    def about():
        return build_about_page()

    @flask_app.get("/waitlist")
    @flask_app.get("/pricing")
    @flask_app.get("/plans")
    @flask_app.get("/subscribe")
    @flask_app.get("/membership")
    def pricing():
        return build_pricing_page()

    @flask_app.post("/waitlist")
    def waitlist_submit():
        return handle_waitlist_submission()

    @flask_app.get("/results")
    def results():
        return build_results_page()

    @flask_app.get("/results/raw")
    def results_raw():
        raw_path = PROJECT_ROOT / "Best_Bets" / "results_page.html"
        try:
            html = raw_path.read_text(encoding="utf-8")
        except Exception:
            return send_from_directory(PROJECT_ROOT / "Best_Bets", "results_page.html")
        dark_css = """
<style>
html,body{background:#0a0f1c!important;color:#e5edf7!important}
body{font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif!important;margin:0!important;padding:24px!important}
.wrap,.container,.results-container,main{max-width:1200px!important;margin:0 auto!important}
.tabs{display:flex!important;gap:12px!important;margin-bottom:18px!important}
.tab-btn{appearance:none!important;border:1px solid #1e293b!important;background:#121929!important;color:#94a3b8!important;padding:10px 16px!important;border-radius:999px!important;cursor:pointer!important;font-size:14px!important}
.tab-btn.active{background:#2563eb!important;color:#fff!important;border-color:#2563eb!important;box-shadow:0 10px 24px rgba(37,99,235,0.28)!important}
.hero,.section,.card,.panel,.table-wrap,.table-container,.summary-card,.stat-card,.tabs,.tab-panel{background:#121929!important;color:#e5edf7!important;border-color:#1e293b!important;box-shadow:none!important}
table,thead,tbody,tr,th,td{background:transparent!important;color:#e5edf7!important;border-color:#1e293b!important}
th{color:#94a3b8!important}
a{color:#60a5fa!important}
</style>
"""
        if "</head>" in html:
            html = html.replace("</head>", dark_css + "</head>", 1)
        else:
            html = dark_css + html
        return Response(html, mimetype="text/html")

    @flask_app.get("/pga")
    def pga_home():
        return build_pga_page(request.args.get("round", type=int))

    @flask_app.get("/pga/best-bets")
    def pga_best_bets_page():
        return build_pga_best_bets_page(request.args.get("round", type=int))

    @flask_app.get("/pga/leaderboard")
    def pga_leaderboard_page():
        return build_pga_leaderboard_page(request.args.get("round", type=int))

    @flask_app.get("/api/pga/board")
    def pga_board_api():
        round_number = request.args.get("round", type=int)
        return jsonify(json_ready(load_pga_summary(round_number)))

    @flask_app.get("/api/pga/best-bets")
    def pga_best_bets_api():
        round_number = request.args.get("round", type=int)
        return jsonify(json_ready(load_pga_best_bets(round_number)))

    @flask_app.get("/api/pga/leaderboard")
    def pga_leaderboard_api():
        return jsonify(json_ready(load_pga_leaderboard()))

    @flask_app.get("/api/pga/player-projections")
    def pga_player_projections_api():
        return jsonify(json_ready(build_pga_player_projection_profiles()))

    @flask_app.get("/api/pga/system")
    def pga_system_api():
        return jsonify({"status": "ok", "sport": "pga", "public": True})

    @flask_app.get("/privacy-policy")
    @flask_app.get("/privacy")
    def privacy_policy():
        return build_privacy_policy_page()

    @flask_app.get("/terms")
    def terms():
        return build_terms_page()

    @flask_app.get("/disclaimer")
    def disclaimer():
        return build_disclaimer_page()

    @flask_app.get("/nba")
    def nba_home():
        return build_nba_home()

    register_wnba_routes(flask_app, render_layout, render_subnav)

    @flask_app.get("/mlb")
    def mlb_home():
        return build_mlb_home()

    @flask_app.get("/ufc")
    def ufc_home():
        return build_ufc_home()

    @flask_app.get("/api/nba/player-projections")
    def nba_player_projections_api():
        return jsonify(json_ready(build_nba_player_projection_profiles()))

    @flask_app.get("/api/mlb/player-projections")
    def mlb_player_projections_api():
        return jsonify(json_ready(build_mlb_player_projection_profiles()))

    @flask_app.get("/api/ufc/player-projections")
    def ufc_player_projections_api():
        return jsonify(json_ready(build_ufc_player_projection_profiles()))

    for key, spec in NBA_PAGE_SPECS.items():
        def nba_page(spec_key=key):
            return build_nba_dataset_page(spec_key)

        def nba_api(spec_key=key):
            if spec_key == "system":
                return jsonify({"status": "ok", "sport": "nba", "public": True})
            return jsonify(json_ready(get_nba_dataset(spec_key)))

        flask_app.add_url_rule(spec["route"], f"nba_page_{key}", nba_page)
        flask_app.add_url_rule(spec["api_route"], f"nba_api_{key}", nba_api)

    register_mlb_weather_routes(flask_app, render_layout, render_mlb_nav, render_banner, render_meta_strip, json_ready)

    for key, spec in MLB_PAGE_SPECS.items():
        def mlb_page(spec_key=key):
            return build_mlb_dataset_page(spec_key)

        def mlb_api(spec_key=key):
            if spec_key == "system":
                return jsonify({"status": "ok", "sport": "mlb", "public": True})
            return jsonify(json_ready(get_mlb_dataset(spec_key)))

        flask_app.add_url_rule(spec["route"], f"mlb_page_{key}", mlb_page)
        flask_app.add_url_rule(spec["api_route"], f"mlb_api_{key}", mlb_api)

    for key, spec in UFC_PAGE_SPECS.items():
        def ufc_page(spec_key=key):
            return build_ufc_dataset_page(spec_key)

        def ufc_api(spec_key=key):
            if spec_key == "system":
                return jsonify({"status": "ok", "sport": "ufc", "public": True})
            return jsonify(json_ready(get_ufc_dataset(spec_key)))

        flask_app.add_url_rule(spec["route"], f"ufc_page_{key}", ufc_page)
        flask_app.add_url_rule(spec["api_route"], f"ufc_api_{key}", ufc_api)

    register_auth_routes(flask_app)

    return flask_app


app = create_app()
