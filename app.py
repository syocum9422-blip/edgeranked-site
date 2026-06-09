import csv
import json
import os
import re
import time
import unicodedata
from datetime import date, datetime, timedelta
from html import escape
from math import erf, isnan, sqrt
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from flask import Flask, Response, jsonify, request, send_from_directory

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


ET = ZoneInfo("America/New_York")
MODEL_VERSION = "v2.1"
SITE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_MLB_BASE = PROJECT_ROOT.parent / "mlb_model_v2_working" / "mlb_model"
DEFAULT_UFC_BASE = PROJECT_ROOT / "data" / "ufc"
DEFAULT_MLB_SIBLING_BASE = PROJECT_ROOT.parent / "mlb_model"


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


mlb_base_env = os.environ.get("EDGERANKED_MLB_BASE_DIR")
mlb_base_candidates = [Path(mlb_base_env)] if mlb_base_env else []
mlb_base_candidates.extend([DEFAULT_MLB_SIBLING_BASE, LEGACY_MLB_BASE, PROJECT_ROOT])
MLB_OUTPUT_DIR = _resolve_first_existing_dir([base / "mlb" / "outputs" for base in mlb_base_candidates])
MLB_DATA_DIR = _resolve_first_existing_dir([base / "data" / "mlb" for base in mlb_base_candidates])
MLB_LINEUPS_FILE = _resolve_first_existing_path([base / "lineups_with_ids.csv" for base in mlb_base_candidates])

ufc_base_env = os.environ.get("EDGERANKED_UFC_BASE_DIR")
ufc_base_candidates = [Path(ufc_base_env)] if ufc_base_env else []
ufc_base_candidates.append(DEFAULT_UFC_BASE)
UFC_BASE_DIR = _resolve_first_existing_dir(ufc_base_candidates)
UFC_WEBSITE_DIR = UFC_BASE_DIR / "website"

pga_base_env = os.environ.get("EDGERANKED_PGA_BASE_DIR")
pga_base_candidates = [Path(pga_base_env)] if pga_base_env else []
pga_base_candidates.extend([
    PROJECT_ROOT.parent / "Desktop" / "pga_model",
    PROJECT_ROOT.parent / "pga_model",
])
PGA_BASE_DIR = _resolve_first_existing_dir(pga_base_candidates)
PGA_OUTPUT_DIR = PGA_BASE_DIR / "outputs"
PGA_DATA_DIR = PGA_BASE_DIR / "data"
PGA_CONFIG_PATH = PGA_BASE_DIR / "config" / "config.json"
PGA_TOURNAMENT_METADATA_PATH = PGA_DATA_DIR / "processed" / "current_tournament.json"
PGA_PROCESSED_ODDS_DIR = PGA_DATA_DIR / "processed" / "odds"
PGA_RESULTS_PATH = PGA_OUTPUT_DIR / "pga_simulation_results.csv"
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
    "fantasy": MLB_OUTPUT_DIR / "fantasy_projections_today.csv",
    "history": MLB_OUTPUT_DIR / "bet_history.csv",
    "record": MLB_OUTPUT_DIR / "daily_betting_summary.csv",
    "hitter_tracking": MLB_OUTPUT_DIR / "hitter_tracking.csv",
    "pitcher_tracking": MLB_OUTPUT_DIR / "pitcher_tracking.csv",
    "lines": MLB_DATA_DIR / "lines_today.csv",
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
    "projections": {"title": "Hitter Projections", "route": "/mlb/projections", "api_route": "/api/mlb/projections", "description": "Slate-wide hitter projection board with model projections, lines, and edges.", "kind": "mlb_hitters"},
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
    ("UFC", "/ufc"),
    ("PGA", "/pga"),
    ("Results", "/results"),
    ("Waitlist", "/waitlist"),
    ("About", "/about"),
]
NBA_NAV_ITEMS = [("Overview", "/nba"), ("Projections", "/nba/projections"), ("Results", "/nba/record"), ("Top Plays", "/nba/best-bets"), ("History", "/nba/history")]
UFC_NAV_ITEMS = [("Overview", "/ufc"), ("Fight Card", "/ufc/fights"), ("Props", "/ufc/props")]
PGA_NAV_ITEMS = [("Overview", "/pga"), ("Best Bets", "/pga/best-bets"), ("Leaderboard", "/pga/leaderboard")]
MLB_PRIMARY_NAV = [("Overview", "/mlb"), ("Top Plays", "/mlb/best-bets"), ("Weather", "/mlb/weather"), ("Pitchers", "/mlb/pitcher-strikeouts"), ("Hitters", "/mlb/projections"), ("Results", "/mlb/record")]
MLB_HITTER_NAV = [
    ("Hit Targets", "/mlb/projections"),
    ("2+ Bases", "/mlb/two-plus-bases"),
    ("RBI Targets", "/mlb/rbi-targets"),
    ("Home Runs", "/mlb/hr-targets"),
    ("Stolen Bases", "/mlb/stolen-bases"),
    ("Hitter Ks", "/mlb/hitter-strikeouts"),
]
MLB_HITTER_ROUTES = {href for _, href in MLB_HITTER_NAV}

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


def file_timestamp(path):
    path = Path(path)
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, ET)


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


def slugify_player_name(value):
    text = normalize_text(value)
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


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
    df = read_csv_df(MLB_FILES["lines"])
    if df.empty:
        return 0
    if "LEAGUE" in df.columns:
        df = df[df["LEAGUE"].astype(str).str.upper() == "MLB"].copy()
    return len(df)


def pitcher_props_scanned_count():
    df = read_csv_df(MLB_FILES["lines"])
    if df.empty:
        return 0
    work = df.copy()
    if "LEAGUE" in work.columns:
        work = work[work["LEAGUE"].astype(str).str.upper() == "MLB"].copy()
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
        "source_path": str(source_path),
        "last_updated": last_updated,
        "props_scanned": props_scanned_count(),
        "plays_shown": len(records),
        "model_version": MODEL_VERSION,
        "data_source_freshness": source_freshness_label(last_updated),
    }


# -------------------------------------------------------------------
# MLB Weather Display
# -------------------------------------------------------------------
MLB_WEATHER_PATH = SITE_ROOT / "mlb" / "outputs" / "mlb_weather_today.json"
MAX_WEATHER_AGE_HOURS = 24


