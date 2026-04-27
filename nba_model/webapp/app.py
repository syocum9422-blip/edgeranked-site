import csv
import json
import os
from datetime import date, datetime, timedelta
from html import escape
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
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_MLB_BASE = PROJECT_ROOT.parent / "mlb_model_v2_working" / "mlb_model"
DEFAULT_UFC_BASE = PROJECT_ROOT / "data" / "ufc"


def _resolve_first_existing_dir(candidates):
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    return candidates[0]


mlb_base_env = os.environ.get("EDGERANKED_MLB_BASE_DIR")
mlb_base_candidates = [Path(mlb_base_env)] if mlb_base_env else []
mlb_base_candidates.extend([PROJECT_ROOT, LEGACY_MLB_BASE])
MLB_OUTPUT_DIR = _resolve_first_existing_dir([base / "mlb" / "outputs" for base in mlb_base_candidates])
MLB_DATA_DIR = _resolve_first_existing_dir([base / "data" / "mlb" for base in mlb_base_candidates])

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
PGA_RESULTS_PATH = PGA_OUTPUT_DIR / "pga_simulation_results.csv"
PGA_INVALID_PROP_TYPES = {"", "holes_played", "null", "nan", "none"}

BRAND_ASSETS_DIR = PROJECT_ROOT / "assets" / "brand"
BRAND_LOGO_FILE = "edgeranked_logo.png"
SUPPORT_EMAIL = "support@edgerankedai.com"
WAITLIST_CONTACT_EMAIL = "info@edgerankai.com"
WAITLIST_DATA_PATH = PROJECT_ROOT / "data" / "waitlist.csv"

MLB_FILES = {
    "best_bets": MLB_OUTPUT_DIR / "betting_sheet_today.csv",
    "pitchers": MLB_OUTPUT_DIR / "pitcher_props_today.csv",
    "hitters": MLB_OUTPUT_DIR / "hitter_summary_today.csv",
    "history": MLB_OUTPUT_DIR / "bet_history.csv",
    "record": MLB_OUTPUT_DIR / "daily_betting_summary.csv",
    "hitter_tracking": MLB_OUTPUT_DIR / "hitter_tracking.csv",
    "pitcher_tracking": MLB_OUTPUT_DIR / "pitcher_tracking.csv",
    "lines": MLB_DATA_DIR / "lines_today.csv",
}

NBA_PAGE_SPECS = {
    "best_bets": {"title": "Today’s Best Bets", "path": Path(BEST_BETS_OUTPUT_PATH), "route": "/nba/best-bets", "api_route": "/api/nba/best-bets", "description": "The final top-ranked board your model is surfacing today."},
    "projections": {"title": "Player Projections", "path": Path(PROJECTIONS_PATH), "route": "/nba/projections", "api_route": "/api/nba/projections", "description": "All saved player projections for the current slate."},
    "history": {"title": "Bet History", "path": Path(HISTORY_PATH), "route": "/nba/history", "api_route": "/api/nba/history", "description": "Your latest graded NBA card."},
    "graded": {"title": "Latest Graded Bets", "path": Path(HISTORY_PATH), "route": "/nba/graded", "api_route": "/api/nba/graded", "description": "Rows already graded in the most recent NBA history export."},
    "record": {"title": "Record Summary", "path": Path(RECORD_SUMMARY_PATH), "route": "/nba/record", "api_route": "/api/nba/record", "description": "Daily performance summary from tracked bet results."},
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
    "pitcher_strikeouts": {"title": "Pitcher Strikeout Props", "route": "/mlb/pitcher-strikeouts", "api_route": "/api/mlb/pitcher-strikeouts", "description": "Pitcher strikeout plays with matchup context and recent form.", "kind": "mlb_pitchers"},
    "projections": {"title": "Hitter Targets", "route": "/mlb/projections", "api_route": "/api/mlb/projections", "description": "Current hitter targets sorted by hit probability.", "kind": "mlb_hitters"},
    "two_plus_hits": {"title": "2+ Hits Targets", "route": "/mlb/two-plus-hits", "api_route": "/api/mlb/two-plus-hits", "description": "Current 2+ hit targets sorted by probability.", "kind": "mlb_hit2plus"},
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
    ("Waitlist", "/waitlist"),
    ("About", "/about"),
]
NBA_NAV_ITEMS = [("Overview", "/nba"), ("Top Plays", "/nba/best-bets"), ("Projections", "/nba/projections"), ("History", "/nba/history")]
UFC_NAV_ITEMS = [("Overview", "/ufc"), ("Fight Card", "/ufc/fights"), ("Props", "/ufc/props")]
PGA_NAV_ITEMS = [("Overview", "/pga"), ("Best Bets", "/pga/best-bets"), ("Leaderboard", "/pga/leaderboard")]
MLB_PRIMARY_NAV = [("Overview", "/mlb"), ("Top Plays", "/mlb/best-bets"), ("Pitchers", "/mlb/pitcher-strikeouts"), ("Hitters", "/mlb/projections")]
MLB_HITTER_NAV = [
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
    "mlb_hitters": "hit_targets",
    "mlb_hit2plus": "two_plus_hits",
    "mlb_tb2": "two_plus_bases",
    "mlb_rbi": "rbi_targets",
    "mlb_hitter_k": "hitter_strikeouts",
    "mlb_sb": "stolen_bases",
    "mlb_hr": "hr_targets",
}
MLB_HITTER_PAGE_CATEGORIES = {
    "projections": "hit_targets",
    "two_plus_hits": "two_plus_hits",
    "two_plus_bases": "two_plus_bases",
    "rbi_targets": "rbi_targets",
    "hitter_strikeouts": "hitter_strikeouts",
    "stolen_bases": "stolen_bases",
    "hr_targets": "hr_targets",
}
MLB_HITTER_CATEGORY_LABELS = {
    "hit_targets": "Hit Targets",
    "two_plus_hits": "2+ Hits",
    "two_plus_bases": "2+ Bases",
    "rbi_targets": "RBI Targets",
    "hr_targets": "Home Runs",
    "stolen_bases": "Stolen Bases",
    "hitter_strikeouts": "Hitter Ks",
}
MLB_HITTER_CATEGORY_SORT_FIELDS = {
    "hit_targets": ("hit_prob",),
    "two_plus_hits": ("MC_Hit2Plus_Prob",),
    "two_plus_bases": ("tb2_prob",),
    "rbi_targets": ("rbi_prob",),
    "hr_targets": ("hr_prob",),
    "stolen_bases": ("sb_prob",),
    "hitter_strikeouts": ("projected_hitter_strikeouts", "hitter_strikeout_pct"),
}
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


