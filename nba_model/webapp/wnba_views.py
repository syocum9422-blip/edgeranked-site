from __future__ import annotations

import os
import json
import sys
from datetime import datetime, timedelta
from html import escape
from math import erf, isnan, sqrt
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from flask import jsonify


ET = ZoneInfo("America/New_York")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPORTS_ROOT = PROJECT_ROOT.parent / "sports"


def _resolve_wnba_base() -> Path:
    candidates = []
    env_base = os.environ.get("EDGERANKED_WNBA_BASE_DIR")
    if env_base:
        candidates.append(Path(env_base).expanduser())
    candidates.extend(
        [
            SPORTS_ROOT / "wnba",
            PROJECT_ROOT / "wnba",
            PROJECT_ROOT / "data" / "wnba",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


WNBA_BASE_DIR = _resolve_wnba_base()
WNBA_BEST_BETS_DIR = WNBA_BASE_DIR / "Best_Bets"
WNBA_PROJECTIONS_PATH = WNBA_BASE_DIR / "projections.csv"
WNBA_APP_VIEW_PATH = WNBA_BASE_DIR / "Projections_app_view.csv"
WNBA_BEST_BETS_PATH = WNBA_BEST_BETS_DIR / "wnba_best_bets_today.csv"
WNBA_HISTORY_PATH = WNBA_BEST_BETS_DIR / "wnba_bets_history.csv"
WNBA_GRADED_PATH = WNBA_BEST_BETS_DIR / "graded_bets.csv"
WNBA_RECORD_SUMMARY_PATH = WNBA_BEST_BETS_DIR / "record_summary.csv"
WNBA_CALIBRATION_SUMMARY_PATH = WNBA_BEST_BETS_DIR / "calibration_summary.csv"
WNBA_CALIBRATION_REPORT_PATH = WNBA_BEST_BETS_DIR / "calibration_report.txt"
WNBA_MATCH_AUDIT_PATH = WNBA_BEST_BETS_DIR / "match_audit_today.csv"
WNBA_UNMATCHED_PLAYERS_PATH = WNBA_BEST_BETS_DIR / "unmatched_players_today.csv"
WNBA_UNMATCHED_STATS_PATH = WNBA_BEST_BETS_DIR / "unmatched_stats_today.csv"
WNBA_STATUS_PATH = WNBA_BASE_DIR / "data" / "raw" / "wnba_player_status.csv"
WNBA_LINES_PATH = WNBA_BASE_DIR / "data" / "raw" / "wnba_sportsbook_lines.csv"
WNBA_SCHEDULE_PATH = WNBA_BASE_DIR / "data" / "raw" / "wnba_schedule_today.csv"

WNBA_PAGE_SPECS = {
    "best_bets": {
        "title": "WNBA Top Plays",
        "path": WNBA_BEST_BETS_PATH,
        "route": "/wnba/best-bets",
        "api_route": "/api/wnba/best-bets",
        "description": "Current WNBA model-approved opportunities with projection, line, edge, and confidence context.",
    },
    "projections": {
        "title": "WNBA Projection Explorer",
        "path": WNBA_PROJECTIONS_PATH,
        "route": "/wnba/projections",
        "api_route": "/api/wnba/projections",
        "description": "Full WNBA player projection board with team, stat, workload, range, and line context.",
    },
    "history": {
        "title": "WNBA Bet History",
        "path": WNBA_HISTORY_PATH,
        "route": "/wnba/history",
        "api_route": "/api/wnba/history",
        "description": "Published WNBA bet history with pending and graded outcomes.",
    },
    "graded": {
        "title": "Latest WNBA Graded Bets",
        "path": WNBA_GRADED_PATH,
        "route": "/wnba/graded",
        "api_route": "/api/wnba/graded",
        "description": "Most recent WNBA graded outcomes.",
    },
    "record": {
        "title": "WNBA Verified Results",
        "path": WNBA_RECORD_SUMMARY_PATH,
        "route": "/wnba/record",
        "api_route": "/api/wnba/record",
        "description": "Tracked WNBA record, recent hit rate, and calibration summaries.",
    },
    "injuries": {
        "title": "WNBA Availability",
        "path": WNBA_STATUS_PATH,
        "route": "/wnba/injuries",
        "api_route": "/api/wnba/injuries",
        "description": "Current WNBA availability input used by the model pipeline.",
    },
    "system": {
        "title": "WNBA System Status",
        "path": WNBA_BASE_DIR,
        "route": "/wnba/system",
        "api_route": "/api/wnba/system",
        "description": "Backing files and freshness for WNBA production outputs.",
    },
}

WNBA_NAV_ITEMS = [
    ("Overview", "/wnba"),
    ("Projections", "/wnba/projections"),
    ("Top Plays", "/wnba/best-bets"),
    ("History", "/wnba/history"),
]

WNBA_STAT_CONFIGS = [
    {"key": "PTS", "label": "Points", "projection": ["PTS_PROJ", "pts_proj"], "floor": ["PTS_FLOOR", "pts_floor"], "ceiling": ["PTS_CEILING", "pts_ceiling"], "thresholds": [10, 15, 20, 25, 30, 35]},
    {"key": "REB", "label": "Rebounds", "projection": ["REB_PROJ", "reb_proj"], "floor": ["REB_FLOOR", "reb_floor"], "ceiling": ["REB_CEILING", "reb_ceiling"], "thresholds": [4, 6, 8, 10, 12, 14]},
    {"key": "AST", "label": "Assists", "projection": ["AST_PROJ", "ast_proj"], "floor": ["AST_FLOOR", "ast_floor"], "ceiling": ["AST_CEILING", "ast_ceiling"], "thresholds": [2, 4, 6, 8, 10]},
    {"key": "FG3M", "label": "3PM", "projection": ["FG3M_PROJ", "fg3m_proj"], "floor": ["FG3M_FLOOR", "fg3m_floor"], "ceiling": ["FG3M_CEILING", "fg3m_ceiling"], "thresholds": [1, 2, 3, 4, 5]},
    {"key": "STL", "label": "Steals", "projection": ["STL_PROJ", "stl_proj"], "floor": ["STL_FLOOR", "stl_floor"], "ceiling": ["STL_CEILING", "stl_ceiling"], "thresholds": [1, 2, 3]},
    {"key": "BLK", "label": "Blocks", "projection": ["BLK_PROJ", "blk_proj"], "floor": ["BLK_FLOOR", "blk_floor"], "ceiling": ["BLK_CEILING", "blk_ceiling"], "thresholds": [1, 2, 3]},
]

WNBA_LINE_STAT_MAP = {
    "POINTS": "PTS",
    "PTS": "PTS",
    "REBOUNDS": "REB",
    "REB": "REB",
    "ASSISTS": "AST",
    "AST": "AST",
    "3PM": "FG3M",
    "3PT MADE": "FG3M",
    "FG3M": "FG3M",
    "THREES_MADE": "FG3M",
    "STEALS": "STL",
    "STL": "STL",
    "BLOCKS": "BLK",
    "BLK": "BLK",
}


def read_csv_df(path: Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def records_from_df(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    return df.where(pd.notna(df), None).to_dict(orient="records")


def json_ready(value):
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [json_ready(item) for item in value]
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def file_timestamp(path: Path):
    path = Path(path)
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, ET)


def public_data_source_label(path):
    return Path(path).name or "data_source"


def format_timestamp(ts) -> str:
    if not ts:
        return "n/a"
    return ts.astimezone(ET).strftime("%B %-d, %Y %-I:%M %p ET")


def normalize_text(value, default: str = "") -> str:
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


def metric_label(value, digits: int = 1) -> str:
    number = safe_float(value)
    if number is None:
        text = normalize_text(value)
        return text or "n/a"
    return f"{number:.{digits}f}" if digits else str(int(round(number)))


def pct_label(value, digits: int = 1) -> str:
    number = safe_float(value)
    if number is None:
        return "n/a"
    if abs(number) <= 1:
        number *= 100
    return f"{number:.{digits}f}%"


def confidence_level(value) -> str:
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


def confidence_rank(value) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(confidence_level(value).lower(), 0)


def grade_result_label(value) -> str:
    text = normalize_text(value).upper()
    if text in {"WIN", "LOSS", "PUSH"}:
        return text.title()
    return "Pending"


def first_value(row, names):
    for name in names:
        if name in row.index:
            value = row.get(name)
            if pd.notna(value):
                return value
    return None


def normalize_player_key(value) -> str:
    return " ".join(normalize_text(value).lower().split())


def projection_display_label(column_name: str) -> str:
    label = normalize_text(column_name)
    label = label.replace("_proj", "").replace("_floor", " floor").replace("_ceiling", " ceiling")
    label = label.replace("_prob", " probability").replace("_pct", " %").replace("_", " ")
    return label.title().replace("Pts", "Points").replace("Reb", "Rebounds").replace("Ast", "Assists").replace("Fg3M", "3PM")


def profile_value_payload(value, kind="value"):
    number = safe_float(value)
    if number is None:
        text = normalize_text(value)
        if not text:
            return None
        return {"value": text, "display": text, "kind": kind}
    return {"value": number, "display": pct_label(number) if kind == "probability" else metric_label(number), "kind": kind}


def append_profile_field(target, label, value, kind="value", source_column=None):
    payload = profile_value_payload(value, kind)
    if payload is None:
        return
    payload.update({"label": label})
    target.append(payload)


def latest_rows_by_date(df: pd.DataFrame, date_columns=("date", "bet_date", "DATE")) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    date_col = next((col for col in date_columns if col in df.columns), None)
    if not date_col:
        return df.copy()
    work = df.copy()
    parsed = pd.to_datetime(work[date_col], errors="coerce")
    if parsed.dropna().empty:
        return work
    latest = parsed.max().date()
    work["_parsed_date"] = parsed.dt.date
    return work[work["_parsed_date"] == latest].drop(columns=["_parsed_date"], errors="ignore").copy()


def wnba_normal_cdf(value):
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def probability_at_or_above(mean, std, threshold):
    if mean is None or threshold is None:
        return None
    spread = safe_float(std)
    if spread is None or spread <= 0:
        return 1.0 if mean >= threshold else 0.0
    z_score = (threshold - mean) / spread
    return min(max(1.0 - wnba_normal_cdf(z_score), 0.0), 1.0)


def threshold_target(config, projection):
    thresholds = config.get("thresholds", [])
    if projection is None or not thresholds:
        return None
    eligible = [value for value in thresholds if value <= projection]
    return eligible[-1] if eligible else thresholds[0]


def threshold_label(config, threshold):
    if threshold is None:
        return "n/a"
    return f"{metric_label(threshold, digits=0 if float(threshold).is_integer() else 1)}+ {config['label'].lower()}"


def build_line_lookup() -> dict:
    df = read_csv_df(WNBA_LINES_PATH)
    if df.empty:
        return {}
    player_col = next((col for col in ["player_name", "PLAYER_NAME", "PLAYER", "player"] if col in df.columns), None)
    stat_col = next((col for col in ["stat", "STAT", "market", "MARKET"] if col in df.columns), None)
    line_col = next((col for col in ["line", "LINE"] if col in df.columns), None)
    if not player_col or not stat_col or not line_col:
        return {}
    lookup = {}
    for _, raw in df.iterrows():
        player = normalize_text(raw.get(player_col)).lower()
        raw_stat = normalize_text(raw.get(stat_col)).upper()
        stat = WNBA_LINE_STAT_MAP.get(raw_stat)
        if not player or not stat:
            continue
        lookup.setdefault((player, stat), safe_float(raw.get(line_col)))
    return lookup


def estimated_std(floor, ceiling, projection):
    floor_value = safe_float(floor)
    ceiling_value = safe_float(ceiling)
    if floor_value is not None and ceiling_value is not None and ceiling_value >= floor_value:
        return (ceiling_value - floor_value) / 2.563
    projection_value = safe_float(projection)
    if projection_value is None:
        return None
    return max(projection_value * 0.22, 0.35)


def build_projection_records() -> list[dict]:
    df = read_csv_df(WNBA_PROJECTIONS_PATH)
    if df.empty:
        df = read_csv_df(WNBA_APP_VIEW_PATH)
    if df.empty:
        return []

    line_lookup = build_line_lookup()
    rows = []
    for _, raw in df.iterrows():
        player = normalize_text(first_value(raw, ["PLAYER_NAME", "PLAYER", "player_name", "player"]))
        team = normalize_text(first_value(raw, ["TEAM_ABBREVIATION", "TEAM", "team"])).upper()
        opponent = normalize_text(first_value(raw, ["OPPONENT", "opponent"])).upper()
        matchup = normalize_text(first_value(raw, ["MATCHUP", "matchup"]), f"{team} vs {opponent}" if team and opponent else "Matchup pending")
        confidence = confidence_level(first_value(raw, ["CONFIDENCE_LABEL", "MODEL_CONFIDENCE", "confidence", "CONFIDENCE"]))
        minutes = safe_float(first_value(raw, ["MIN_PROJ", "projected_minutes", "MIN"]))
        player_key = player.lower()

        for config in WNBA_STAT_CONFIGS:
            projection = safe_float(first_value(raw, config["projection"]))
            if projection is None:
                continue
            floor = safe_float(first_value(raw, config["floor"]))
            ceiling = safe_float(first_value(raw, config["ceiling"]))
            std = estimated_std(floor, ceiling, projection)
            threshold = threshold_target(config, projection)
            probability = probability_at_or_above(projection, std, threshold)
            line_value = line_lookup.get((player_key, config["key"]))
            line_delta = round(projection - line_value, 2) if line_value is not None else None
            rows.append(
                {
                    "player": player,
                    "team": team,
                    "opponent": opponent,
                    "matchup": matchup,
                    "confidence": confidence,
                    "confidence_rank": confidence_rank(confidence),
                    "expected_minutes": minutes,
                    "stat_key": config["key"],
                    "stat_label": config["label"],
                    "projection": projection,
                    "median_projection": projection,
                    "floor_projection": floor,
                    "ceiling_projection": ceiling,
                    "range_display": f"{metric_label(floor)}-{metric_label(ceiling)}" if floor is not None and ceiling is not None else "n/a",
                    "distribution_std": std,
                    "threshold": threshold,
                    "threshold_label": threshold_label(config, threshold),
                    "threshold_probability": probability,
                    "sportsbook_line": line_value,
                    "sportsbook_delta": line_delta,
                    "sort_projection": projection,
                    "sort_probability": probability if probability is not None else -1,
                    "sort_minutes": minutes if minutes is not None else -1,
                }
            )
    rows.sort(key=lambda item: (item["sort_projection"], item["sort_probability"], item["sort_minutes"], item["player"]), reverse=True)
    return rows


def build_projection_snapshot(records: list[dict], limit: int = 3) -> list[dict]:
    snapshot = []
    for stat_key in ["PTS", "REB", "AST", "FG3M", "STL", "BLK"]:
        stat_rows = [row for row in records if row["stat_key"] == stat_key]
        if not stat_rows:
            continue
        leaders = sorted(stat_rows, key=lambda item: item["projection"] if item["projection"] is not None else -1, reverse=True)[:limit]
        snapshot.append({"stat_key": stat_key, "stat_label": leaders[0]["stat_label"], "leaders": leaders})
    return snapshot


def build_player_projection_profiles() -> dict:
    source_path = WNBA_PROJECTIONS_PATH if WNBA_PROJECTIONS_PATH.exists() else WNBA_APP_VIEW_PATH
    df = read_csv_df(source_path)
    if df.empty:
        return {"records": [], "teams": [], "source_label": public_data_source_label(source_path), "last_updated": file_timestamp(source_path)}

    profiles = {}
    projection_columns = [
        column for column in df.columns
        if column.lower().endswith("_proj") or column.lower().endswith("_floor") or column.lower().endswith("_ceiling") or column == "projected_minutes"
    ]
    probability_columns = [column for column in df.columns if column.lower().endswith("_prob") or column.lower().endswith("_pct")]
    confidence_columns = [column for column in ["CONFIDENCE_LABEL", "MODEL_CONFIDENCE", "confidence", "CONFIDENCE"] if column in df.columns]

    for _, raw in df.iterrows():
        player = normalize_text(first_value(raw, ["PLAYER_NAME", "PLAYER", "player_name", "player"]))
        if not player:
            continue
        team = normalize_text(first_value(raw, ["TEAM_ABBREVIATION", "TEAM", "team"])).upper()
        opponent = normalize_text(first_value(raw, ["OPPONENT", "opponent"])).upper()
        key = normalize_player_key(player)
        profile = profiles.setdefault(key, {
            "player": player,
            "team": team,
            "opponent": opponent,
            "matchup": normalize_text(first_value(raw, ["MATCHUP", "matchup"]), f"{team} vs {opponent}" if team and opponent else "Matchup pending"),
            "confidence": confidence_level(first_value(raw, ["CONFIDENCE_LABEL", "MODEL_CONFIDENCE", "confidence", "CONFIDENCE"])),
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

    records = sorted(profiles.values(), key=lambda item: (item.get("team", ""), item.get("player", "")))
    teams = sorted({item["team"] for item in records if item.get("team")})
    return {"records": records, "teams": teams, "source_label": public_data_source_label(source_path), "last_updated": file_timestamp(source_path)}


def build_best_bets_board() -> dict:
    df = read_csv_df(WNBA_BEST_BETS_PATH)
    source_path = WNBA_BEST_BETS_PATH
    using_fallback = False
    if df.empty:
        history = read_csv_df(WNBA_HISTORY_PATH)
        if not history.empty:
            latest = latest_rows_by_date(history)
            if not latest.empty:
                df = latest.copy()
                source_path = WNBA_HISTORY_PATH
                using_fallback = True

    if df.empty:
        return {"records": [], "source_label": public_data_source_label(source_path), "last_updated": file_timestamp(source_path), "plays_shown": 0, "recent_hit_rate": None, "banner": ""}

    work = df.copy()
    work["ABS_EDGE_SORT"] = pd.to_numeric(work.get("ABS_EDGE", work.get("edge")), errors="coerce").fillna(0)
    work["BET_CONFIDENCE_SORT"] = pd.to_numeric(work.get("BET_CONFIDENCE", work.get("confidence_score")), errors="coerce").fillna(0)
    work = work.sort_values(["BET_CONFIDENCE_SORT", "ABS_EDGE_SORT"], ascending=[False, False], kind="stable")

    rows = []
    for _, raw in work.iterrows():
        side = normalize_text(raw.get("side")).upper()
        stat = normalize_text(raw.get("RAW_STAT") or raw.get("STAT") or raw.get("stat"))
        rows.append(
            {
                "date": normalize_text(raw.get("DATE") or raw.get("bet_date")),
                "player": normalize_text(raw.get("PLAYER") or raw.get("player_name")),
                "team": normalize_text(raw.get("TEAM") or raw.get("team")).upper(),
                "matchup": normalize_text(raw.get("MATCHUP"), f"{normalize_text(raw.get('team')).upper()} vs {normalize_text(raw.get('opponent')).upper()}"),
                "stat": stat,
                "bet": normalize_text(raw.get("BET"), f"{side} {stat}".strip()),
                "line": safe_float(raw.get("LINE") if "LINE" in raw.index else raw.get("line")),
                "projection": safe_float(raw.get("PROJECTION") if "PROJECTION" in raw.index else raw.get("projection_mean")),
                "edge": safe_float(raw.get("EDGE") if "EDGE" in raw.index else raw.get("line_delta")),
                "hit_rate": safe_float(raw.get("HIT_RATE") if "HIT_RATE" in raw.index else raw.get("hit_rate")),
                "confidence": confidence_level(raw.get("CONFIDENCE_LABEL") or raw.get("confidence")),
                "confidence_score": safe_float(raw.get("BET_CONFIDENCE") if "BET_CONFIDENCE" in raw.index else raw.get("confidence_score")),
                "result": grade_result_label(raw.get("RESULT") if "RESULT" in raw.index else raw.get("bet_result")),
            }
        )

    history = read_csv_df(WNBA_HISTORY_PATH)
    result_col = "bet_result" if "bet_result" in history.columns else "result" if "result" in history.columns else None
    recent_hit_rate = None
    if result_col:
        graded = history[history[result_col].astype(str).str.upper().isin({"WIN", "LOSS"})].copy()
        if not graded.empty:
            recent = graded.tail(min(len(graded), 15))
            wins = int((recent[result_col].astype(str).str.upper() == "WIN").sum())
            total = int(recent[result_col].astype(str).str.upper().isin({"WIN", "LOSS"}).sum())
            recent_hit_rate = wins / total if total else None

    return {
        "records": rows,
        "source_label": public_data_source_label(source_path),
        "last_updated": file_timestamp(source_path),
        "plays_shown": len(rows),
        "recent_hit_rate": recent_hit_rate,
        "banner": "Showing the latest available WNBA board from history." if using_fallback else "",
    }


def summarize_window(history_df: pd.DataFrame, days: int) -> dict:
    if history_df.empty:
        return {"record": "0-0", "win_rate": None}
    date_col = next((col for col in ["date", "bet_date", "DATE"] if col in history_df.columns), None)
    result_col = next((col for col in ["result", "bet_result", "RESULT"] if col in history_df.columns), None)
    if not date_col or not result_col:
        return {"record": "0-0", "win_rate": None}
    cutoff = datetime.now(ET).date() - timedelta(days=days - 1)
    work = history_df.copy()
    work["_date"] = pd.to_datetime(work[date_col], errors="coerce").dt.date
    work = work[work["_date"].notna() & (work["_date"] >= cutoff)]
    graded = work[work[result_col].astype(str).str.upper().isin({"WIN", "LOSS"})]
    wins = int((graded[result_col].astype(str).str.upper() == "WIN").sum())
    losses = int((graded[result_col].astype(str).str.upper() == "LOSS").sum())
    total = wins + losses
    return {"record": f"{wins}-{losses}", "win_rate": wins / total if total else None}


def build_record_board() -> dict:
    history = read_csv_df(WNBA_HISTORY_PATH)
    daily = read_csv_df(WNBA_RECORD_SUMMARY_PATH)
    result_col = next((col for col in ["result", "bet_result", "RESULT"] if col in history.columns), None)
    graded = history[history[result_col].astype(str).str.upper().isin({"WIN", "LOSS", "PUSH"})].copy() if result_col else pd.DataFrame()
    wins = int((graded[result_col].astype(str).str.upper() == "WIN").sum()) if not graded.empty else 0
    losses = int((graded[result_col].astype(str).str.upper() == "LOSS").sum()) if not graded.empty else 0
    pushes = int((graded[result_col].astype(str).str.upper() == "PUSH").sum()) if not graded.empty else 0
    total = wins + losses

    daily_rows = []
    if not daily.empty:
        work = daily.copy()
        date_col = "date" if "date" in work.columns else "bet_date" if "bet_date" in work.columns else None
        if date_col:
            work["_date"] = pd.to_datetime(work[date_col], errors="coerce")
            work = work.sort_values("_date", ascending=False, kind="stable")
        for _, raw in work.iterrows():
            wins_value = int(safe_float(raw.get("wins"), 0) or 0)
            losses_value = int(safe_float(raw.get("losses"), 0) or 0)
            total_value = int(safe_float(raw.get("total"), wins_value + losses_value) or 0)
            daily_rows.append({"date": normalize_text(raw.get("date") or raw.get("bet_date")), "wins": wins_value, "losses": losses_value, "total": total_value, "win_rate": safe_float(raw.get("win_pct"))})

    recent_results = []
    if not graded.empty:
        work = graded.copy()
        date_col = next((col for col in ["date", "bet_date", "DATE"] if col in work.columns), None)
        if date_col:
            work["_date"] = pd.to_datetime(work[date_col], errors="coerce")
            work = work.sort_values("_date", ascending=False, kind="stable")
        for _, raw in work.head(12).iterrows():
            recent_results.append(
                {
                    "date": normalize_text(raw.get("date") or raw.get("bet_date") or raw.get("DATE")),
                    "player": normalize_text(raw.get("player") or raw.get("player_name") or raw.get("PLAYER")),
                    "team": normalize_text(raw.get("team") or raw.get("TEAM")).upper(),
                    "stat": normalize_text(raw.get("raw_stat") or raw.get("stat") or raw.get("STAT")),
                    "bet": normalize_text(raw.get("bet") or raw.get("BET") or raw.get("side")),
                    "projection": safe_float(raw.get("projection") or raw.get("projection_mean") or raw.get("PROJECTION")),
                    "actual": safe_float(raw.get("actual") or raw.get("actual_value") or raw.get("ACTUAL")),
                    "result": grade_result_label(raw.get(result_col)),
                }
            )

    last_updated = max(filter(None, [file_timestamp(WNBA_HISTORY_PATH), file_timestamp(WNBA_RECORD_SUMMARY_PATH)]), default=None)
    return {
        "summary": {
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "win_rate": wins / total if total else None,
            "recent7": summarize_window(history, 7),
            "recent14": summarize_window(history, 14),
            "recent30": summarize_window(history, 30),
        },
        "records": daily_rows,
        "recent_results": recent_results,
        "source_label": public_data_source_label(WNBA_RECORD_SUMMARY_PATH),
        "last_updated": last_updated,
        "plays_tracked": len(graded),
    }


def render_stat_cards(cards, compact=False) -> str:
    class_name = "stat-grid compact" if compact else "stat-grid"
    return "<div class='" + class_name + "'>" + "".join(
        "<article class='stat-card'><span>" + escape(str(label)) + "</span><strong>" + escape(str(value)) + "</strong><p>" + escape(str(detail)) + "</p></article>"
        for label, value, detail in cards
    ) + "</div>"


def render_badge(label, kind="confidence") -> str:
    value = normalize_text(label, "Medium")
    return f"<span class='badge {escape(kind)}'>{escape(value)}</span>"


def render_empty_state(title: str, heading: str, detail: str) -> str:
    return "<section class='panel'><div class='panel-head'><div><div class='eyebrow'>" + escape(title) + "</div><h2>" + escape(heading) + "</h2></div><p class='muted'>" + escape(detail) + "</p></div></section>"


def render_data_table(title: str, subtitle: str, rows: list[dict], columns: list[tuple[str, str, str]], empty_heading: str, empty_detail: str) -> str:
    if not rows:
        return render_empty_state(title, empty_heading, empty_detail)
    header = "".join("<th>" + escape(label) + "</th>" for label, _, _ in columns)
    body = []
    for row in rows:
        cells = []
        for label, key, kind in columns:
            value = row.get(key)
            if kind == "pct":
                rendered = pct_label(value)
            elif kind == "num":
                rendered = metric_label(value)
            elif kind == "result":
                rendered = render_badge(value or "Pending", "result")
            else:
                rendered = escape(normalize_text(value, "n/a"))
            if kind == "result":
                cells.append(f"<td data-label='{escape(label)}'>{rendered}</td>")
            else:
                cells.append(f"<td data-label='{escape(label)}'>{rendered}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        "<section class='panel'><div class='panel-head'><div><div class='eyebrow'>"
        + escape(title)
        + "</div><h2>"
        + escape(title)
        + "</h2></div><p class='muted'>"
        + escape(subtitle)
        + "</p></div><div class='table-shell analytics-table-shell'><table><thead><tr>"
        + header
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div></section>"
    )


def render_player_profile_explorer(payload: dict) -> str:
    records = payload.get("records", []) if isinstance(payload, dict) else []
    if not records:
        return render_empty_state("Model Coverage", "No WNBA player profiles are currently available.", "The existing WNBA projection files do not currently contain supported player-level rows for this view.")
    teams = payload.get("teams", [])
    options = []
    for index, row in enumerate(records):
        team = normalize_text(row.get("team")).upper()
        label = normalize_text(row.get("player"), "Player") + (f" - {team}" if team else "")
        options.append(f"<option value='{index}' data-team='{escape(team)}'>{escape(label)}</option>")
    payload_json = json.dumps(json_ready(records)).replace("</", "<\\/")
    team_options = "".join(f"<option value='{escape(team)}'>{escape(team)}</option>" for team in teams)
    return (
        "<section class='panel player-profile-panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Projection Explorer</div><h2>Player Stat Profile</h2></div>"
        "<p class='muted'>Search or filter to see every projected stat, available probability, and confidence field already present for a selected WNBA player.</p></div>"
        "<div class='filter-toolbar player-profile-controls'>"
        "<label class='filter-field'><span>Search player</span><input id='wnba-profile-search' type='search' placeholder='Search by name'></label>"
        f"<label class='filter-field'><span>Team</span><select id='wnba-profile-team'><option value='ALL'>All</option>{team_options}</select></label>"
        f"<label class='filter-field player-select-field'><span>Player</span><select id='wnba-profile-player'>{''.join(options)}</select></label>"
        "</div><div class='player-profile-card' id='wnba-profile-profile'></div>"
        f"<script type='application/json' id='wnba-profile-data'>{payload_json}</script>"
        """
<script>
(() => {
  const dataNode = document.getElementById("wnba-profile-data");
  const playerSelect = document.getElementById("wnba-profile-player");
  const teamSelect = document.getElementById("wnba-profile-team");
  const searchInput = document.getElementById("wnba-profile-search");
  const profileNode = document.getElementById("wnba-profile-profile");
  if (!dataNode || !playerSelect || !profileNode) return;
  const records = JSON.parse(dataNode.textContent || "[]");
  const allOptions = Array.from(playerSelect.options).map((option) => option.cloneNode(true));
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  function fieldGrid(title, fields) {
    if (!fields || !fields.length) return "";
    return `<div class="profile-field-group"><h3>${escapeHtml(title)}</h3><div class="profile-field-grid">${fields.map((field) => `<div class="profile-field"><span>${escapeHtml(field.label)}</span><strong>${escapeHtml(field.display)}</strong></div>`).join("")}</div></div>`;
  }
  function renderProfile(indexValue) {
    const record = records[Number.parseInt(indexValue || "0", 10)] || records[0];
    if (!record) {
      profileNode.innerHTML = "<p class='muted'>No profile selected.</p>";
      return;
    }
    const context = [record.team, record.opponent || record.matchup].filter(Boolean).join(" / ");
    profileNode.innerHTML = `
      <div class="profile-card-head">
        <div><div class="eyebrow">Player Stat Profile</div><h3>${escapeHtml(record.player)}</h3><p class="muted">${escapeHtml(context || "Model View")}</p></div>
        <span class="badge medium">${escapeHtml(record.confidence || "Model View")}</span>
      </div>
      ${fieldGrid("Projected Stats", record.stats)}
      ${fieldGrid("Probability", record.probabilities)}
      ${fieldGrid("Confidence", record.confidence_fields)}
    `;
  }
  function applyFilters() {
    const team = (teamSelect?.value || "ALL").toUpperCase();
    const query = (searchInput?.value || "").trim().toLowerCase();
    const filtered = allOptions.filter((option) => {
      const record = records[Number.parseInt(option.value || "0", 10)] || {};
      const matchesTeam = team === "ALL" || (option.dataset.team || "").toUpperCase() === team;
      const matchesQuery = !query || String(record.player || "").toLowerCase().includes(query);
      return matchesTeam && matchesQuery;
    });
    playerSelect.replaceChildren(...filtered.map((option) => option.cloneNode(true)));
    if (playerSelect.options.length) renderProfile(playerSelect.value);
    else profileNode.innerHTML = "<p class='muted'>No profiles match the current filters.</p>";
  }
  playerSelect.addEventListener("change", () => renderProfile(playerSelect.value));
  teamSelect?.addEventListener("change", applyFilters);
  searchInput?.addEventListener("input", applyFilters);
  applyFilters();
})();
</script>
"""
        "</section>"
    )


def render_projection_table(rows: list[dict]) -> str:
    if not rows:
        return render_empty_state("Projection Explorer", "No WNBA projections are currently available.", "The latest WNBA projection file has not been loaded yet.")

    stat_options = sorted({row["stat_key"]: row["stat_label"] for row in rows}.items(), key=lambda item: item[1])
    team_options = sorted({row["team"] for row in rows if row["team"]})
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
            + "</div><div class='muted'>"
            + escape(row["matchup"])
            + "</div></div></td>"
            + "<td data-label='Stat'><div class='stat-chip'>"
            + escape(row["stat_label"])
            + "</div></td>"
            + "<td data-label='Projection'><div class='projection-main'>"
            + escape(metric_label(row["projection"]))
            + "</div></td>"
            + "<td data-label='Range'><div class='projection-main'>"
            + escape(row["range_display"])
            + "</div></td>"
            + "<td data-label='Probability'><div class='projection-main'>"
            + escape(probability)
            + "</div></td>"
            + "<td data-label='Minutes'><div class='projection-main'>"
            + escape(metric_label(row["expected_minutes"]))
            + "</div></td>"
            + "<td data-label='Context'>"
            + render_badge(row["confidence"], "confidence")
            + "</td></tr>"
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
        "<div class='panel-head'><div><div class='eyebrow'>Projection Explorer</div><h2>Full-slate WNBA player board</h2></div>"
        "<p class='muted'>Browse every player-stat projection generated by the current WNBA simulation output. Team filters use the full projection source, so a team view shows the entire modeled player pool for that team.</p></div>"
        + render_stat_cards([
            ("Modeled Players", str(total_players), "Players included in the current WNBA projection file."),
            ("Projection Rows", str(len(rows)), "Player-stat rows available for filtering and sorting."),
            ("Teams Live", str(total_teams), "Teams represented in the current WNBA board."),
            ("Stats Covered", str(total_stats), "Projection categories available in the explorer."),
        ], compact=True)
        + "<div class='filter-toolbar five-up'>"
        "<label class='filter-field'><span>Team</span><select id='wnba-team-filter'><option value='ALL'>All Teams</option>"
        + team_select
        + "</select></label>"
        "<label class='filter-field'><span>Stat</span><select id='wnba-stat-filter'><option value='ALL'>All Stats</option>"
        + stat_select
        + "</select></label>"
        "<label class='filter-field'><span>Sort By</span><select id='wnba-sort-field'>"
        + sort_select
        + "</select></label>"
        "<label class='filter-field'><span>Direction</span><select id='wnba-sort-direction'><option value='desc'>High to Low</option><option value='asc'>Low to High</option></select></label>"
        "<div class='filter-field'><span>Reset</span><button class='cta-btn secondary filter-reset-btn' id='wnba-reset-filters' type='button'>Reset Filters</button></div>"
        "</div>"
        f"<p class='muted projection-summary' id='wnba-projection-summary'>Showing {len(rows)} rows across {total_players} players.</p>"
        "<div class='table-shell analytics-table-shell'><table id='wnba-projection-table'><thead><tr><th>Player</th><th>Stat</th><th>Projection</th><th>Range</th><th>Probability</th><th>Minutes</th><th>Context</th></tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div></section>"
        """
<script>
(() => {
  const table = document.getElementById("wnba-projection-table");
  if (!table) return;
  const tbody = table.querySelector("tbody");
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const teamFilter = document.getElementById("wnba-team-filter");
  const statFilter = document.getElementById("wnba-stat-filter");
  const sortField = document.getElementById("wnba-sort-field");
  const sortDirection = document.getElementById("wnba-sort-direction");
  const resetButton = document.getElementById("wnba-reset-filters");
  const summary = document.getElementById("wnba-projection-summary");
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


def render_projection_snapshot(snapshot_cards: list[dict]) -> str:
    if not snapshot_cards:
        return render_empty_state("Projection Snapshot", "No WNBA projection leaders are currently available.", "Snapshot cards will populate once the current projection file is loaded.")
    cards = []
    for card in snapshot_cards:
        leaders = []
        for index, leader in enumerate(card["leaders"], start=1):
            leaders.append(
                "<li class='leader-item'><span class='leader-rank'>"
                + str(index)
                + "</span><div class='leader-copy'><div class='leader-name'>"
                + escape(leader["player"])
                + "</div><div class='leader-meta'>"
                + escape(leader["team"])
                + " | "
                + escape(metric_label(leader["projection"]))
                + " | "
                + escape(leader["threshold_label"])
                + " at "
                + escape(pct_label(leader["threshold_probability"]))
                + "</div></div></li>"
            )
        cards.append("<article class='leader-card'><div class='leader-card-head'><div class='eyebrow'>Snapshot</div><h3>" + escape(card["stat_label"]) + "</h3></div><ol class='leader-list'>" + "".join(leaders) + "</ol></article>")
    return "<section class='panel'><div class='panel-head'><div><div class='eyebrow'>WNBA Projection Snapshot</div><h2>Category leaders from the current slate</h2></div><p class='muted'>A quick read on where the WNBA board is strongest before opening the full explorer.</p></div><div class='leader-grid'>" + "".join(cards) + "</div></section>"


def render_best_bets_summary(board: dict) -> str:
    rows = board.get("records", [])[:4]
    if not rows:
        return render_empty_state("WNBA Top Plays", "No WNBA top plays are currently available.", "The board will populate when the WNBA pipeline publishes the latest model-approved opportunities.")
    cards = []
    for row in rows:
        cards.append(
            "<article class='play-card signal-card-quiet'><div class='play-top'><div><div class='play-name'>"
            + escape(row["player"])
            + "</div><div class='play-sub'>"
            + escape(row["team"])
            + " | "
            + escape(row["matchup"])
            + "</div></div>"
            + render_badge(row["confidence"], "confidence")
            + "</div><div class='play-grid'><div><span>Model Projection</span><strong>"
            + escape(metric_label(row["projection"]))
            + "</strong></div><div><span>Stat</span><strong>"
            + escape(row["stat"])
            + "</strong></div><div><span>Sportsbook Line</span><strong>"
            + escape(metric_label(row["line"]))
            + "</strong></div><div><span>Hit Rate</span><strong>"
            + escape(pct_label(row["hit_rate"]))
            + "</strong></div></div><p class='muted'>"
            + escape(row["bet"] or "Model signal")
            + "</p></article>"
        )
    return (
        "<section class='panel'><div class='panel-head'><div><div class='eyebrow'>Top Plays</div><h2>Current WNBA model signals</h2></div><p class='muted'>Top plays are a supporting layer next to the projection board, with line, edge, and confidence context kept visible.</p></div>"
        + render_stat_cards([
            ("Top Plays Published", str(board.get("plays_shown", 0)), "Rows currently available from the WNBA top-plays board."),
            ("Recent Graded Hit Rate", pct_label(board.get("recent_hit_rate")), "Computed from recent graded WNBA history when available."),
            ("Last Updated", format_timestamp(board.get("last_updated")), "Freshness of the WNBA top-plays file."),
        ], compact=True)
        + "<div class='play-grid-shell'>"
        + "".join(cards)
        + "</div></section>"
    )


def render_record_panel(record: dict) -> str:
    summary = record.get("summary", {})
    metrics = render_stat_cards([
        ("All-Time Record", f"{summary.get('wins', 0)}-{summary.get('losses', 0)}", "Verified graded WNBA outcomes."),
        ("Win Rate", pct_label(summary.get("win_rate")), "Calculated from graded wins and losses."),
        ("Last 7 Days", summary.get("recent7", {}).get("record", "0-0"), "Recent graded WNBA record."),
        ("Last 14 Days", summary.get("recent14", {}).get("record", "0-0"), "Mid-window accountability check."),
        ("Last 30 Days", summary.get("recent30", {}).get("record", "0-0"), "Longer WNBA trend from tracked history."),
        ("Last Updated", format_timestamp(record.get("last_updated")), "Freshness of WNBA history and record files."),
    ])
    daily = render_data_table(
        "Daily Performance Ledger",
        "Recent day-by-day tracked WNBA performance.",
        record.get("records", []),
        [("Date", "date", "text"), ("Wins", "wins", "text"), ("Losses", "losses", "text"), ("Tracked", "total", "text"), ("Win Rate", "win_rate", "pct")],
        "No WNBA record data is currently available.",
        "The WNBA record summary will appear after grading writes completed outcomes.",
    )
    recent = render_data_table(
        "Recent Verified Results",
        "Latest WNBA graded outcomes from bet history.",
        record.get("recent_results", []),
        [("Date", "date", "text"), ("Player", "player", "text"), ("Team", "team", "text"), ("Stat", "stat", "text"), ("Bet", "bet", "text"), ("Projection", "projection", "num"), ("Actual", "actual", "num"), ("Result", "result", "result")],
        "No graded WNBA results are currently available.",
        "Verified WNBA results will appear after the nightly grading workflow runs.",
    )
    return "<section class='panel'><div class='panel-head'><div><div class='eyebrow'>Verified Results</div><h2>WNBA model accountability</h2></div><p class='muted'>Published WNBA plays stay tied to tracked outcomes and daily record summaries.</p></div>" + metrics + "</section>" + daily + recent


def render_best_bets_table(board: dict) -> str:
    return render_data_table(
        "WNBA Top Plays",
        "Current WNBA top plays with projection, line, edge, and hit-rate context.",
        board.get("records", []),
        [("Player", "player", "text"), ("Team", "team", "text"), ("Matchup", "matchup", "text"), ("Stat", "stat", "text"), ("Bet", "bet", "text"), ("Projection", "projection", "num"), ("Line", "line", "num"), ("Edge", "edge", "num"), ("Hit Rate", "hit_rate", "pct"), ("Confidence", "confidence", "text"), ("Result", "result", "result")],
        "No WNBA top plays are currently available.",
        "Run the WNBA pipeline to generate the latest top-plays board.",
    )


def build_system_rows() -> list[dict]:
    paths = {
        "base_dir": WNBA_BASE_DIR,
        "projections": WNBA_PROJECTIONS_PATH,
        "app_view": WNBA_APP_VIEW_PATH,
        "best_bets": WNBA_BEST_BETS_PATH,
        "history": WNBA_HISTORY_PATH,
        "graded": WNBA_GRADED_PATH,
        "record_summary": WNBA_RECORD_SUMMARY_PATH,
        "calibration_summary": WNBA_CALIBRATION_SUMMARY_PATH,
        "calibration_report": WNBA_CALIBRATION_REPORT_PATH,
        "match_audit": WNBA_MATCH_AUDIT_PATH,
        "unmatched_players": WNBA_UNMATCHED_PLAYERS_PATH,
        "unmatched_stats": WNBA_UNMATCHED_STATS_PATH,
        "availability": WNBA_STATUS_PATH,
        "lines": WNBA_LINES_PATH,
        "schedule": WNBA_SCHEDULE_PATH,
    }
    return [{"file": label, "exists": "Yes" if path.exists() else "No", "updated": format_timestamp(file_timestamp(path)), "source_label": label} for label, path in paths.items()]


def build_live_data_audit() -> dict:
    require_live_data = os.environ.get("EDGERANKED_WNBA_REQUIRE_LIVE_DATA", "")
    audit = {
        "schedule_source": "unknown",
        "lines_source": "unknown",
        "injuries_source": "unknown",
        "live_data_ready": False,
        "blocking_reasons": ["WNBA data-source audit could not be loaded."],
        "EDGERANKED_WNBA_REQUIRE_LIVE_DATA": require_live_data,
        "mode": "unknown",
    }

    try:
        wnba_base = str(WNBA_BASE_DIR)
        if wnba_base not in sys.path:
            sys.path.insert(0, wnba_base)
        from wnba_model.pipeline.service import audit_data_sources

        audit.update(audit_data_sources())
    except Exception as exc:
        audit["blocking_reasons"] = [f"WNBA data-source audit failed: {exc}"]

    require_live = str(require_live_data).strip().lower() in {"1", "true", "yes", "y"}
    if audit.get("live_data_ready"):
        audit["mode"] = "live-ready"
    elif require_live:
        audit["mode"] = "blocked-live-required"
    else:
        audit["mode"] = "safe/fallback"

    audit["EDGERANKED_WNBA_REQUIRE_LIVE_DATA"] = require_live_data
    audit["blocking_reasons"] = list(audit.get("blocking_reasons") or [])
    return audit


def build_live_data_audit_rows(audit: dict) -> list[dict]:
    blocking = audit.get("blocking_reasons") or []
    return [
        {"file": "schedule_source", "exists": "n/a", "updated": "n/a", "source_label": audit.get("schedule_source", "unknown")},
        {"file": "lines_source", "exists": "n/a", "updated": "n/a", "source_label": audit.get("lines_source", "unknown")},
        {"file": "injuries_source", "exists": "n/a", "updated": "n/a", "source_label": audit.get("injuries_source", "unknown")},
        {"file": "live_data_ready", "exists": "n/a", "updated": "n/a", "source_label": str(bool(audit.get("live_data_ready")))},
        {"file": "blocking_reasons", "exists": "n/a", "updated": "n/a", "source_label": "; ".join(str(reason) for reason in blocking) or "none"},
        {
            "file": "EDGERANKED_WNBA_REQUIRE_LIVE_DATA",
            "exists": "n/a",
            "updated": "n/a",
            "source_label": str(audit.get("EDGERANKED_WNBA_REQUIRE_LIVE_DATA", "")),
        },
        {"file": "live_data_mode", "exists": "n/a", "updated": "n/a", "source_label": audit.get("mode", "unknown")},
    ]


def get_dataset(spec_key: str) -> dict:
    spec = WNBA_PAGE_SPECS[spec_key]
    if spec_key == "projections":
        records = build_projection_records()
        return {"kind": "table", "records": records, "title": spec["title"], "description": spec["description"], "source_label": public_data_source_label(WNBA_PROJECTIONS_PATH), "last_updated": file_timestamp(WNBA_PROJECTIONS_PATH)}
    if spec_key == "best_bets":
        board = build_best_bets_board()
        board.update({"kind": "table", "title": spec["title"], "description": spec["description"]})
        return board
    if spec_key == "record":
        board = build_record_board()
        board.update({"kind": "table", "title": spec["title"], "description": spec["description"]})
        return board
    if spec_key == "history":
        return {"kind": "table", "records": records_from_df(latest_rows_by_date(read_csv_df(WNBA_HISTORY_PATH))), "title": spec["title"], "description": spec["description"]}
    if spec_key == "graded":
        return {"kind": "table", "records": records_from_df(read_csv_df(WNBA_GRADED_PATH)), "title": spec["title"], "description": spec["description"]}
    if spec_key == "system":
        return {
            "kind": "table",
            "records": [{"service": "wnba", "status": "available"}],
            "title": spec["title"],
            "description": spec["description"],
        }
    return {"kind": "table", "records": records_from_df(read_csv_df(spec["path"])), "title": spec["title"], "description": spec["description"]}


def build_home(render_layout, render_subnav) -> str:
    projection_rows = build_projection_records()
    best_bets = build_best_bets_board()
    snapshot = build_projection_snapshot(projection_rows)
    body = (
        "<section class='panel'><div class='panel-head'><div><div class='eyebrow'>WNBA Daily Slate</div><h2>Projection-first WNBA board</h2></div><p class='muted'>WNBA now follows the same product pattern as the flagship NBA board: full player coverage, sortable projection rows, and top-play context.</p></div></section>"
        + render_projection_snapshot(snapshot)
        + render_player_profile_explorer(build_player_projection_profiles())
        + "<section class='panel'><div class='panel-head'><div><div class='eyebrow'>Full Projection Access</div><h2>Explore every modeled player</h2></div><p class='muted'>Open the explorer to filter by team or stat and sort the full WNBA player-stat board.</p></div>"
        + "<div class='actions'><a class='cta-btn' href='/wnba/projections'>Open Projection Explorer</a></div></section>"
        + render_best_bets_summary(best_bets)
    )
    return render_layout("WNBA Projection Center", "WNBA player projections and top plays powered by EdgeRanked.", body, "/wnba", render_subnav(WNBA_NAV_ITEMS, "/wnba"), hero_kicker="WNBA")


def build_dataset_page(spec_key: str, render_layout, render_subnav) -> str:
    spec = WNBA_PAGE_SPECS[spec_key]
    data = get_dataset(spec_key)
    rows = data.get("records", [])
    nav_target = spec["route"] if spec_key != "system" else "/wnba"
    header = "<section class='panel'><div class='panel-head'><div><div class='eyebrow'>WNBA</div><h2>" + escape(spec["title"]) + "</h2></div><p class='muted'>" + escape(spec["description"]) + "</p></div></section>"
    if spec_key == "record":
        body = header + render_record_panel(data)
    elif spec_key == "best_bets":
        body = header + render_best_bets_table(data)
    elif spec_key == "projections":
        body = header + render_player_profile_explorer(build_player_projection_profiles()) + render_projection_table(rows)
    elif spec_key == "system":
        body = header + render_data_table("WNBA System Status", spec["description"], rows, [("Service", "service", "text"), ("Status", "status", "text")], "No WNBA system data is currently available.", "Status is currently unavailable.")
    else:
        columns = [(key, key, "text") for key in (rows[0].keys() if rows else ["Board"])]
        body = header + render_data_table(spec["title"], spec["description"], rows, columns, "No WNBA data is currently available.", "The latest WNBA file has not been loaded yet.")
    return render_layout(spec["title"], spec["description"], body, spec["route"], render_subnav(WNBA_NAV_ITEMS, nav_target), hero_kicker="WNBA")


def register_wnba_routes(flask_app, render_layout, render_subnav) -> None:
    @flask_app.get("/wnba")
    def wnba_home():
        return build_home(render_layout, render_subnav)

    @flask_app.get("/api/wnba/player-projections")
    def wnba_player_projections_api():
        return jsonify(json_ready(build_player_projection_profiles()))

    for key, spec in WNBA_PAGE_SPECS.items():
        def wnba_page(spec_key=key):
            return build_dataset_page(spec_key, render_layout, render_subnav)

        def wnba_api(spec_key=key):
            if spec_key == "system":
                return jsonify({"status": "ok", "sport": "wnba", "public": True})
            return jsonify(json_ready(get_dataset(spec_key)))

        flask_app.add_url_rule(spec["route"], f"wnba_page_{key}", wnba_page)
        flask_app.add_url_rule(spec["api_route"], f"wnba_api_{key}", wnba_api)