def load_mlb_weather():
    """Load MLB weather data from JSON file with graceful error handling."""
    base_payload = {
        "games": [],
        "source_path": str(MLB_WEATHER_PATH),
        "last_updated": None,
        "stale": False,
    }
    if not MLB_WEATHER_PATH.exists():
        return {
            **base_payload,
            "error": "Weather data is not available yet.",
            "status": "missing",
        }

    last_updated = None
    stale = False
    try:
        stat = MLB_WEATHER_PATH.stat()
        last_updated = datetime.fromtimestamp(stat.st_mtime, tz=ET)
        age_seconds = time.time() - stat.st_mtime
        if age_seconds > MAX_WEATHER_AGE_HOURS * 3600:
            stale = True
    except Exception:
        pass

    try:
        with open(MLB_WEATHER_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {
                **base_payload,
                "error": "Weather data is not in the expected format.",
                "status": "invalid",
            }
        data["games"] = data.get("games") if isinstance(data.get("games"), list) else []
        data["source_path"] = str(MLB_WEATHER_PATH)
        data["last_updated"] = last_updated
        data["stale"] = stale
        data["status"] = "stale" if stale else "ok"
        if stale:
            data["warning"] = f"Weather data is older than {MAX_WEATHER_AGE_HOURS} hours."
        return data
    except json.JSONDecodeError as e:
        return {
            **base_payload,
            "error": f"Weather data could not be parsed: {e}",
            "status": "parse_error",
        }
    except Exception as e:
        return {
            **base_payload,
            "error": f"Weather data could not be read: {e}",
            "status": "read_error",
        }


def build_mlb_weather_page():
    """Build MLB weather display page."""
    weather = load_mlb_weather()

    games = weather.get("games", [])
    error = weather.get("error")
    warning = weather.get("warning")
    generated_at = weather.get("generated_at", "")
    slate_date = weather.get("slate_date", "")
    last_updated = weather.get("last_updated")
    generated_label = generated_at or "Not available"
    last_updated_label = last_updated.strftime("%b %-d, %-I:%M %p ET") if isinstance(last_updated, datetime) else "Not available"

    # Label colors (dark theme)
    label_colors = {
        "Power Boost": "#ef4444",
        "Run Boost": "#22c55e",
        "Pitcher Friendly": "#3b82f6",
        "Wind Suppression": "#a855f7",
        "Delay Risk": "#f59e0b",
        "Neutral": "#6b7280",
    }

    rows_html = ""
    if error:
        rows_html = f"<tr><td colspan='99' class='weather-error'>{escape(error)}</td></tr>"
    elif not games:
        rows_html = "<tr><td colspan='99' class='weather-empty'>No weather data available</td></tr>"
    else:
        for game in games:
            label = game.get("label", "Neutral")
            color = label_colors.get(label, "#6b7280")
            temp = game.get("temperature_f", "—")
            wind = game.get("wind_speed_mph", "—")
            wind_dir = game.get("wind_direction", "")
            rain = game.get("rain_chance", "—")
            summary = game.get("summary", "")
            
            home_team = game.get("home_team", "")
            home_name = game.get("home_team_name", home_team)
            away_team = game.get("away_team", "")
            away_name = game.get("away_team_name", away_team)
            venue = game.get("venue", "")
            city = game.get("city", "")
            roof = game.get("roof_type", "")

            temp_display = f"{temp}&deg;F" if temp not in ("", None, "—") else "N/A"
            wind_display = f"{wind} mph {escape(str(wind_dir))}".strip() if wind not in ("", None, "—") else "N/A"
            rain_display = f"{rain}%" if rain not in ("", None, "—") else "N/A"
            venue_meta = " · ".join([value for value in [city, roof.title() if roof else ""] if value])

            rows_html += f"""
        <tr class="weather-row">
            <td class="matchup-cell">
                <span class="team-away">{escape(away_name)}</span>
                <span class="at-symbol">@</span>
                <span class="team-home">{escape(home_name)}</span>
            </td>
            <td class="venue-cell">{escape(venue)}<span class="venue-city">{escape(venue_meta)}</span></td>
            <td class="temp-cell">{temp_display}</td>
            <td class="wind-cell">{wind_display}</td>
            <td class="rain-cell">{rain_display}</td>
            <td class="label-cell">
                <span class="weather-label" style="background:{color}">{escape(label)}</span>
            </td>
            <td class="summary-cell">{escape(summary)}</td>
        </tr>"""

    notice_html = ""
    if warning:
        notice_html = f"<div class='weather-notice'>{escape(warning)}</div>"
    elif error:
        notice_html = "<div class='weather-notice'>The Weather tab will update automatically once today's JSON is written.</div>"

    weather_cards = render_stat_cards([
        ("Games", len(games), "MLB matchups in today's weather file."),
        ("Slate Date", slate_date or "N/A", "Date attached to the weather output."),
        ("Updated", last_updated_label, "File timestamp for the current weather JSON."),
    ], compact=True)

    body = f"""
<section class="panel">
    <div class="panel-head">
        <div>
            <div class="eyebrow">MLB Weather</div>
            <h2>Today's Game Weather</h2>
        </div>
        <p class="muted">Ballpark conditions for today's MLB slate.</p>
    </div>
    {weather_cards}
    <div class="meta-strip">
        <span>Generated: {escape(str(generated_label))}</span>
        <span>Source: {escape(str(weather.get('source', 'Weather JSON')))}</span>
    </div>
    {notice_html}
</section>
<section class="panel">
    <div class="table-shell">
        <table class="mlb-weather-table">
            <thead>
                <tr>
                    <th>Matchup</th>
                    <th>Venue</th>
                    <th>Temp</th>
                    <th>Wind</th>
                    <th>Rain</th>
                    <th>Label</th>
                    <th>Summary</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </div>
</section>
<style>
.mlb-weather-table {{ width: 100%; font-size: 13px; }}
.mlb-weather-table th {{ text-align: left; padding: 12px 16px; border-bottom: 2px solid var(--line); color: var(--accent); font-weight: 600; }}
.mlb-weather-table td {{ padding: 14px 16px; border-bottom: 1px solid rgba(255,255,255,0.06); vertical-align: middle; }}
.weather-row:hover {{ background: rgba(255,255,255,0.03); }}
.matchup-cell {{ white-space: nowrap; }}
.team-away {{ color: var(--text-muted); }}
.at-symbol {{ color: var(--text-muted); margin: 0 6px; }}
.team-home {{ font-weight: 600; }}
.venue-cell {{ color: var(--text-secondary); font-size: 12px; }}
.venue-city {{ display: block; font-size: 11px; color: var(--text-muted); }}
.temp-cell, .wind-cell, .rain-cell {{ text-align: center; font-variant-numeric: tabular-nums; }}
.weather-label {{ display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; color: white; text-transform: uppercase; letter-spacing: 0.03em; }}
.summary-cell {{ color: var(--text-secondary); font-size: 12px; max-width: 200px; }}
.weather-error, .weather-empty {{ text-align: center; padding: 40px; color: var(--text-muted); }}
.meta-strip {{ font-size: 12px; color: var(--text-muted); display: flex; flex-wrap: wrap; gap: 12px; margin-top: 12px; }}
.weather-notice {{ margin-top: 14px; padding: 12px 14px; border: 1px solid rgba(245,158,11,0.25); border-radius: 8px; color: #fbbf24; background: rgba(245,158,11,0.08); font-size: 13px; }}
</style>
"""
    return render_layout(
        "MLB Weather",
        "Ballpark weather conditions for today's MLB slate",
        body,
        "/mlb/weather",
        render_mlb_nav("/mlb/weather")
    )


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
        "source_path": str(source_path),
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
        "source_path": str(source_path),
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
        "source_path": str(source_path),
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
        "source_path": str(MLB_FILES["record"]),
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
    if kind == "mlb_hitters":
        prob_col = "Hit Probability"
        category_match = "HIT TARGETS"
        keep = [hitter_col, pitcher_col, "Hit Probability", "Total Bases >= 2", "Home Run Probability", "Stolen Base Probability"]
        rename = {"Hit Probability": "Hit %", "Total Bases >= 2": "2+ Bases %", "Home Run Probability": "HR %", "Stolen Base Probability": "SB %"}
    elif kind == "mlb_tb2":
        prob_col = "Total Bases >= 2"
        category_match = "2+ TOTAL BASES TARGETS"
        keep = [hitter_col, pitcher_col, "Total Bases >= 2", "Hit Probability", "Home Run Probability"]
        rename = {"Total Bases >= 2": "2+ Bases %", "Hit Probability": "Hit %", "Home Run Probability": "HR %"}
    elif kind == "mlb_rbi":
        prob_col = "RBI Probability"
        category_match = "RBI TARGETS"
        keep = [hitter_col, pitcher_col, "RBI Probability", "Hit Probability", "Home Run Probability"]
        rename = {"RBI Probability": "RBI %", "Hit Probability": "Hit %", "Home Run Probability": "HR %"}
    elif kind == "mlb_hitter_k":
        prob_col = "Hitter Strikeout %"
        category_match = "HITTER STRIKEOUT TARGETS"
        keep = [hitter_col, pitcher_col, "Hitter Strikeout %", "Projected Hitter Strikeouts", "Hit Probability"]
        rename = {"Hitter Strikeout %": "K %", "Projected Hitter Strikeouts": "Projected K", "Hit Probability": "Hit %"}
    elif kind == "mlb_sb":
        prob_col = "Stolen Base Probability"
        category_match = "STOLEN BASE TARGETS"
        keep = [hitter_col, pitcher_col, "Stolen Base Probability", "Hit Probability", "Hitter Strikeout %"]
        rename = {"Stolen Base Probability": "SB %", "Hit Probability": "Hit %", "Hitter Strikeout %": "K %"}
    else:
        prob_col = "Home Run Probability"
        category_match = "HOME RUN TARGETS"
        keep = [hitter_col, pitcher_col, "Home Run Probability", "Hit Probability", "Total Bases >= 2"]
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
    work = work[keep].head(25).rename(columns={hitter_col: "Hitter", pitcher_col: "Pitcher", **rename})
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


def build_mlb_line_lookup():
    df = read_csv_df(MLB_FILES["lines"])
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


def build_mlb_hitter_projection_board():
    summary_df = read_csv_df(MLB_FILES["hitters"])
    if summary_df.empty:
        return []

    hitter_col = find_first_column(summary_df, ["Hitter", "hitter_name", "player_name"])
    pitcher_col = find_first_column(summary_df, ["Pitcher", "pitcher_name", "matchup_pitcher"])
    team_col = find_first_column(summary_df, ["Team", "team", "TEAM"])
    opponent_col = find_first_column(summary_df, ["Opponent", "opponent", "opp", "matchup"])
    if not hitter_col:
        return []

    line_lookup, opponent_lookup = build_mlb_line_lookup()
    hitter_context_lookup = build_mlb_hitter_context_lookup()
    team_lookup = build_mlb_hitter_team_lookup()
    pitcher_context_lookup = build_mlb_pitcher_context_lookup()

    stat_configs = [
        ("Hits", "Hit Probability", "HIT", None),
        ("2+ Bases", "Total Bases >= 2", "TB", None),
        ("RBI", "RBI Probability", "RBI", None),
        ("Home Runs", "Home Run Probability", "HR", None),
        ("Stolen Bases", "Stolen Base Probability", "SB", None),
        ("Hitter Strikeouts", "Projected Hitter Strikeouts", "K", None),
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
                continue
            projection = safe_float(row.get(prob_col))
            if projection is None:
                continue
            line = line_lookup.get((player_key, stat_code), default_line)
            inferred_team = mlb_clean_text(pitcher_context.get("pitcher_opponent"), fallback="")
            inferred_opponent = mlb_clean_text(pitcher_context.get("pitcher_team"), fallback="")
            context_team = mlb_clean_text(hitter_context.get("team"), fallback="")
            context_opponent = mlb_clean_text(hitter_context.get("opponent"), fallback="")
            resolved_team = source_team or context_team or mlb_clean_text(team_lookup.get(player_key), fallback="") or inferred_team
            opponent = source_opponent or context_opponent or opponent_lookup.get((player_key, stat_code), "") or inferred_opponent or opponent_pitcher
            if stat_label == "Hitter Strikeouts":
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
                "sort_projection": projection,
                "sort_edge": abs(safe_float(edge, default=0)),
                "sort_confidence": confidence_rank(confidence),
            }
            key = (player_key, stat_label)
            current = records_by_key.get(key)
            if not current or record["sort_projection"] > current["sort_projection"]:
                records_by_key[key] = record

    records = list(records_by_key.values())
    fantasy_rows = load_mlb_fantasy_projection_rows()
    if fantasy_rows:
        records.extend(fantasy_rows)
        records = ensure_mlb_minimum_team_players(records, fantasy_rows, min_players=3)
    records.sort(key=lambda item: (item["sort_projection"], item["sort_edge"]), reverse=True)
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


def collect_mlb_player_slugs():
    slugs = {}
    for row in build_mlb_hitter_projection_board():
        name = normalize_text(row.get("player"))
        slug = slugify_player_name(name)
        if slug:
            slugs.setdefault(slug, name)
    for row in build_mlb_pitcher_projection_board():
        name = normalize_text(row.get("player"))
        slug = slugify_player_name(name)
        if slug:
            slugs.setdefault(slug, name)
    return slugs


def build_mlb_player_profile(slug):
    target = slugify_player_name(slug)
    if not target:
        return None

    hitter_rows = [
        row for row in build_mlb_hitter_projection_board()
        if slugify_player_name(row.get("player")) == target
    ]
    pitcher_rows = [
        row for row in build_mlb_pitcher_projection_board()
        if slugify_player_name(row.get("player")) == target
    ]
    if not hitter_rows and not pitcher_rows:
        return None

    name = ""
    team = ""
    opponent = ""
    for row in hitter_rows + pitcher_rows:
        name = name or normalize_text(row.get("player"))
        team = team or normalize_text(row.get("team"))
        opponent = opponent or normalize_text(row.get("opponent"))

    best_confidence = ""
    best_rank = -1
    for row in hitter_rows + pitcher_rows:
        rank = confidence_rank(row.get("confidence"))
        if rank > best_rank:
            best_rank = rank
            best_confidence = confidence_level(row.get("confidence"))

    source_paths = []
    if hitter_rows:
        source_paths.append(MLB_FILES["hitters"])
    if pitcher_rows:
        source_paths.append(MLB_FILES["pitchers"])
    timestamps = [ts for ts in (file_timestamp(path) for path in source_paths) if ts]
    last_updated = max(timestamps) if timestamps else None

    return {
        "slug": target,
        "name": name,
        "team": team,
        "opponent": opponent,
        "confidence": best_confidence,
        "hitter_rows": hitter_rows,
        "pitcher_rows": pitcher_rows,
        "last_updated": last_updated,
    }


def render_mlb_player_projection_card(heading, eyebrow, rows, is_hitter):
    if not rows:
        return ""
    body_rows = []
    for row in rows:
        stat = escape(normalize_text(row.get("stat")) or "—")
        if is_hitter:
            projection = normalize_text(row.get("projection_display")) or metric_label(row.get("projection"))
        else:
            projection = metric_label(row.get("projection"))
        line = row.get("line")
        line_display = metric_label(line) if line is not None else "—"
        confidence_badge = render_mlb_confidence_badge(row.get("confidence"))
        body_rows.append(
            "<tr>"
            f"<td data-label='Stat'>{stat}</td>"
            f"<td data-label='Today’s Projection'><strong>{escape(projection)}</strong></td>"
            f"<td data-label='Line'>{escape(line_display)}</td>"
            f"<td data-label='Confidence'>{confidence_badge}</td>"
            "</tr>"
        )
    return (
        "<section class='panel'>"
        f"<div class='panel-head'><div><div class='eyebrow'>{escape(eyebrow)}</div><h2>{escape(heading)}</h2></div>"
        "<p class='muted'>Today’s model projections. Projection is primary; any line is shown as supporting context.</p></div>"
        "<div class='table-shell'><table><thead><tr>"
        "<th>Stat</th><th>Today’s Projection</th><th>Line</th><th>Confidence</th>"
        "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div></section>"
    )


def build_mlb_player_not_found_page(slug):
    body = (
        render_empty_state(
            "Player Not Found",
            "We couldn’t find today’s projection for that player.",
            "This player may not be on today’s MLB slate. Browse the full hitter and pitcher boards for current projections.",
        )
        + render_page_actions([
            ("View Hitter Projections", "/mlb/projections", "secondary"),
            ("View Pitcher Projections", "/mlb/pitcher-strikeouts", "secondary"),
        ])
    )
    return (
        render_layout(
            "Player Not Found",
            "The requested MLB player profile is not available on today’s slate.",
            body,
            "/mlb",
            render_mlb_nav("/mlb"),
            hero_kicker="MLB Players",
            document_title="Player Not Found | EdgeRanked AI",
            meta_description="The requested EdgeRanked AI MLB player projection page is not available on today’s slate.",
        ),
        404,
    )


def build_mlb_player_page(slug):
    profile = build_mlb_player_profile(slug)
    if profile is None:
        return build_mlb_player_not_found_page(slug)

    name = profile["name"]
    team = profile["team"]
    opponent = profile["opponent"]

    matchup = ""
    if team and opponent:
        matchup = f"{team} vs {opponent}"
    elif team:
        matchup = team
    elif opponent:
        matchup = f"vs {opponent}"

    summary_cards = [
        ("Team", team or "TBD", "Current team on today’s MLB slate."),
        ("Opponent", opponent or "TBD", "Today’s opposing matchup."),
    ]
    if profile["confidence"]:
        summary_cards.append((
            "Model Confidence",
            profile["confidence"],
            "Highest model confidence across today’s projected markets.",
        ))
    summary_cards.append((
        "Last Updated",
        format_timestamp(profile["last_updated"]),
        "When the backing MLB projection files were last refreshed.",
    ))

    intro = (
        "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Today’s Projection</div>"
        f"<h2>{escape(name)}</h2></div>"
        f"<p class='muted'>{escape('Today’s EdgeRanked AI model projections for ' + name + ((' — ' + matchup) if matchup else '') + '.')}</p></div>"
        + render_stat_cards(summary_cards)
        + "</section>"
    )

    hitter_card = render_mlb_player_projection_card(
        f"{name} — Hitter Projections", "Hitter", profile["hitter_rows"], is_hitter=True
    )
    pitcher_card = render_mlb_player_projection_card(
        f"{name} — Pitcher Projections", "Pitcher", profile["pitcher_rows"], is_hitter=False
    )

    actions = render_page_actions([
        ("All Hitter Projections", "/mlb/projections", "secondary"),
        ("All Pitcher Projections", "/mlb/pitcher-strikeouts", "secondary"),
    ])

    body = intro + hitter_card + pitcher_card + actions

    document_title = f"{name} Projection Today | EdgeRanked AI"
    meta_description = (
        f"View today’s {name} projections, matchup data, probabilities, "
        "and model confidence from EdgeRanked AI."
    )
    subtitle = f"Today’s EdgeRanked AI projections for {name}" + (f" ({matchup})." if matchup else ".")

    return render_layout(
        name,
        subtitle,
        body,
        "/mlb",
        render_mlb_nav("/mlb"),
        hero_kicker="MLB Player",
        document_title=document_title,
        meta_description=meta_description,
    )


def build_mlb_players_sitemap():
    base_url = "https://edgerankedai.com"
    slugs = collect_mlb_player_slugs()
    lastmod = None
    for path in (MLB_FILES["hitters"], MLB_FILES["pitchers"]):
        ts = file_timestamp(path)
        if ts and (lastmod is None or ts > lastmod):
            lastmod = ts
    lastmod_tag = f"<lastmod>{lastmod.date().isoformat()}</lastmod>" if lastmod else ""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for slug in sorted(slugs):
        lines.append(f"  <url><loc>{base_url}/mlb/player/{escape(slug)}</loc>{lastmod_tag}</url>")
    lines.append("</urlset>")
    return Response("\n".join(lines), mimetype="application/xml")


def mlb_system_rows():
    rows = []
    for label, path in MLB_FILES.items():
        rows.append({
            "file": label,
            "exists": "Yes" if path.exists() else "No",
            "path": str(path),
            "updated": format_timestamp(file_timestamp(path)),
        })
    return rows


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
            "source_path": str(source_path),
            "last_updated": file_timestamp(source_path),
            "plays_shown": 0,
            "recent_hit_rate": None,
            "banner": "",
        }

    work = df.copy()
    work["ABS_EDGE_SORT"] = pd.to_numeric(work.get("ABS_EDGE"), errors="coerce").fillna(0)
    work["BET_CONFIDENCE_SORT"] = pd.to_numeric(work.get("BET_CONFIDENCE"), errors="coerce").fillna(0)
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
        "source_path": str(source_path),
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
        "source_path": str(Path(RECORD_SUMMARY_PATH)),
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
    rounds = []
    for round_number in range(1, 5):
        if (PGA_OUTPUT_DIR / f"best_bets_R{round_number}.json").exists():
            rounds.append(round_number)
    return sorted(rounds)


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
    selected_round = round_number if round_number in available_rounds else (max(available_rounds) if available_rounds else None)
    candidates = []
    if selected_round is not None:
        candidates.append((PGA_OUTPUT_DIR / f"best_bets_R{selected_round}.json", selected_round))
    if not round_only:
        candidates.append((PGA_OUTPUT_DIR / "best_bets.json", None))

    for path, fallback_round in candidates:
        payload = read_json(path)
        if isinstance(payload, list) and payload:
            records = [record for record in (normalize_pga_best_bet_record(item, fallback_round=fallback_round) for item in payload) if record]
            if not records:
                fallback_props = load_pga_available_props(selected_round if fallback_round is not None else round_number)
                if fallback_props:
                    return {
                        "records": fallback_props,
                        "source_path": str(path),
                        "last_updated": file_timestamp(path),
                        "selected_round": selected_round if fallback_round is not None else None,
                        "is_round_specific": fallback_round is not None,
                        "is_available_props": True,
                    }
                continue
            return {
                "records": records,
                "source_path": str(path),
                "last_updated": file_timestamp(path),
                "selected_round": selected_round if fallback_round is not None else None,
                "is_round_specific": fallback_round is not None,
                "is_available_props": False,
            }
    empty_source = str(candidates[0][0]) if candidates else str(PGA_OUTPUT_DIR / "best_bets_R1.json")
    fallback_props = load_pga_available_props(selected_round)
    if fallback_props:
        return {
            "records": fallback_props,
            "source_path": empty_source,
            "last_updated": None,
            "selected_round": selected_round,
            "is_round_specific": False,
            "is_available_props": True,
        }
    return {
        "records": [],
        "source_path": empty_source,
        "last_updated": None,
        "selected_round": selected_round,
        "is_round_specific": False,
        "is_available_props": False,
    }