def safe_float(value, default=None):
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
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
    if df.empty or "pitcher_name" not in df.columns:
        return {}
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
        snapshot[pitcher_key] = {
            "pitcher_k_percent_season": safe_float(latest.get("season_k_pct")),
            "opponent_hitter_k_percent": safe_float(latest.get("opponent_k_pct")),
            "estimated_innings": safe_float(latest.get("season_ip_per_start")),
            "recent_avg_ks": float(round(recent_actuals.mean(), 2)) if not recent_actuals.empty else None,
        }
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


def recommended_play(row, line_override=None):
    play = normalize_text(row.get("play")).upper()
    line = line_override if line_override is not None else standard_line_value(row)
    if play and line is not None:
        return f"{play.title()} {line:g}"
    fallback = normalize_text(row.get("recommended_play"))
    return fallback or play.title() or "n/a"


def projection_value(row):
    market = normalize_text(row.get("market")).upper()
    if market == "PITCHER_K":
        return safe_float(row.get("predicted_strikeouts"))
    return safe_float(row.get("projected_value"))


MLB_PITCHER_OUTPUT_CANDIDATES = [
    Path("/home/ubuntu/mlb_model/mlb/outputs/pitcher_props_today.csv"),
    Path("/home/ubuntu/mlb_model/mlb/outputs/mlb_pitcher_projections_today.csv"),
    Path("/home/ubuntu/mlb_model/mlb/outputs/pitcher_predictions_today.csv"),
    Path("/home/ubuntu/mlb_model/mlb/outputs/pitcher_predictions_full.csv"),
    Path("/home/ubuntu/EdgeRanked/sports/mlb/mlb_model/mlb/outputs/pitcher_props_today.csv"),
    Path("/home/ubuntu/EdgeRanked/sports/mlb/mlb_model/mlb/outputs/mlb_pitcher_projections_today.csv"),
    Path("/home/ubuntu/EdgeRanked/sports/mlb/mlb_model/mlb/outputs/pitcher_predictions_today.csv"),
    Path("/home/ubuntu/EdgeRanked/sports/mlb/mlb_model/mlb/outputs/pitcher_predictions_full.csv"),
    Path("/home/ubuntu/EdgeRanked/site/mlb/outputs/pitcher_props_today.csv"),
    Path("/home/ubuntu/EdgeRanked/site/mlb/outputs/mlb_pitcher_projections_today.csv"),
    Path("/home/ubuntu/EdgeRanked/site/mlb/outputs/pitcher_predictions_today.csv"),
    Path("/home/ubuntu/EdgeRanked/site/mlb/outputs/pitcher_predictions_full.csv"),
]

MLB_TOP_PLAYS_OUTPUT_CANDIDATES = [
    Path("/home/ubuntu/mlb_model/mlb/outputs/betting_sheet_today.csv"),
    Path("/home/ubuntu/mlb_model/mlb/outputs/daily_betting_summary.csv"),
    Path("/home/ubuntu/EdgeRanked/sports/mlb/mlb_model/mlb/outputs/betting_sheet_today.csv"),
    Path("/home/ubuntu/EdgeRanked/sports/mlb/mlb_model/mlb/outputs/daily_betting_summary.csv"),
    Path("/home/ubuntu/EdgeRanked/site/mlb/outputs/betting_sheet_today.csv"),
    Path("/home/ubuntu/EdgeRanked/site/mlb/outputs/daily_betting_summary.csv"),
]


def freshest_valid_csv(candidates, required_columns, fallback):
    valid = []
    for candidate in candidates:
        if not candidate.exists():
            continue
        df = read_csv_df(candidate)
        normalized_columns = {str(column).strip().lower() for column in df.columns}
        has_required = any(
            all(str(column).strip().lower() in normalized_columns for column in group)
            for group in required_columns
        )
        if not df.empty and has_required:
            valid.append((candidate.stat().st_mtime, len(df), candidate, df))
    if valid:
        valid.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return valid[0][2], valid[0][3]
    fallback_df = read_csv_df(fallback)
    return fallback, fallback_df


def mlb_pitcher_output_source():
    return freshest_valid_csv(
        MLB_PITCHER_OUTPUT_CANDIDATES,
        required_columns=(
            ("pitcher_name",),
            ("pitcher",),
        ),
        fallback=MLB_FILES["pitchers"],
    )


