from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = Path(os.environ.get("EDGERANKED_WNBA_BASE_DIR", str(PROJECT_ROOT))).expanduser().resolve()

DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
DATA_MODELS_DIR = DATA_DIR / "models"
MODELS_DIR = BASE_DIR / "models"
OUTPUTS_DIR = BASE_DIR / "outputs"
LOGS_DIR = BASE_DIR / "logs"
BEST_BETS_DIR = BASE_DIR / "Best_Bets"
ARCHIVE_DIR = OUTPUTS_DIR / "archive"
LAST_GOOD_DIR = OUTPUTS_DIR / "wnba_last_good"

RAW_PLAYER_GAMES_PATH = RAW_DIR / "wnba_player_games_raw.csv"
RAW_TEAM_CONTEXT_PATH = RAW_DIR / "wnba_team_context_raw.csv"
RAW_SCHEDULE_TODAY_PATH = RAW_DIR / "wnba_schedule_today_raw.csv"
RAW_SPORTSBOOK_LINES_PATH = RAW_DIR / "wnba_sportsbook_lines_raw.csv"
RAW_PLAYER_POSITIONS_PATH = RAW_DIR / "wnba_player_positions_raw.csv"
RAW_PLAYER_STATUS_PATH = RAW_DIR / "wnba_player_status_raw.csv"

CANONICAL_PLAYER_GAMES_PATH = RAW_DIR / "wnba_player_games.csv"
CANONICAL_TEAM_CONTEXT_PATH = RAW_DIR / "wnba_team_context.csv"
CANONICAL_SCHEDULE_TODAY_PATH = RAW_DIR / "wnba_schedule_today.csv"
CANONICAL_SPORTSBOOK_LINES_PATH = RAW_DIR / "wnba_sportsbook_lines.csv"
CANONICAL_PLAYER_POSITIONS_PATH = RAW_DIR / "wnba_player_positions.csv"
CANONICAL_PLAYER_STATUS_PATH = RAW_DIR / "wnba_player_status.csv"

DATASET_PATH = PROCESSED_DIR / "wnba_training_dataset.csv"
TODAY_FEATURES_PATH = PROCESSED_DIR / "wnba_today_features.csv"
MODEL_REPORT_PATH = PROCESSED_DIR / "wnba_model_report.csv"
SIMULATION_DETAIL_PATH = PROCESSED_DIR / "wnba_simulation_detail.csv"
BETTING_RECORD_PATH = BEST_BETS_DIR / "wnba_bets_history.csv"
GRADED_BETS_PATH = BEST_BETS_DIR / "graded_bets.csv"
PROJECTIONS_PATH = BASE_DIR / "projections.csv"
APP_VIEW_PROJECTIONS_PATH = BASE_DIR / "Projections_app_view.csv"
BEST_BETS_PATH = BASE_DIR / "wnba_best_bets_today.csv"
BEST_BETS_ARCHIVE_PATH = BEST_BETS_DIR / "wnba_best_bets_today.csv"
BEST_BETS_RECORD_PAGE_PATH = BEST_BETS_DIR / "results_page.html"
PROJECTIONS_ARCHIVE_DIR = ARCHIVE_DIR / "projections"
BEST_BETS_ARCHIVE_DIR_DATED = ARCHIVE_DIR / "best_bets"

UNMATCHED_PLAYERS_PATH = BEST_BETS_DIR / "unmatched_players_today.csv"
UNMATCHED_STATS_PATH = BEST_BETS_DIR / "unmatched_stats_today.csv"
MATCH_AUDIT_PATH = BEST_BETS_DIR / "match_audit_today.csv"

MINUTES_MODEL_PATH = MODELS_DIR / "wnba_minutes_model.joblib"
STAT_MODEL_TEMPLATE = "wnba_{stat}_model.joblib"

STAT_TARGETS = ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]
STAT_ALIASES = {
    "points": "pts",
    "rebounds": "reb",
    "assists": "ast",
    "threes_made": "fg3m",
    "steals": "stl",
    "blocks": "blk",
}

ROLLING_WINDOWS = (3, 5, 10)
MONTE_CARLO_SIMS = 10000
RANDOM_SEED = 42

TRAIN_CUTOFF_DATE = os.environ.get("WNBA_TRAIN_CUTOFF_DATE") or None
TODAY_OVERRIDE = os.environ.get("WNBA_TODAY_OVERRIDE") or None