def load_pga_leaderboard():
    df = read_csv_df(PGA_RESULTS_PATH)
    if df.empty:
        return {"records": [], "source_path": str(PGA_RESULTS_PATH), "last_updated": file_timestamp(PGA_RESULTS_PATH)}

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
        "source_path": str(PGA_RESULTS_PATH),
        "last_updated": file_timestamp(PGA_RESULTS_PATH),
    }


def load_pga_summary(round_number=None):
    metadata = read_json(PGA_TOURNAMENT_METADATA_PATH)
    config = read_json(PGA_CONFIG_PATH)
    available_rounds = pga_available_rounds()
    selected_round = round_number if round_number in available_rounds else (max(available_rounds) if available_rounds else None)
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
        "favorite": favorite,
        "top_bet": top_bet,
    }


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
        "<div><span>EdgeRankedSportsAI</span><div class='footer-note'>Premium memberships coming soon</div></div>"
        "</div>"
        "<div class='footer-links'>"
        "<a href='/about'>About</a>"
        "<a href='/privacy-policy'>Privacy Policy</a>"
        "<a href='/terms'>Terms of Use</a>"
        "<a href='/disclaimer'>Disclaimer</a>"
        f"<a href='mailto:{SUPPORT_EMAIL}'>Contact</a>"
        "</div>"
        f"<p class='footer-copy'>&copy; {year} EdgeRanked AI. All rights reserved.</p>"
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
    label = {"High": "Top Signal", "Medium": "Strong Signal", "Low": "In Range"}.get(tier, "In Range")
    return f"<span class='badge badge-{tier.lower()}'>{escape(label)}</span>"