def mlb_pitcher_projection_context_source():
    return freshest_valid_csv(
        MLB_PITCHER_OUTPUT_CANDIDATES,
        required_columns=(
            ("pitcher", "season_k_pct", "opponent_k_pct"),
            ("pitcher", "pitcher_k_pct", "opponent_k_pct"),
            ("pitcher_name", "season_k_pct", "opponent_k_pct"),
            ("pitcher_name", "pitcher_k_pct", "opponent_k_pct"),
        ),
        fallback=MLB_FILES["pitchers"],
    )


def find_first_column_ci(df, names):
    lookup = {str(column).strip().lower(): column for column in df.columns}
    for name in names:
        column = lookup.get(str(name).strip().lower())
        if column is not None:
            return column
    return None


def standard_line_value(row):
    for field in ("line", "reference_line", "sportsbook_line", "prizepicks_line", "standard_line"):
        if field in row:
            value = safe_float(row.get(field), default=None)
            if value is not None and value == value:
                return value
    return None


def pitcher_rate_context_lookup():
    _, df = mlb_pitcher_projection_context_source()
    name_col = find_first_column_ci(df, ["pitcher_name", "Pitcher", "player_name"])
    pitcher_k_col = find_first_column_ci(df, ["season_k_pct", "pitcher_k_pct", "pitcher_k_percent", "k_pct", "K%", "pitcher_strikeout_pct", "Pitcher_K_Pct"])
    opponent_k_col = find_first_column_ci(df, ["opponent_k_pct", "opponent_hitter_k_pct", "opp_hitter_k_pct", "opp_k_pct", "opponent_strikeout_pct", "opponent_team_k_pct", "Opponent_K_Pct"])
    if df.empty or not name_col:
        return {}, pitcher_k_col, opponent_k_col
    lookup = {}
    for _, raw in df.iterrows():
        row = raw.to_dict()
        name = normalize_text(row.get(name_col)).lower()
        if not name:
            continue
        lookup[name] = {
            "pitcher_k_percent_season": safe_float(row.get(pitcher_k_col), default=None) if pitcher_k_col else None,
            "opponent_hitter_k_percent": safe_float(row.get(opponent_k_col), default=None) if opponent_k_col else None,
        }
    return lookup, pitcher_k_col, opponent_k_col


def pitcher_reference_line_lookup():
    _, df = mlb_pitcher_output_source()
    name_col = find_first_column_ci(df, ["pitcher_name", "Pitcher", "player_name"])
    if df.empty or not name_col:
        return {}, None
    line_col = find_first_column_ci(df, ["line", "reference_line", "sportsbook_line", "prizepicks_line", "standard_line"])
    lookup = {}
    for _, raw in df.iterrows():
        row = raw.to_dict()
        name = normalize_text(row.get(name_col)).lower()
        line = safe_float(row.get(line_col), default=None) if line_col else None
        if name and line is not None and line == line:
            lookup[name] = line
    return lookup, line_col


def mlb_top_plays_output_source():
    return freshest_valid_csv(
        MLB_TOP_PLAYS_OUTPUT_CANDIDATES,
        required_columns=(
            ("player_name", "market"),
            ("player", "market"),
        ),
        fallback=MLB_FILES["best_bets"],
    )


def pitcher_value(row, *fields):
    for field in fields:
        value = row.get(field)
        if value is not None:
            return value
    return None


def team_lookup_from_pitchers():
    _, df = mlb_pitcher_output_source()
    name_col = find_first_column(df, ["pitcher_name", "Pitcher", "player_name"])
    team_col = find_first_column(df, ["team", "Team"])
    if df.empty or not name_col or not team_col:
        return {}
    return {
        normalize_text(row[name_col]).lower(): normalize_text(row[team_col])
        for _, row in df.iterrows()
        if normalize_text(row.get(name_col))
    }


def load_mlb_best_bets():
    source_path, today_board = mlb_top_plays_output_source()
    history = read_csv_df(MLB_FILES["history"])
    tracking = latest_pitcher_tracking_snapshot()
    hitter_tracking = best_hitter_tracking_snapshot()
    team_lookup = team_lookup_from_pitchers()
    pitcher_line_lookup, top_plays_line_column = pitcher_reference_line_lookup()

    using_fallback = False
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
            line_value = pitcher_line_lookup.get(player_key) if market.startswith("PITCHER") else None
            if line_value is None:
                line_value = standard_line_value(row)
            team = ""
            if market.startswith("PITCHER"):
                team = team_lookup.get(player_key, "")
            opponent = normalize_text(row.get("opponent")) or normalize_text(row.get("matchup_pitcher")) or "TBD"
            enriched = {
                "player": player,
                "team": team or "TBD",
                "opponent": opponent,
                "stat_type": market_label(row),
                "reference_line": line_value,
                "projection": projection,
                "edge": safe_float(row.get("edge")),
                "confidence": confidence_level(row.get("confidence") or row.get("confidence_score")),
                "recommended_play": recommended_play(row, line_value),
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
        "top_plays_line_column": top_plays_line_column,
        "plays_shown": len(records),
        "model_version": MODEL_VERSION,
        "data_source_freshness": source_freshness_label(last_updated),
    }


