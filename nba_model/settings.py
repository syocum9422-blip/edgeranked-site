import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

BASE_DIR = os.environ.get("EDGERANKED_NBA_BASE_DIR", str(PROJECT_ROOT))

BEST_BETS_DIR = os.path.join(BASE_DIR, "Best_Bets")
BEST_BETS_ARCHIVE_DIR = os.path.join(BEST_BETS_DIR, "archive")

LINES_PATH = os.path.join(BASE_DIR, "lines_today.csv")
GAME_LINES_PATH = os.path.join(BASE_DIR, "game_lines_today.csv")
RAW_GAMES_PATH = os.path.join(BASE_DIR, "raw_games.csv")
LINEUP_STINTS_PATH = os.path.join(BASE_DIR, "lineup_stints.csv")
ROTATION_TEMPLATES_PATH = os.path.join(BASE_DIR, "rotation_templates.csv")
TEAMS_TODAY_PATH = os.path.join(BASE_DIR, "teams_today.csv")
PROJECTIONS_PATH = os.path.join(BASE_DIR, "projections.csv")
PROJECTIONS_APP_VIEW_PATH = os.path.join(BASE_DIR, "Projections_app_view.csv")

INJURY_CSV_PATH = os.path.join(BASE_DIR, "injured_players.csv")
INJURY_TXT_PATH = os.path.join(BASE_DIR, "injured_players.txt")

ALIASES_PATH = os.path.join(BASE_DIR, "name_aliases.csv")
BEST_BETS_OUTPUT_PATH = os.path.join(BEST_BETS_DIR, "nba_best_bets_today.csv")

UNMATCHED_PLAYERS_PATH = os.path.join(BEST_BETS_DIR, "unmatched_players_today.csv")
UNMATCHED_STATS_PATH = os.path.join(BEST_BETS_DIR, "unmatched_stats_today.csv")
MATCH_AUDIT_PATH = os.path.join(BEST_BETS_DIR, "match_audit_today.csv")
HISTORY_PATH = os.path.join(BEST_BETS_DIR, "nba_bets_history.csv")
GRADED_OUTPUT_PATH = os.path.join(BEST_BETS_DIR, "graded_bets.csv")
CALIBRATION_FACTORS_PATH = os.path.join(BEST_BETS_DIR, "calibration_factors.json")
RECORD_SUMMARY_PATH = os.path.join(BEST_BETS_DIR, "record_summary.csv")
CALIBRATION_SUMMARY_PATH = os.path.join(BEST_BETS_DIR, "calibration_summary.csv")
CALIBRATION_REPORT_PATH = os.path.join(BEST_BETS_DIR, "calibration_report.txt")
RESULTS_PAGE_PATH = os.path.join(BEST_BETS_DIR, "results_page.html")