def render_mlb_projection_table(title, subtitle, rows, scope_id, entity_label="Player", include_lean=True, include_search=False, extra_columns=None, initial_limit=30, default_stat=None, min_team_rows=3):
    if not rows:
        return render_empty_state(
            title,
            f"No {title.lower()} are currently available.",
            "The latest MLB projection files are still being generated. Check back shortly.",
        )
    extra_columns = extra_columns or []

    team_options = sorted({normalize_text(row.get("team")).upper() for row in rows if normalize_text(row.get("team"))})
    stat_options = sorted({normalize_text(row.get("stat")) for row in rows if normalize_text(row.get("stat"))})
    sort_options = [
        ("projection", "Highest Projection"),
        ("edge", "Highest Edge"),
        ("confidence", "Confidence"),
        ("player", entity_label),
        ("team", "Team"),
        ("stat", "Stat"),
    ]
    team_select = "".join(f"<option value='{escape(team)}'>{escape(team)}</option>" for team in team_options)
    stat_select = "".join(f"<option value='{escape(stat)}'>{escape(stat)}</option>" for stat in stat_options)
    sort_select = "".join(f"<option value='{escape(value)}'>{escape(label)}</option>" for value, label in sort_options)

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
        player_slug = slugify_player_name(player)
        player_label = escape(player or entity_label)
        player_cell = (
            f"<a class='player-link' href='/mlb/player/{player_slug}'><strong>{player_label}</strong></a>"
            if player and player_slug else f"<strong>{player_label}</strong>"
        )
        cells = [
            f"<td data-label='{escape(entity_label)}'>{player_cell}</td>",
            f"<td data-label='Team'>{escape(team or '—')}</td>",
            f"<td data-label='Opponent'>{escape(opponent)}</td>",
            f"<td data-label='Stat'>{escape(stat or 'N/A')}</td>",
            f"<td data-label='Projection'><strong>{escape(normalize_text(row.get('projection_display')) or metric_label(projection))}</strong></td>",
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
            cells.append(f"<td data-label='Lean'>{escape(lean or 'Lean')}</td>")
        body_rows.append(
            "<tr "
            f"data-player='{escape(player.lower())}' "
            f"data-team='{escape(team)}' "
            f"data-team-key='{escape(team_key)}' "
            f"data-stat='{escape(stat.lower())}' "
            f"data-projection='{safe_float(row.get('sort_projection'), default=-9999)}' "
            f"data-edge='{safe_float(row.get('sort_edge'), default=0)}' "
            f"data-confidence='{safe_float(row.get('sort_confidence'), default=0)}'>"
            + "".join(cells)
            + "</tr>"
        )

    lean_header = "<th>Lean</th>" if include_lean else ""
    extra_headers = "".join(f"<th>{escape(label)}</th>" for label, _, _ in extra_columns)
    return (
        "<section class='panel'>"
        f"<div class='panel-head'><div><div class='eyebrow'>MLB</div><h2>{escape(title)}</h2></div>"
        f"<p class='muted'>{escape(subtitle)}</p></div>"
        "<div class='filter-toolbar'>"
        + (
            f"<label class='filter-field'><span>Search {escape(entity_label.lower())}</span><input id='{escape(scope_id)}-search' type='search' placeholder='Search by name'></label>"
            if include_search else ""
        )
        + f"<label class='filter-field'><span>Team</span><select id='{escape(scope_id)}-team'><option value='ALL'>All Teams</option>{team_select}</select></label>"
        f"<label class='filter-field'><span>Stat</span><select id='{escape(scope_id)}-stat'><option value='ALL'>All Stats</option>{stat_select}</select></label>"
        f"<label class='filter-field'><span>Sort By</span><select id='{escape(scope_id)}-sort'>{sort_select}</select></label>"
        f"<label class='filter-field'><span>Direction</span><select id='{escape(scope_id)}-direction'><option value='desc'>High to Low</option><option value='asc'>Low to High</option></select></label>"
        "</div>"
        f"<p class='muted projection-summary' id='{escape(scope_id)}-summary'>Showing {len(rows)} rows.</p>"
        f"<div class='table-shell'><table id='{escape(scope_id)}-table'><thead><tr>"
        f"<th>{escape(entity_label)}</th><th>Team</th><th>Opponent</th><th>Stat</th><th>Projection</th>{extra_headers}<th>Confidence</th>{lean_header}"
        "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div></section>"
        + f"""
<script>
(() => {{
  const table = document.getElementById("{scope_id}-table");
  if (!table) return;
  const tbody = table.querySelector("tbody");
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const search = document.getElementById("{scope_id}-search");
  const team = document.getElementById("{scope_id}-team");
  const stat = document.getElementById("{scope_id}-stat");
  const sort = document.getElementById("{scope_id}-sort");
  const direction = document.getElementById("{scope_id}-direction");
  const summary = document.getElementById("{scope_id}-summary");
  const initialLimit = {int(initial_limit)};
  const defaultStat = {json.dumps(default_stat or "")};
  const minTeamRows = {int(min_team_rows)};

    function normalizeKey(value) {{
      return (value || "").toString().toLowerCase().replace(/[^a-z0-9]/g, "");
    }}

    function value(row, key) {{
      return (row.dataset[key] || "").toString();
    }}

    function numericValue(row, key) {{
      const parsed = Number.parseFloat(value(row, key));
      return Number.isNaN(parsed) ? -9999 : parsed;
    }}

  function apply() {{
    const query = search ? (search.value || "").trim().toLowerCase() : "";
    const teamValue = (team.value || "ALL").toUpperCase();
    const teamKey = normalizeKey(teamValue);
    const statValue = (stat.value || "ALL").toLowerCase();
    const sortKey = sort.value || "projection";
    const dir = direction.value === "asc" ? 1 : -1;

    const matched = rows.filter((row) => {{
      const matchesQuery = !query || value(row, "player").includes(query);
      const rowTeam = value(row, "team").toUpperCase();
      const rowTeamKey = value(row, "teamKey") || normalizeKey(rowTeam);
      const matchesTeam = teamValue === "ALL" || rowTeam === teamValue || rowTeamKey === teamKey;
      const matchesStat = statValue === "ALL" || value(row, "stat") === statValue;
      return matchesQuery && matchesTeam && matchesStat;
    }});

    if (teamValue !== "ALL" && statValue !== "ALL" && matched.length < minTeamRows) {{
      const seen = new Set(matched);
      const supplemental = rows.filter((row) => {{
        if (seen.has(row)) return false;
        const rowTeam = value(row, "team").toUpperCase();
        const rowTeamKey = value(row, "teamKey") || normalizeKey(rowTeam);
        const matchesTeam = rowTeam === teamValue || rowTeamKey === teamKey;
        const matchesQuery = !query || value(row, "player").includes(query);
        return matchesTeam && matchesQuery;
      }});
      for (const row of supplemental) {{
        matched.push(row);
        if (matched.length >= minTeamRows) break;
      }}
    }}

    matched.sort((a, b) => {{
      if (sortKey === "player" || sortKey === "team" || sortKey === "stat") {{
        const primary = value(a, sortKey).localeCompare(value(b, sortKey)) * dir;
        if (primary !== 0) return primary;
        return value(a, "player").localeCompare(value(b, "player"));
      }}
      const primary = (numericValue(a, sortKey) - numericValue(b, sortKey)) * dir;
      if (primary !== 0) return primary;
      return value(a, "player").localeCompare(value(b, "player"));
    }});

    const limitApplies = !query && teamValue === "ALL" && statValue === "ALL" && initialLimit > 0;
    const visible = limitApplies ? matched.slice(0, initialLimit) : matched;

    rows.forEach((row) => {{
      const show = visible.includes(row);
      row.hidden = !show;
      row.style.display = show ? "" : "none";
    }});

    visible.forEach((row) => tbody.appendChild(row));

    const parts = [limitApplies ? `Showing ${{visible.length}} of ${{matched.length}} rows` : `Showing ${{visible.length}} rows`];
    if (query) parts.push(`search: ${{query}}`);
    if (teamValue !== "ALL") parts.push(`team: ${{teamValue}}`);
    if (statValue !== "ALL" && stat.selectedIndex >= 0) parts.push(`stat: ${{stat.options[stat.selectedIndex].text}}`);
    if (sort.selectedIndex >= 0) parts.push(`sorted by ${{sort.options[sort.selectedIndex].text.toLowerCase()}}`);
    if (limitApplies) parts.push("top rows shown by default");
    summary.textContent = parts.join(" | ");
  }}

  [search, team, stat, sort, direction].filter(Boolean).forEach((control) => {{
    control.addEventListener("input", apply);
    control.addEventListener("change", apply);
  }});

  if (defaultStat && stat) {{
    const option = Array.from(stat.options).find((item) => item.text.toLowerCase() === defaultStat.toLowerCase() || item.value.toLowerCase() === defaultStat.toLowerCase());
    if (option) {{
      stat.value = option.value;
    }}
  }}

  apply();
}})();
</script>
"""
    )


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
            "</article>"
        )
    return "<section class='panel'><div class='panel-head'><div><div class='eyebrow'>Fight Card</div><h2>Current UFC card</h2></div><p class='muted'>Simple model probabilities for the current published card.</p></div><div class='play-grid-shell'>" + "".join(cards) + "</div></section>"


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