def load_mlb_pitcher_board():
    source_path, props = mlb_pitcher_output_source()
    tracking = latest_pitcher_tracking_snapshot()
    rate_context, pitcher_k_column, opponent_k_column = pitcher_rate_context_lookup()
    using_fallback = False

    if props.empty:
        fallback = latest_rows_by_date(read_csv_df(MLB_FILES["pitcher_tracking"]), allowed_results_only=False)
        using_fallback = True
        source_path = MLB_FILES["pitcher_tracking"]
        props = fallback

    records = []
    for _, raw in props.iterrows():
        row = raw.to_dict()
        name = normalize_text(pitcher_value(row, "pitcher_name", "Pitcher", "player_name"))
        key = name.lower()
        line = standard_line_value(row)
        projected_ks = safe_float(pitcher_value(row, "projected_strikeouts", "predicted_strikeouts", "Projected_Strikeouts", "Model_Projected_K"))
        context = {**tracking.get(key, {}), **rate_context.get(key, {})}
        est_innings = safe_float(pitcher_value(row, "projected_ip", "Estimated_IP", "estimated_innings"))
        if est_innings is None:
            est_outs = safe_float(pitcher_value(row, "projected_outs", "predicted_outs", "Projected_Outs"))
            est_innings = round(est_outs / 3, 2) if est_outs is not None else context.get("estimated_innings")
        record = {
            "pitcher_name": name,
            "team": normalize_text(pitcher_value(row, "team", "Team")) or "TBD",
            "opponent": normalize_text(pitcher_value(row, "opponent", "Opponent")) or "TBD",
            "projected_ks": projected_ks,
            "reference_line": line,
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
        "pitcher_k_column": pitcher_k_column,
        "opponent_k_column": opponent_k_column,
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



MLB_HITTER_OUTPUT_CANDIDATES = [
    Path("/home/ubuntu/EdgeRanked/sports/mlb/mlb_model/mlb/outputs/hitter_predictions_full.csv"),
    Path("/home/ubuntu/EdgeRanked/sports/mlb/mlb_model/mlb/outputs/hitter_predictions_today.csv"),
    Path("/home/ubuntu/mlb_model/mlb/outputs/hitter_predictions_full.csv"),
    Path("/home/ubuntu/mlb_model/mlb/outputs/hitter_predictions_today.csv"),
    Path("/home/ubuntu/EdgeRanked/site/mlb/outputs/hitter_predictions_full.csv"),
    Path("/home/ubuntu/EdgeRanked/site/mlb/outputs/hitter_predictions_today.csv"),
]


def mlb_hitter_output_source():
    valid = []
    for candidate in MLB_HITTER_OUTPUT_CANDIDATES:
        if not candidate.exists():
            continue
        df = read_csv_df(candidate)
        hitter_col = find_first_column(df, ["hitter_name", "Hitter", "player_name"])
        if not df.empty and hitter_col:
            valid.append((candidate.stat().st_mtime, len(df), candidate, df))
    if not valid:
        fallback = MLB_FILES["hitters"]
        return fallback, read_csv_df(fallback)
    valid.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return valid[0][2], valid[0][3]


def mlb_numeric(row, *names):
    for name in names:
        value = safe_float(row.get(name), default=None)
        if value is not None:
            return value
    return None


def mlb_pick_text(row, *names, fallback=""):
    for name in names:
        value = normalize_text(row.get(name))
        if value:
            return value
    return fallback


def mlb_hitter_sort_value(row, category_key):
    for field in MLB_HITTER_CATEGORY_SORT_FIELDS.get(category_key, ("hit_prob",)):
        value = safe_float(row.get(field), default=None)
        if value is None:
            continue
        if category_key == "hitter_strikeouts" and value <= 0:
            continue
        return value
    return None


def build_mlb_hitter_card_records(category_key="hit_targets"):
    source_path, df = mlb_hitter_output_source()
    if df.empty:
        return [], source_path
    hitter_col = find_first_column(df, ["hitter_name", "Hitter", "player_name"])
    if not hitter_col:
        return [], source_path
    records = []
    for _, raw in df.iterrows():
        row = raw.to_dict()
        player = normalize_text(row.get(hitter_col))
        if not player:
            continue
        sort_value = mlb_hitter_sort_value(row, category_key)
        if sort_value is None or sort_value <= 0:
            continue
        records.append({
            "player": player,
            "team": mlb_pick_text(row, "team", "Team").upper(),
            "opponent": mlb_pick_text(row, "opponent", "Opponent", "opp", fallback="Matchup pending"),
            "pitcher": mlb_pick_text(row, "pitcher_name", "Pitcher", "matchup_pitcher", fallback="Pitcher pending"),
            "lineup_spot": safe_int(row.get("lineup_spot", row.get("Lineup Spot"))),
            "hit_prob": mlb_numeric(row, "hit_prob", "Hit Probability"),
            "two_hit_prob": mlb_numeric(row, "MC_Hit2Plus_Prob", "blended_hit_2plus_prob_v2", "hit_2plus_prob"),
            "tb2_prob": mlb_numeric(row, "tb2_prob", "Total Bases >= 2"),
            "rbi_prob": mlb_numeric(row, "rbi_prob", "RBI Probability"),
            "hr_prob": mlb_numeric(row, "hr_prob", "Home Run Probability"),
            "sb_prob": mlb_numeric(row, "sb_prob", "Stolen Base Probability"),
            "hitter_k_projection": mlb_numeric(row, "projected_hitter_strikeouts", "Projected Hitter Strikeouts"),
            "hitter_k_pct": mlb_numeric(row, "hitter_strikeout_pct", "Hitter Strikeout %"),
            "category": category_key,
            "sort_value": sort_value,
        })
    records.sort(key=lambda item: (safe_float(item.get("sort_value"), default=-9999), safe_float(item.get("hit_prob"), default=-9999), item.get("player", "")), reverse=True)
    return records, source_path


def render_mlb_hitter_cards(title, subtitle, rows, source_path, scope_id, category_key):
    if not rows:
        return render_empty_state(title, f"No {title.lower()} are currently available.", "The latest MLB hitter output file does not contain rows for this category yet.")
    teams = sorted({row["team"] for row in rows if row.get("team")})
    team_options = "".join(f'<option value="{escape(team)}">{escape(team)}</option>' for team in teams)

    def chip(label, value, fmt="pct"):
        if value is None:
            return ""
        display = pct_label(value) if fmt == "pct" else metric_label(value)
        return f'<div class="hitter-stat"><span>{escape(label)}</span><strong>{escape(display)}</strong></div>'

    cards = []
    for row in rows:
        lineup_html = f'<span class="meta-chip">Lineup {safe_int(row.get("lineup_spot"))}</span>' if row.get("lineup_spot") else ''
        cards.append(
            f'<article class="play-card mlb-hitter-card" data-team="{escape(row.get("team", ""))}" data-player="{escape(row.get("player", "").lower())}" data-sort="{safe_float(row.get("sort_value"), default=-9999)}">'
            f'<div class="play-top"><div><div class="play-name">{escape(row.get("player") or "Hitter")}</div>'
            f'<div class="play-sub">{escape(row.get("team") or "-")} vs {escape(row.get("opponent") or "Matchup pending")}</div></div>'
            f'<span class="badge badge-neutral">{escape(MLB_HITTER_CATEGORY_LABELS.get(category_key, "MLB"))}</span></div>'
            f'<div class="card-meta"><span class="meta-chip">Pitcher {escape(row.get("pitcher") or "Pending")}</span>{lineup_html}</div>'
            '<div class="hitter-stat-grid">'
            + chip('Hit', row.get('hit_prob'))
            + chip('2+ Bases', row.get('tb2_prob'))
            + chip('RBI', row.get('rbi_prob'))
            + chip('HR', row.get('hr_prob'))
            + chip('2+ Hits', row.get('two_hit_prob'))
            + chip('SB', row.get('sb_prob'))
            + chip('Hitter K', row.get('hitter_k_projection'), 'num')
            + chip('Hitter K%', row.get('hitter_k_pct'))
            + '</div></article>'
        )
    return (
        '<section class="panel">'
        f'<div class="panel-head"><div><div class="eyebrow">MLB</div><h2>{escape(title)}</h2></div><p class="muted">{escape(subtitle)}</p></div>'
        f'<p class="muted projection-summary">Source: {escape(str(source_path))} | Updated: {escape(format_timestamp(file_timestamp(source_path)))} | Rows: {len(rows)}</p>'
        '<div class="mlb-team-filter"><label class="filter-field"><span>Team</span>'
        f'<select id="{escape(scope_id)}-team"><option value="ALL">All Teams</option>{team_options}</select></label></div>'
        f'<p class="muted projection-summary" id="{escape(scope_id)}-summary">Showing {len(rows)} players.</p>'
        f'<div class="play-grid-shell" id="{escape(scope_id)}-cards">{"".join(cards)}</div>'
        '</section>'
        '<style>.mlb-team-filter{max-width:280px;margin:14px 0 16px}.card-meta{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}.meta-chip{display:inline-flex;align-items:center;padding:4px 10px;border-radius:999px;border:1px solid rgba(59,130,246,.22);background:rgba(59,130,246,.1);color:#dbeafe;font-size:11px;font-weight:700}.hitter-stat-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.hitter-stat{padding:9px 10px;border:1px solid rgba(30,41,59,.75);border-radius:10px;background:rgba(10,15,28,.58)}.hitter-stat span{display:block;color:var(--muted);font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}.hitter-stat strong{color:#fff;font-size:16px;line-height:1.25}</style>'
        f'<script>(()=>{{const cards=Array.from(document.querySelectorAll("#{scope_id}-cards .mlb-hitter-card"));const team=document.getElementById("{scope_id}-team");const summary=document.getElementById("{scope_id}-summary");function apply(){{const active=team?.value||"ALL";let visible=0;cards.forEach((card)=>{{const show=active==="ALL"||card.dataset.team===active;card.hidden=!show;card.style.display=show?"":"none";if(show)visible+=1;}});summary.textContent=active==="ALL"?`Showing ${{visible}} players.`:`Showing ${{visible}} players | team: ${{active}}`;}}team?.addEventListener("change",apply);apply();}})();</script>'
    )

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


def read_nba_summary():
    best_bets = records_from_df(read_csv_df(BEST_BETS_OUTPUT_PATH))
    projections = projection_view_records()
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
                continue
            return {
                "records": records,
                "source_path": str(path),
                "last_updated": file_timestamp(path),
                "selected_round": selected_round if fallback_round is not None else None,
                "is_round_specific": fallback_round is not None,
            }
    empty_source = str(candidates[0][0]) if candidates else str(PGA_OUTPUT_DIR / "best_bets_R1.json")
    return {
        "records": [],
        "source_path": empty_source,
        "last_updated": None,
        "selected_round": selected_round,
        "is_round_specific": False,
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
        "<div><span>EdgeRanked<span class='brand-accent'>SportsAI</span></span><div class='footer-note'>Institutional-grade sports intelligence and probability modeling.</div></div>"
        "</div>"
        "<div class='footer-links'>"
        "<div class='footer-col'>"
        "<h4>Platform</h4>"
        "<a href='/nba'>NBA</a>"
        "<a href='/mlb'>MLB</a>"
        "<a href='/ufc'>UFC</a>"
        "<a href='/pga'>PGA</a>"
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
            f"<div><span>Reference</span><strong>{escape(metric_label(row.get('reference_line')))}</strong></div>"
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
        "<div class='pricing-name'>Join the EdgeRank AI Waitlist</div>"
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
            "Join the EdgeRank AI Waitlist",
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
        "Join the EdgeRank AI Waitlist",
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
    cleaned = []
    for row in rows:
        cleaned.append({
            "fighter_name": ufc_prop_fighter_name(row),
            "prop": ufc_prop_label(row),
            "probability": row.get("probability"),
        })
    cleaned.sort(key=lambda item: safe_float(item.get("probability")) or 0, reverse=True)
    return render_data_table(
        "UFC Props",
        "Published UFC props with a cleaner public-facing layout.",
        cleaned,
        [("Fighter Name", "fighter_name", "text"), ("Prop", "prop", "text"), ("Probability", "probability", "pct")],
        "No UFC props are currently available.",
        "The latest UFC prop export has not been loaded yet.",
    )


def render_path_panel(path):
    return ""


def render_nba_projection_table(rows):
    if not rows:
        return render_empty_state(
            "Player Projections",
            "No NBA projections are currently available.",
            "The current NBA projection file has not been loaded yet.",
        )

    stat_labels = {
        "PTS": "Points",
        "REB": "Rebounds",
        "AST": "Assists",
        "3PM": "3PM",
        "STL": "Steals",
        "BLK": "Blocks",
        "PRA": "PRA",
        "RA": "RA",
        "PA": "PA",
        "PR": "PR",
        "SB": "Stocks",
        "FANTASY": "Fantasy",
        "MIN": "Minutes",
        "TOV": "Turnovers",
    }
    all_columns = ["PLAYER", "TEAM", "MATCHUP", "CONFIDENCE", "MIN", "PTS", "REB", "AST", "STL", "BLK", "3PM", "TOV", "PRA", "PR", "PA", "RA", "SB", "FANTASY"]
    available_columns = [column for column in all_columns if column in rows[0]]
    focusable_stats = [column for column in ["PTS", "REB", "AST", "3PM", "STL", "BLK", "PRA", "RA", "PA", "PR", "SB", "FANTASY", "MIN", "TOV"] if column in available_columns]
    team_options = sorted({normalize_text(row.get("TEAM")).upper() for row in rows if normalize_text(row.get("TEAM"))})

    header_cells = []
    for column in available_columns:
        header_class = "projection-stat-col" if column in focusable_stats else ""
        stat_attr = f" data-stat-key='{escape(column)}'" if column in focusable_stats else ""
        header_cells.append(f"<th class='{header_class}' data-key='{escape(column)}'{stat_attr}>{escape(stat_labels.get(column, column.title()))}</th>")

    body_rows = []
    for row in rows:
        team = normalize_text(row.get("TEAM")).upper()
        confidence = confidence_level(row.get("CONFIDENCE"))
        cells = []
        for column in available_columns:
            label = stat_labels.get(column, column.title())
            value = row.get(column)
            if column == "CONFIDENCE":
                rendered = render_badge(value, "confidence")
            elif column in focusable_stats:
                rendered = escape(metric_label(value))
            else:
                rendered = escape(normalize_text(value) or "n/a")
            cell_class = "projection-stat-col" if column in focusable_stats else ""
            stat_attr = f" data-stat-key='{escape(column)}'" if column in focusable_stats else ""
            raw_value = metric_label(value) if column in focusable_stats else normalize_text(value)
            cells.append(
                f"<td class='{cell_class}' data-label='{escape(label)}' data-key='{escape(column)}' data-raw='{escape(raw_value)}'{stat_attr}>{rendered}</td>"
            )
        body_rows.append(
            "<tr "
            f"data-player='{escape(normalize_text(row.get('PLAYER')).lower())}' "
            f"data-team='{escape(team)}' "
            f"data-confidence='{escape(confidence)}' "
            f"data-confidence-rank='{confidence_rank(confidence)}'>"
            + "".join(cells)
            + "</tr>"
        )

    team_select = "".join(f"<option value='{escape(team)}'>{escape(team)}</option>" for team in team_options)
    stat_select = "".join(f"<option value='{escape(stat)}'>{escape(stat_labels.get(stat, stat))}</option>" for stat in focusable_stats)
    sort_options = [
        ("PROJECTION", "Projection"),
        ("PLAYER", "Player Name"),
        ("TEAM", "Team"),
        ("CONFIDENCE", "Confidence"),
    ]
    sort_select = "".join(f"<option value='{escape(value)}'>{escape(label)}</option>" for value, label in sort_options)

    return (
        "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>NBA</div><h2>Player Projections</h2></div>"
        "<p class='muted'>Sort by player, team, confidence, or the active stat projection. Use Stat Focus to spotlight a market without changing the underlying model output.</p></div>"
        "<div class='filter-toolbar'>"
        "<label class='filter-field'><span>Team</span><select id='nba-team-filter'><option value='ALL'>All Teams</option>"
        + team_select
        + "</select></label>"
        "<label class='filter-field'><span>Stat Focus</span><select id='nba-stat-filter'><option value='ALL'>All Stats</option>"
        + stat_select
        + "</select></label>"
        "<label class='filter-field'><span>Sort By</span><select id='nba-sort-field'>"
        + sort_select
        + "</select></label>"
        "<label class='filter-field'><span>Direction</span><select id='nba-sort-direction'><option value='desc'>High to Low</option><option value='asc'>Low to High</option></select></label>"
        "</div>"
        f"<p class='muted projection-summary' id='nba-projection-summary'>Showing {len(rows)} players.</p>"
        "<div class='table-shell'><table id='nba-projection-table'><thead><tr>"
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
  const summary = document.getElementById("nba-projection-summary");
  const teamFilter = document.getElementById("nba-team-filter");
  const statFilter = document.getElementById("nba-stat-filter");
  const sortField = document.getElementById("nba-sort-field");
  const sortDirection = document.getElementById("nba-sort-direction");
  let rafId = 0;

  const numericFields = new Set(["PROJECTION", "CONFIDENCE", "MIN", "PTS", "REB", "AST", "STL", "BLK", "3PM", "TOV", "PRA", "PR", "PA", "RA", "SB", "FANTASY"]);

  function cellFor(row, key) {
    return row.querySelector(`[data-key="${key}"]`);
  }

  function cellValue(row, key) {
    const cell = cellFor(row, key);
    if (!cell) return "";
    return (cell.dataset.raw || cell.textContent || "").trim();
  }

  function numericValue(row, key) {
    if (key === "CONFIDENCE") return Number(row.dataset.confidenceRank || "0");
    const raw = cellValue(row, key);
    const parsed = Number.parseFloat(raw);
    return Number.isNaN(parsed) ? -Infinity : parsed;
  }

  function activeProjectionKey() {
    return statFilter.value !== "ALL" ? statFilter.value : "FANTASY";
  }

  function applyColumnState() {
    const focusedStat = statFilter.value;
    table.querySelectorAll(".projection-stat-col").forEach((cell) => {
      const statKey = cell.dataset.statKey;
      const isActive = focusedStat !== "ALL" && statKey === focusedStat;
      cell.classList.toggle("stat-active", isActive);
      cell.classList.toggle("stat-hidden", focusedStat !== "ALL" && statKey && statKey !== focusedStat);
    });
  }

  function applyFiltersAndSort() {
    const team = teamFilter.value;
    const sortKey = sortField.value === "PROJECTION" ? activeProjectionKey() : sortField.value;
    const direction = sortDirection.value === "asc" ? 1 : -1;

    const visibleRows = rows.filter((row) => team === "ALL" || row.dataset.team === team);
    rows.forEach((row) => {
      row.hidden = !visibleRows.includes(row);
    });

    visibleRows.sort((a, b) => {
      if (numericFields.has(sortField.value) || sortField.value === "PROJECTION") {
        return (numericValue(a, sortKey) - numericValue(b, sortKey)) * direction;
      }
      const aValue = (sortField.value === "CONFIDENCE" ? a.dataset.confidence : cellValue(a, sortKey)).toLowerCase();
      const bValue = (sortField.value === "CONFIDENCE" ? b.dataset.confidence : cellValue(b, sortKey)).toLowerCase();
      return aValue.localeCompare(bValue) * direction;
    });

    visibleRows.forEach((row) => tbody.appendChild(row));

    const parts = [`Showing ${visibleRows.length} player${visibleRows.length === 1 ? "" : "s"}`];
    if (team !== "ALL") parts.push(`team: ${team}`);
    if (statFilter.value !== "ALL" && statFilter.selectedIndex >= 0) parts.push(`stat focus: ${statFilter.options[statFilter.selectedIndex].text}`);
    if (sortField.selectedIndex >= 0) parts.push(`sorted by ${sortField.options[sortField.selectedIndex].text.toLowerCase()}`);
    summary.textContent = parts.join(" | ");
  }

  function scheduleApply() {
    if (rafId) window.cancelAnimationFrame(rafId);
    rafId = window.requestAnimationFrame(() => {
      applyColumnState();
      applyFiltersAndSort();
    });
  }

  [teamFilter, statFilter, sortField, sortDirection].forEach((control) => {
    control.addEventListener("change", scheduleApply);
    control.addEventListener("input", scheduleApply);
  });

  applyColumnState();
  applyFiltersAndSort();
})();
</script>
"""
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
      background: linear-gradient(180deg, rgba(15, 23, 42, 0.98), rgba(2, 6, 23, 0.98));
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
    .form-field input, .form-field textarea, .filter-field select {{
      width: 100%;
      padding: 14px 16px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: rgba(10, 15, 28, 0.92);
      color: #fff;
      font: inherit;
      resize: vertical;
    }}
    .form-field input:focus, .form-field textarea:focus, .filter-field select:focus {{
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
    .projection-summary {{
      margin-bottom: 16px;
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
    if kind in MLB_HITTER_CATEGORY_STATS:
        category_key = MLB_HITTER_CATEGORY_STATS[kind]
        records, source_path = build_mlb_hitter_card_records(category_key)
        return {"kind": kind, "records": records, "source_path": str(source_path), "last_updated": file_timestamp(source_path)}
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
        return {"kind": "table", "records": projection_view_records(), "title": spec["title"], "description": spec["description"]}
    if spec_key in {"history", "graded"}:
        return {"kind": "table", "records": latest_graded_nba_history(), "title": spec["title"], "description": spec["description"]}
    if spec_key == "best_bets":
        return {"kind": "table", "records": clean_nba_best_bets_records(records_from_df(read_csv_df(spec["path"]))), "title": spec["title"], "description": spec["description"]}
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
    body = (
        "<section class='panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Open Beta</div><h2>Free public access is live during beta testing.</h2></div>"
        "<p class='muted'>Access NBA, MLB, UFC, and PGA dashboards while we prepare launch updates and premium tools.</p></div>"
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
            ("UFC", "Fight forecasts, prop edges, finish probability", "/ufc", "Live"),
            ("PGA", "Matchup edges, finishing targets, strokes gained projections", "/pga", "New"),
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
    body = (
        render_data_table(
            "Board Preview",
            "Current NBA board preview.",
            clean_nba_best_bets_records(records_from_df(read_csv_df(BEST_BETS_OUTPUT_PATH))[:8]),
            [(key, key, "text") for key in (clean_nba_best_bets_records(records_from_df(read_csv_df(BEST_BETS_OUTPUT_PATH))[:1])[0].keys() if clean_nba_best_bets_records(records_from_df(read_csv_df(BEST_BETS_OUTPUT_PATH))[:1]) else ["Board"])],
            "No NBA best bets are currently available.",
            "The NBA board has not been generated yet.",
        )
    )
    return render_layout("NBA", "AI-powered player projections, top plays, and verified results.", body, "/nba", render_subnav(NBA_NAV_ITEMS, "/nba"))


def build_ufc_home():
    payload = read_json(UFC_PAGE_SPECS["fights"]["path"])
    body = render_ufc_fight_cards(payload.get("fights", []) if isinstance(payload, dict) else [])
    return render_layout("UFC", "Fight forecasts, prop probabilities, and model-driven card analysis.", body, "/ufc", render_subnav(UFC_NAV_ITEMS, "/ufc"))


def build_mlb_home():
    best_bets = load_mlb_best_bets()
    pitchers = load_mlb_pitcher_board()
    body = (
        render_banner(best_bets["banner"])
        + "<div class='split'><div class='stack'>"
        + render_mlb_top_play_cards(best_bets["top_plays"])
        + "</div><div class='stack'>"
        + render_data_table(
            "Featured Pitchers",
            "Live strikeout targets from today's MLB board.",
            pitchers["records"][:6],
            [
                ("Pitcher", "pitcher_name", "text"),
                ("Opponent", "opponent", "text"),
                ("Proj Ks", "projected_ks", "num"),
                ("Confidence", "confidence", "badge"),
            ],
            "No pitcher props are currently available.",
            "Today's pitcher board is still being generated. Check back shortly.",
        )
        + "</div></div>"
    )
    return render_layout("MLB", "Pitcher strikeout targets, hitter edges, and daily top plays.", body, "/mlb", render_mlb_nav("/mlb"))


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
    body = (
        render_pga_round_links(summary, "/pga/best-bets")
        + render_stat_cards([
            ("Tournament", summary["tournament_name"], "Current event tied to the saved PGA outputs."),
            ("Round", round_display, "The latest valid round-specific prop board currently being shown."),
            ("Plays Shown", len(round_board["records"]), "Current saved round-specific PGA plays."),
        ], compact=True)
        + (
            render_data_table(
                "PGA Round Best Bets",
                "Round-specific golf props with line, simulation value, and confidence.",
                round_board["records"],
                pga_best_bets_columns(),
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
                    ("Reference Line", "reference_line", "num"),
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
        body = (
            render_banner(data["banner"])
            + render_meta_strip(data)
            + render_data_table(
                "Pitcher Strikeout Board",
                "Both season-level pitcher K% and opponent hitter K% are included to explain why each play stands out.",
                data["records"],
                [
                    ("Pitcher", "pitcher_name", "text"),
                    ("Team", "team", "text"),
                    ("Opponent", "opponent", "text"),
                    ("Projected Ks", "projected_ks", "num"),
                    ("Pitcher K% Season", "pitcher_k_percent_season", "pct"),
                    ("Opponent Hitter K%", "opponent_hitter_k_percent", "pct"),
                    ("Estimated Innings", "estimated_innings", "num"),
                    ("Confidence", "confidence", "badge"),
                ],
                "No pitcher props are currently available.",
                "Today's pitcher board is still being generated. Check back shortly.",
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

    if spec_key in {"projections", "two_plus_hits", "two_plus_bases", "rbi_targets", "hitter_strikeouts", "stolen_bases", "hr_targets"}:
        category_key = MLB_HITTER_PAGE_CATEGORIES[spec_key]
        rows, source_path = build_mlb_hitter_card_records(category_key)
        title_map = {
            "projections": "Hit Targets",
            "two_plus_hits": "2+ Hits Board",
            "two_plus_bases": "2+ Bases Board",
            "rbi_targets": "RBI Targets",
            "hitter_strikeouts": "Hitter Ks",
            "stolen_bases": "Stolen Bases",
            "hr_targets": "Home Runs",
        }
        body = render_mlb_hitter_cards(title_map[spec_key], subtitle, rows, source_path, f"mlb-{spec_key}", category_key)
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
        body = (
            header
            + render_data_table(spec["title"], "Daily NBA record summary from the tracked record file.", rows, columns, "No NBA record data is currently available.", "The latest NBA record file has not been loaded yet.")
        )
    elif spec_key == "best_bets":
        body = (
            header
            + render_data_table(spec["title"], "Current public-facing NBA best bets in the upgraded table layout.", rows, columns, "No NBA best bets are currently available.", "The current NBA board has not been generated yet.")
        )
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