def render_ufc_props_table(rows):
    preferred = []
    fallback = []
    for row in rows:
        source = normalize_text(row.get("source")).lower()
        market_type = normalize_text(row.get("market_type")).lower()
        line_value = safe_float(row.get("line"))
        if market_type == "total_rounds" and line_value is not None and line_value > 3.5:
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
            f"data-player='{escape(row['player'].lower())}' "
            f"data-team='{escape(row['team'])}' "
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
        "</section>"
        """
<script>
(() => {
  const table = document.getElementById("nba-projection-table");
  if (!table) return;

  const tbody = table.querySelector("tbody");
  const rows = Array.from(tbody.querySelectorAll("tr"));
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
    const team = (teamFilter.value || "ALL").toUpperCase();
    const stat = (statFilter.value || "ALL").toUpperCase();
    const sortKey = sortField.value || "projection";
    const direction = sortDirection.value === "asc" ? 1 : -1;

    const visibleRows = rows.filter((row) => {
      const matchesTeam = team === "ALL" || (row.dataset.team || "").toUpperCase() === team;
      const matchesStat = stat === "ALL" || (row.dataset.stat || "").toUpperCase() === stat;
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

    rows.forEach((row) => {
      row.hidden = true;
      row.style.display = "none";
    });
    visibleRows.forEach((row) => {
      row.hidden = false;
      row.style.display = "";
      tbody.appendChild(row);
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

    metrics_html = render_stat_cards([
        ("All-Time Record", f"{summary.get('wins', 0)}-{summary.get('losses', 0)}", "Verified graded outcomes across the tracked NBA history file."),
        ("Win Rate", pct_label(summary.get("win_rate")), "Calculated from graded wins and losses only."),
        ("Last 7 Days", summary.get("recent7", {}).get("record", "0-0"), "Recent graded record."),
        ("Last 14 Days", summary.get("recent14", {}).get("record", "0-0"), "Mid-window accountability check."),
        ("Last 30 Days", summary.get("recent30", {}).get("record", "0-0"), "Longer trend from the tracked history export."),
        ("Last Updated", format_timestamp(record_data.get("last_updated")), "Freshness of the record and history backing files."),
    ])

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
        + metrics_html
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


def render_layout(title, subtitle, body_html, active_path, section_nav=None, hero_kicker=None, hero_media_html="", is_home=False, meta_description=None, document_title=None):
    section_nav_html = section_nav or ""
    kicker = hero_kicker or "Premium Sports Analytics"
    head_title = document_title or title
    meta_description_tag = (
        f'\n  <meta name="description" content="{escape(meta_description)}">'
        if meta_description else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(head_title)}</title>{meta_description_tag}
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-L9N5JKN47H"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', 'G-L9N5JKN47H');
  </script>
  <style>
    :root {{
      --bg: #0a0f1c;
      --surface: #121929;
      --surface-strong: #0f1725;
      --surface-soft: rgba(18, 25, 41, 0.88);
      --ink: #e5edf7;
      --muted: #94a3b8;
      --line: #1e293b;
      --accent: #3b82f6;
      --accent-strong: #2563eb;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --shadow: 0 18px 48px rgba(2, 8, 23, 0.42);
      --radius-xl: 24px;
      --radius-lg: 20px;
      --radius-md: 14px;
    }}
    * {{ box-sizing: border-box; }}
    html {{ background: var(--bg); }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at top center, rgba(59, 130, 246, 0.12), transparent 28%),
        radial-gradient(circle at bottom right, rgba(16, 185, 129, 0.07), transparent 24%),
        var(--bg);
      color: var(--ink);
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    a {{ color: inherit; }}
    .player-link {{ color: var(--accent); text-decoration: none; }}
    .player-link:hover {{ text-decoration: underline; }}
    img {{ display: block; }}
    .site-nav {{
      position: sticky;
      top: 0;
      z-index: 50;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      background: rgba(10, 15, 28, 0.75);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
    }}
    .nav-shell, .shell, .footer-shell {{
      width: min(1280px, calc(100% - 32px));
      margin: 0 auto;
    }}
    .nav-shell {{
      min-height: 72px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 12px 0;
    }}
    .nav-brand {{
      display: inline-flex;
      align-items: center;
      gap: 12px;
      text-decoration: none;
    }}
    .nav-logo {{
      width: 36px;
      height: 36px;
      object-fit: contain;
    }}
    .nav-wordmark {{
      color: #fff;
      font-size: 20px;
      font-weight: 800;
      letter-spacing: -0.03em;
      white-space: nowrap;
    }}
    .brand-accent {{ color: var(--accent); }}
    .beta-pill {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid rgba(59, 130, 246, 0.24);
      background: rgba(59, 130, 246, 0.12);
      color: #dbeafe;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      white-space: nowrap;
    }}
    .shell {{
      padding: 32px 0 56px;
    }}
    .hero {{
      position: relative;
      overflow: hidden;
      background: linear-gradient(180deg, rgba(18,25,41,0.96), rgba(10,15,28,0.96));
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      border-radius: var(--radius-xl);
      padding: 28px;
      margin-bottom: 22px;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -4% -36% auto;
      width: 360px;
      height: 360px;
      background: radial-gradient(circle, rgba(59,130,246,0.14) 0%, transparent 72%);
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
      gap: 8px;
    }}
    .top-link, .sub-link, .cta-btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      text-decoration: none;
      border-radius: 10px;
      border: 1px solid var(--line);
      padding: 10px 14px;
      font-size: 13px;
      font-weight: 700;
      background: rgba(18, 25, 41, 0.9);
      color: var(--muted);
      transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
    }}
    .top-link:hover, .sub-link:hover, .cta-btn:hover {{
      transform: translateY(-1px);
      border-color: rgba(59, 130, 246, 0.32);
      color: #fff;
    }}
    .top-link.active, .sub-link.active, .cta-btn.primary {{
      color: #fff;
      background: var(--surface);
      border-color: var(--line);
    }}
    .cta-btn.secondary {{
      background: rgba(18, 25, 41, 0.9);
      color: #fff;
      border-color: var(--line);
    }}
    .hero-copy {{
      max-width: 760px;
      margin-bottom: 18px;
    }}
    h1, h2, h3, p {{ margin: 0; }}
    h1 {{
      font-size: clamp(38px, 6vw, 64px);
      line-height: 1.02;
      letter-spacing: -0.04em;
      margin-bottom: 12px;
      max-width: 13ch;
      color: #fff;
    }}
    h2 {{
      font-size: clamp(24px, 3vw, 34px);
      line-height: 1.05;
      letter-spacing: -0.03em;
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
      font-size: 16px;
      max-width: 62ch;
    }}
    .cta-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }}
    .hero-kicker, .eyebrow, .pricing-kicker {{
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 8px;
    }}
    .hero-emblem {{
      width: 82px;
      height: auto;
      margin: 0 0 20px;
      filter: drop-shadow(0 0 16px rgba(59,130,246,0.28));
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
      gap: 14px;
    }}
    .metric-grid.compact {{
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    }}
    .metric-card {{
      background: rgba(10, 15, 28, 0.85);
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
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }}
    .resource-card {{
      display: block;
      text-decoration: none;
      background: rgba(18, 25, 41, 0.9);
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
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
    .filter-reset-btn {{
      width: 100%;
      min-height: 50px;
    }}
    .projection-summary {{
      margin-bottom: 16px;
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
      padding: 28px 0 40px;
      background: rgba(10, 15, 28, 0.94);
    }}
    .footer-shell {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
    }}
    .footer-brand {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      color: #fff;
      font-weight: 800;
    }}
    .footer-note {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }}
    .footer-logo {{
      width: 28px;
      height: 28px;
      object-fit: contain;
    }}
    .footer-links {{
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 18px;
      color: var(--muted);
      font-size: 14px;
    }}
    .footer-links a {{
      text-decoration: none;
    }}
    .footer-links a:hover {{
      color: #fff;
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
        gap: 12px;
        padding: 0;
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
        flex-direction: column;
        text-align: center;
      }}
      .premium-hero-shell {{ padding: 40px 0; }}
      .home-section {{ padding: 40px 0; }}
      .beta-banner-premium {{ flex-direction: column; gap: 20px; text-align: center; }}
      .beta-banner-premium div {{ text-align: center; }}
    }}
    .premium-hero-shell {{ width: min(1280px, calc(100% - 32px)); margin: 0 auto; padding: 80px 0 60px; text-align: center; position: relative; }}
    .premium-hero-shell::before {{ content: ""; position: absolute; top: -100px; left: 50%; transform: translateX(-50%); width: 600px; height: 600px; background: radial-gradient(circle, rgba(59,130,246,0.15) 0%, transparent 70%); z-index: -1; pointer-events: none; }}
    .premium-kicker {{ display: inline-flex; align-items: center; gap: 8px; padding: 8px 16px; border-radius: 999px; background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.2); color: #60a5fa; font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 24px; }}
    .premium-hero-title {{ font-size: clamp(40px, 6vw, 64px); font-weight: 900; line-height: 1.1; letter-spacing: -0.04em; color: #fff; margin: 0 0 24px; }}
    .premium-hero-subtitle {{ font-size: clamp(18px, 2.5vw, 22px); color: #94a3b8; max-width: 760px; margin: 0 auto 40px; line-height: 1.6; }}
    .premium-actions {{ display: flex; align-items: center; justify-content: center; gap: 16px; flex-wrap: wrap; }}
    .premium-btn-primary {{ display: inline-flex; align-items: center; justify-content: center; height: 52px; padding: 0 32px; border-radius: 12px; background: #3b82f6; color: #fff; font-size: 16px; font-weight: 700; text-decoration: none; transition: all 0.2s; box-shadow: 0 8px 24px rgba(59, 130, 246, 0.25); }}
    .premium-btn-primary:hover {{ background: #2563eb; transform: translateY(-2px); box-shadow: 0 12px 32px rgba(59, 130, 246, 0.35); }}
    .premium-btn-secondary {{ display: inline-flex; align-items: center; justify-content: center; height: 52px; padding: 0 32px; border-radius: 12px; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); color: #e2e8f0; font-size: 16px; font-weight: 600; text-decoration: none; transition: all 0.2s; }}
    .premium-btn-secondary:hover {{ background: rgba(255, 255, 255, 0.1); color: #fff; }}
    .home-section {{ padding: 80px 0; position: relative; }}
    .home-section-header {{ text-align: center; margin-bottom: 56px; }}
    .home-section-header h2 {{ font-size: 36px; font-weight: 800; color: #fff; margin: 0 0 16px; letter-spacing: -0.02em; }}
    .home-section-header p {{ font-size: 18px; color: #94a3b8; max-width: 600px; margin: 0 auto; }}
    .sport-cards-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 24px; }}
    .premium-sport-card {{ display: flex; flex-direction: column; background: #121929; border: 1px solid #1e293b; border-radius: 20px; padding: 32px; text-decoration: none; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); position: relative; overflow: hidden; }}
    .premium-sport-card::before {{ content: ""; position: absolute; top: 0; left: 0; right: 0; height: 4px; background: var(--card-accent, #3b82f6); opacity: 0.5; transition: opacity 0.3s; }}
    .premium-sport-card:hover {{ transform: translateY(-4px); border-color: rgba(255, 255, 255, 0.1); box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4); }}
    .premium-sport-card:hover::before {{ opacity: 1; }}
    .sport-card-icon {{ width: 48px; height: 48px; border-radius: 12px; background: rgba(255,255,255,0.03); display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 18px; color: var(--card-accent, #fff); margin-bottom: 24px; border: 1px solid rgba(255,255,255,0.05); }}
    .sport-card-title {{ font-size: 24px; font-weight: 800; color: #fff; margin: 0 0 12px; }}
    .sport-card-desc {{ font-size: 15px; color: #94a3b8; line-height: 1.6; margin: 0 0 24px; flex: 1; }}
    .sport-card-meta {{ display: flex; flex-direction: column; gap: 12px; margin-bottom: 24px; }}
    .sport-card-row {{ display: flex; justify-content: space-between; align-items: center; font-size: 13px; padding-bottom: 12px; border-bottom: 1px solid rgba(255, 255, 255, 0.05); }}
    .sport-card-row:last-child {{ border-bottom: none; padding-bottom: 0; }}
    .sport-card-label {{ color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }}
    .sport-card-val {{ color: #e2e8f0; font-weight: 700; }}
    .sport-card-cta {{ color: var(--card-accent, #3b82f6); font-weight: 700; font-size: 15px; display: flex; align-items: center; gap: 8px; }}
    .methodology-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 32px; }}
    .methodology-item {{ padding: 32px; border-radius: 20px; background: rgba(18, 25, 41, 0.5); border: 1px solid rgba(255,255,255,0.05); }}
    .methodology-item h3 {{ font-size: 20px; font-weight: 800; color: #fff; margin: 0 0 12px; }}
    .methodology-item p {{ color: #94a3b8; line-height: 1.6; margin: 0; }}
    .pricing-section {{ text-align: center; background: linear-gradient(180deg, transparent, rgba(59, 130, 246, 0.05) 50%, transparent); border-top: 1px solid rgba(255,255,255,0.05); border-bottom: 1px solid rgba(255,255,255,0.05); }}
    .pricing-card {{ max-width: 480px; margin: 0 auto; background: #121929; border: 1px solid #1e293b; border-radius: 24px; padding: 48px; box-shadow: 0 24px 48px rgba(0,0,0,0.4); position: relative; }}
    .pricing-card::before {{ content: ""; position: absolute; top: -1px; left: 24px; right: 24px; height: 1px; background: linear-gradient(90deg, transparent, #3b82f6, transparent); }}
    .price-tag {{ font-size: 64px; font-weight: 900; color: #fff; letter-spacing: -0.05em; margin: 24px 0 8px; }}
    .price-period {{ font-size: 18px; color: #64748b; font-weight: 500; }}
    .pricing-features {{ list-style: none; padding: 0; margin: 32px 0; text-align: left; }}
    .pricing-features li {{ display: flex; align-items: center; gap: 12px; color: #e2e8f0; font-size: 15px; margin-bottom: 16px; }}
    .pricing-features li::before {{ content: "✓"; color: #10b981; font-weight: 800; }}
    .beta-banner-premium {{ background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 16px; padding: 24px 32px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 64px; }}
    .beta-banner-premium div {{ text-align: left; }}
    .beta-banner-premium h4 {{ color: #fff; margin: 0 0 8px; font-size: 18px; }}
    .beta-banner-premium p {{ color: #94a3b8; margin: 0; font-size: 15px; }}
    .analytics-preview-mock {{ max-width: 1000px; margin: 64px auto 0; background: #0f1725; border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; box-shadow: 0 32px 64px rgba(0,0,0,0.5); overflow: hidden; }}
    .mock-header {{ display: flex; gap: 8px; padding: 16px 24px; border-bottom: 1px solid rgba(255,255,255,0.05); background: rgba(255,255,255,0.02); }}
    .mock-dot {{ width: 12px; height: 12px; border-radius: 50%; background: #334155; }}
    .mock-dot.r {{ background: #ef4444; }}
    .mock-dot.y {{ background: #f59e0b; }}
    .mock-dot.g {{ background: #10b981; }}
    .mock-body {{ padding: 24px; }}
    .mock-row {{ display: flex; justify-content: space-between; align-items: center; padding: 16px; background: #121929; border: 1px solid rgba(255,255,255,0.03); border-radius: 12px; margin-bottom: 12px; }}
    .mock-row:last-child {{ margin-bottom: 0; }}
    .mock-player {{ font-weight: 700; color: #fff; }}
    .mock-stat {{ color: #94a3b8; font-size: 14px; }}
    .mock-badge {{ background: rgba(16, 185, 129, 0.15); color: #10b981; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 800; }}
  </style>
</head>
<body>
  <nav class="site-nav">
    <div class="nav-shell">
      <a class="nav-brand" href="/">
        <img class="nav-logo" src="/brand/logo.png" alt="EdgeRanked SportsAI logo">
        <span class="nav-wordmark">EdgeRanked<span class="brand-accent">SportsAI</span></span>
        <span class="beta-pill">Open Beta</span>
      </a>
      {render_root_nav(active_path)}
      <a class="cta-btn primary" href="/waitlist">Join Waitlist</a>
    </div>
  </nav>
  <div class="shell">
    {"" if is_home else f"""
    <section class="hero">
      <div class="brand-row">
        <div class="hero-copy">
          {{hero_media_html}}
          <div class="hero-kicker">{{escape(kicker)}}</div>
          <h1>{{escape(title)}}</h1>
          <p class="hero-sub">{{escape(subtitle)}}</p>
        </div>
      </div>
      {{section_nav_html}}
    </section>
    """}
    <main class="content">
      {body_html}
    </main>
  </div>
  {render_footer()}
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
    if kind == "mlb_hitters":
        return {"kind": kind, "records": load_hitter_summary(kind), "source_path": str(MLB_FILES["hitters"]), "last_updated": file_timestamp(MLB_FILES["hitters"])}
    if kind == "mlb_tb2":
        return {kind: kind, records: [row for row in build_mlb_hitter_projection_board() if normalize_text(row.get(stat)) == 2+ Bases], source_path: str(MLB_FILES[hitters]), last_updated: file_timestamp(MLB_FILES[hitters])}
    if kind == "mlb_rbi":
        return {"kind": kind, "records": load_hitter_summary(kind), "source_path": str(MLB_FILES["hitters"]), "last_updated": file_timestamp(MLB_FILES["hitters"])}
    if kind == "mlb_hitter_k":
        return {"kind": kind, "records": load_hitter_summary(kind), "source_path": str(MLB_FILES["hitters"]), "last_updated": file_timestamp(MLB_FILES["hitters"])}
    if kind == "mlb_sb":
        return {"kind": kind, "records": load_hitter_summary(kind), "source_path": str(MLB_FILES["hitters"]), "last_updated": file_timestamp(MLB_FILES["hitters"])}
    if kind == "mlb_hr":
        return {"kind": kind, "records": load_hitter_summary(kind), "source_path": str(MLB_FILES["hitters"]), "last_updated": file_timestamp(MLB_FILES["hitters"])}
    if kind == "mlb_lines":
        return {"kind": kind, "records": records_from_df(read_csv_df(MLB_FILES["lines"]).head(50)), "source_path": str(MLB_FILES["lines"]), "last_updated": file_timestamp(MLB_FILES["lines"])}
    if kind == "mlb_tracking":
        hitter_tracking = read_csv_df(MLB_FILES["hitter_tracking"])
        pitcher_tracking = read_csv_df(MLB_FILES["pitcher_tracking"])
        return {
            "kind": kind,
            "hitters": records_from_df(latest_rows_by_date(hitter_tracking, allowed_results_only=False).head(25)),
            "pitchers": records_from_df(latest_rows_by_date(pitcher_tracking, allowed_results_only=False).head(25)),
            "source_path": str(MLB_FILES["hitter_tracking"]),
            "last_updated": max(filter(None, [file_timestamp(MLB_FILES["hitter_tracking"]), file_timestamp(MLB_FILES["pitcher_tracking"])]), default=None),
        }
    return {"kind": kind, "records": mlb_system_rows(), "source_path": str(MLB_OUTPUT_DIR), "last_updated": max(filter(None, [file_timestamp(path) for path in MLB_FILES.values()]), default=None)}


def get_nba_dataset(spec_key):
    spec = NBA_PAGE_SPECS[spec_key]
    if spec_key == "projections":
        records = build_nba_projection_records()
        return {
            "kind": "table",
            "records": records,
            "title": spec["title"],
            "description": spec["description"],
            "source_path": str(Path(PROJECTIONS_PATH)),
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
        rows = []
        for key, item in NBA_PAGE_SPECS.items():
            rows.append({"page": key, "exists": "Yes" if item["path"].exists() else "No", "path": str(item["path"])})
        return {"kind": "table", "records": rows, "title": spec["title"], "description": spec["description"]}
    return {"kind": "table", "records": records_from_df(read_csv_df(spec["path"])), "title": spec["title"], "description": spec["description"]}


def get_ufc_dataset(spec_key):
    spec = UFC_PAGE_SPECS[spec_key]
    if spec_key == "fights":
        return {"kind": "json", "data": read_json(spec["path"]), "title": spec["title"], "description": spec["description"]}
    if spec_key == "system":
        rows = []
        for key, item in UFC_PAGE_SPECS.items():
            rows.append({"page": key, "exists": "Yes" if item["path"].exists() else "No", "path": str(item["path"])})
        return {"kind": "table", "records": rows, "title": spec["title"], "description": spec["description"]}
    return {"kind": "table", "records": records_from_df(read_csv_df(spec["path"])), "title": spec["title"], "description": spec["description"]}


def build_home_page():
    mlb_board = load_mlb_best_bets()
    body = f"""
    <div class="premium-hero-shell">
      <div class="premium-kicker">EdgeRankedSportsAI</div>
      <h1 class="premium-hero-title">Premium Multi-Sport Analytics</h1>
      <p class="premium-hero-subtitle">EdgeRankedSportsAI delivers premium multi-sport projections, matchup intelligence, player trends, simulations, and weather/context analysis.</p>
      <div class="premium-actions">
        <a href="/nba/projections" class="premium-btn-primary">Explore Projections</a>
        <a href="/waitlist" class="premium-btn-secondary">View Pricing</a>
      </div>

      <div class="analytics-preview-mock">
        <div class="mock-header">
          <div class="mock-dot r"></div><div class="mock-dot y"></div><div class="mock-dot g"></div>
        </div>
        <div class="mock-body">
          <div class="mock-row">
            <div>
              <div class="mock-player">Luka Doncic</div>
              <div class="mock-stat">Points + Rebounds + Assists • vs. LAL</div>
            </div>
            <div class="mock-badge">High Confidence Edge</div>
          </div>
          <div class="mock-row">
            <div>
              <div class="mock-player">Shohei Ohtani</div>
              <div class="mock-stat">Total Bases • Matchup Context: Strong</div>
            </div>
            <div class="mock-badge">Premium Pick</div>
          </div>
        </div>
      </div>
    </div>

    <section class="home-section">
      <div class="beta-banner-premium">
        <div>
          <h4>Open Beta Access</h4>
          <p>Free public access is currently live during beta testing. Premium memberships are coming soon.</p>
        </div>
        <a href="/waitlist" class="premium-btn-primary" style="height: 44px; font-size: 14px;">Join Waitlist</a>
      </div>

      <div class="home-section-header">
        <h2>Choose Your Sport</h2>
        <p>Access daily boards, full-slate player analytics, and model-driven projections.</p>
      </div>
      <div class="sport-cards-grid">
        <a href="/mlb" class="premium-sport-card" style="--card-accent: #3b82f6;">
          <div class="sport-card-icon">MLB</div>
          <h3 class="sport-card-title">MLB Projections</h3>
          <p class="sport-card-desc">Strikeout boards, hitter targets, and daily premium edges with weather and context adjustments.</p>
          <div class="sport-card-meta">
            <div class="sport-card-row"><span class="sport-card-label">Status</span><span class="sport-card-val" style="color: #10b981;">Live</span></div>
            <div class="sport-card-row"><span class="sport-card-label">Data</span><span class="sport-card-val">Daily Updates</span></div>
          </div>
          <div class="sport-card-cta">View Dashboard &rarr;</div>
        </a>
        <a href="/nba" class="premium-sport-card" style="--card-accent: #f97316;">
          <div class="sport-card-icon">NBA</div>
          <h3 class="sport-card-title">NBA Intelligence</h3>
          <p class="sport-card-desc">Projection explorer, matchup intelligence, verified results, and full-slate analytics.</p>
          <div class="sport-card-meta">
            <div class="sport-card-row"><span class="sport-card-label">Status</span><span class="sport-card-val" style="color: #10b981;">Live</span></div>
            <div class="sport-card-row"><span class="sport-card-label">Data</span><span class="sport-card-val">Daily Updates</span></div>
          </div>
          <div class="sport-card-cta" style="color: #f97316;">View Dashboard &rarr;</div>
        </a>
        <a href="/pga" class="premium-sport-card" style="--card-accent: #10b981;">
          <div class="sport-card-icon">PGA</div>
          <h3 class="sport-card-title">PGA Simulations</h3>
          <p class="sport-card-desc">Matchup edges, finishing targets, and strokes gained projections.</p>
          <div class="sport-card-meta">
            <div class="sport-card-row"><span class="sport-card-label">Status</span><span class="sport-card-val" style="color: #3b82f6;">New</span></div>
            <div class="sport-card-row"><span class="sport-card-label">Data</span><span class="sport-card-val">Tournament</span></div>
          </div>
          <div class="sport-card-cta" style="color: #10b981;">View Dashboard &rarr;</div>
        </a>
        <a href="/ufc" class="premium-sport-card" style="--card-accent: #ef4444;">
          <div class="sport-card-icon">UFC</div>
          <h3 class="sport-card-title">UFC Forecasts</h3>
          <p class="sport-card-desc">Fight forecasts, prop edges, and finish probabilities.</p>
          <div class="sport-card-meta">
            <div class="sport-card-row"><span class="sport-card-label">Status</span><span class="sport-card-val" style="color: #10b981;">Live</span></div>
            <div class="sport-card-row"><span class="sport-card-label">Data</span><span class="sport-card-val">Event Specific</span></div>
          </div>
          <div class="sport-card-cta" style="color: #ef4444;">View Dashboard &rarr;</div>
        </a>
      </div>
    </section>

    <section class="home-section">
      <div class="home-section-header">
        <h2>Data-Driven Methodology</h2>
        <p>Built for serious bettors and data-first sports fans seeking market advantages.</p>
      </div>
      <div class="methodology-grid">
        <div class="methodology-item">
          <h3>Simulation Systems</h3>
          <p>Every board is powered by real projection models, thousands of simulations, and live data inputs.</p>
        </div>
        <div class="methodology-item">
          <h3>Matchup Context</h3>
          <p>We adjust for weather, referee assignments, defensive schemes, and opponent context.</p>
        </div>
        <div class="methodology-item">
          <h3>Accountable Reporting</h3>
          <p>Transparent outcomes and win-rate visibility stay visible across the site. We track every result.</p>
        </div>
      </div>
    </section>

    <section class="home-section pricing-section">
      <div class="home-section-header">
        <h2>Premium Access</h2>
        <p>Get full access to all sports, models, and daily projections.</p>
      </div>
      <div class="pricing-card">
        <div class="premium-kicker" style="margin-bottom: 0;">Pro Membership</div>
        <div class="price-tag">$19.99<span class="price-period">/mo</span></div>
        <ul class="pricing-features">
          <li>Daily Multi-Sport Projections</li>
          <li>Matchup Analysis & Intelligence</li>
          <li>Full Simulation Insights</li>
          <li>Mobile-Optimized Dashboards</li>
          <li>Transparent Tracked Results</li>
        </ul>
        <a href="/waitlist" class="premium-btn-primary" style="width: 100%;">Join Waitlist</a>
      </div>
    </section>
    """
    
    return render_layout(
        title="EdgeRankedSportsAI | Premium Analytics",
        subtitle="",
        body_html=body,
        active_path="/",
        is_home=True
    )


def build_about_page():
    body = (
        "<section class='panel'><div class='panel-head'><div><div class='eyebrow'>About</div><h2>Built for serious bettors and data-first sports fans.</h2></div>"
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
            ("View Verified Results", "/nba/record", "secondary"),
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
    body = render_ufc_fight_cards(payload.get("fights", []) if isinstance(payload, dict) else [])
    return render_layout("UFC", "Fight forecasts, prop probabilities, and model-driven card analysis.", body, "/ufc", render_subnav(UFC_NAV_ITEMS, "/ufc"))


def build_mlb_home():
    best_bets = load_mlb_best_bets()
    hitter_rows = build_mlb_hitter_projection_board()
    pitcher_rows = build_mlb_pitcher_projection_board()
    pitcher_extra_columns = [("Pitcher K%", "pitcher_k_percent_season", "pct"), ("Opponent Hitter K%", "opponent_hitter_k_percent", "pct")]
    body = (
        render_banner(best_bets["banner"])
        + render_mlb_projection_snapshot(hitter_rows, pitcher_rows)
        + render_mlb_projection_table(
            "Hitter Projection Board",
            "Daily hitter projections across the slate, with sportsbook lines and edge context kept secondary.",
            hitter_rows,
            "mlb-hitters",
            entity_label="Player",
            include_lean=True,
            initial_limit=40,
        )
        + render_mlb_projection_table(
            "Pitcher Projection Board",
            "Projection-first pitcher rows for strikeouts and workload-driven markets.",
            pitcher_rows,
            "mlb-pitchers",
            entity_label="Pitcher",
            include_lean=False,
            extra_columns=pitcher_extra_columns,
        )
        + render_mlb_compact_top_plays(best_bets["top_plays"])
    )
    return render_layout("MLB Projection Center", "Daily hitter and pitcher projections powered by EdgeRanked.", body, "/mlb", render_mlb_nav("/mlb"))


def build_pricing_page(form_values=None, submit_state=None):
    return build_waitlist_page(form_values=form_values, submit_state=submit_state)


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
            + render_mlb_projection_table(
                "Pitcher Projection Board",
                "Projection-first pitcher rows for strikeouts and workload-driven markets.",
                pitcher_rows,
                "mlb-pitcher-projections",
                entity_label="Pitcher",
                include_lean=False,
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

    if spec_key in {"projections", "two_plus_bases", "rbi_targets", "hitter_strikeouts", "stolen_bases", "hr_targets"}:
        hitter_rows = build_mlb_hitter_projection_board()
        target_stat = {
            "projections": None,
            "two_plus_bases": "2+ Bases",
            "rbi_targets": "RBI",
            "hitter_strikeouts": "Hitter Strikeouts",
            "stolen_bases": "Stolen Bases",
            "hr_targets": "Home Runs",
        }[spec_key]
        rows = hitter_rows
        title_map = {
            "projections": "Hitter Projection Board",
            "two_plus_bases": "2+ Bases Board",
            "rbi_targets": "RBI Board",
            "hitter_strikeouts": "Hitter Strikeout Board",
            "stolen_bases": "Stolen Base Board",
            "hr_targets": "Home Run Board",
        }
        body = (
            render_mlb_projection_table(
                title_map[spec_key],
                "Expanded hitter projections across the slate, with projection kept primary and lines shown as supporting context.",
                rows,
                f"mlb-{spec_key}",
                entity_label="Player",
                include_lean=True,
                initial_limit=40 if spec_key == "projections" else 25,
                default_stat=target_stat,
                min_team_rows=3,
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
        body = header + render_nba_projection_table(rows)
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
        now = now_et()

        checks = {
            "mlb_pitchers": ("mlb/outputs/mlb_pitcher_projections_today.csv", 18),
            "mlb_hitters": ("mlb/outputs/hitter_predictions_today.csv", 18),
            "nba_projections": ("outputs/nba_last_good/projections.csv", 72),
            "nba_lines": ("outputs/nba_last_good/lines_today.csv", 72),
            "mlb_weather": ("mlb/outputs/mlb_weather_today.json", 18),
        }

        freshness = {}
        ok = True

        for name, (rel_path, max_age_hours) in checks.items():
            path = Path(rel_path)
            if not path.exists():
                freshness[name] = {
                    "ok": False,
                    "status": "missing",
                    "path": rel_path,
                    "max_age_hours": max_age_hours,
                }
                ok = False
                continue

            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=now.tzinfo)
            age_hours = round((now - mtime).total_seconds() / 3600, 2)
            is_fresh = age_hours <= max_age_hours

            freshness[name] = {
                "ok": is_fresh,
                "status": "fresh" if is_fresh else "stale",
                "path": rel_path,
                "age_hours": age_hours,
                "max_age_hours": max_age_hours,
                "modified_at": mtime.isoformat(),
            }

            if not is_fresh:
                ok = False

        status_code = 200 if ok else 503
        return jsonify({
            "ok": ok,
            "timestamp": now.isoformat(),
            "freshness": freshness,
        }), status_code

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

    @flask_app.get("/mlb")
    def mlb_home():
        return build_mlb_home()

    @flask_app.get("/mlb/weather")
    def mlb_weather_page():
        return build_mlb_weather_page()

    @flask_app.get("/mlb/player/<player_slug>")
    def mlb_player_page(player_slug):
        return build_mlb_player_page(player_slug)

    @flask_app.get("/sitemap_mlb_players.xml")
    def mlb_players_sitemap():
        return build_mlb_players_sitemap()

    @flask_app.get("/api/mlb/weather")
    def mlb_weather_api():
        return jsonify(load_mlb_weather())

    @flask_app.get("/ufc")
    def ufc_home():
        return build_ufc_home()

    for key, spec in NBA_PAGE_SPECS.items():
        def nba_page(spec_key=key):
            return build_nba_dataset_page(spec_key)

        def nba_api(spec_key=key):
            return jsonify(json_ready(get_nba_dataset(spec_key)))

        flask_app.add_url_rule(spec["route"], f"nba_page_{key}", nba_page)
        flask_app.add_url_rule(spec["api_route"], f"nba_api_{key}", nba_api)

    for key, spec in MLB_PAGE_SPECS.items():
        def mlb_page(spec_key=key):
            return build_mlb_dataset_page(spec_key)

        def mlb_api(spec_key=key):
            return jsonify(json_ready(get_mlb_dataset(spec_key)))

        flask_app.add_url_rule(spec["route"], f"mlb_page_{key}", mlb_page)
        flask_app.add_url_rule(spec["api_route"], f"mlb_api_{key}", mlb_api)

    for key, spec in UFC_PAGE_SPECS.items():
        def ufc_page(spec_key=key):
            return build_ufc_dataset_page(spec_key)

        def ufc_api(spec_key=key):
            return jsonify(json_ready(get_ufc_dataset(spec_key)))

        flask_app.add_url_rule(spec["route"], f"ufc_page_{key}", ufc_page)
        flask_app.add_url_rule(spec["api_route"], f"ufc_api_{key}", ufc_api)

    return flask_app


app = create_app()
