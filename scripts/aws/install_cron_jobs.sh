#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
REFERENCE_CRONTAB_FILE="$SCRIPT_DIR/aws_crontab.txt"
SITE_REPO_DIR="${EDGERANKED_SITE_REPO_DIR:-$REPO_DIR}"
LIVE_SITE_DIR="${EDGERANKED_LIVE_SITE_DIR:-/home/ubuntu/edgeranked-sportsai}"
SITE_PARENT_DIR="$(cd "$SITE_REPO_DIR/.." && pwd)"

resolve_first_dir() {
  for candidate in "$@"; do
    if [[ -n "$candidate" && -e "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  printf '%s\n' "$1"
}

NBA_BASE_DIR="${EDGERANKED_NBA_BASE_DIR:-$SITE_REPO_DIR}"
CANONICAL_MLB_ROOT="$SITE_PARENT_DIR/sports/mlb"
MLB_BASE_DIR="${EDGERANKED_MLB_BASE_DIR:-$CANONICAL_MLB_ROOT}"
MLB_SOURCE_DIR="$(resolve_first_dir \
  "${EDGERANKED_MLB_SOURCE_DIR:-}" \
  "$CANONICAL_MLB_ROOT" \
  "$SITE_PARENT_DIR/sports/mlb/mlb_model")"
MLB_PIPELINE_DIR="$(resolve_first_dir \
  "${EDGERANKED_MLB_PIPELINE_DIR:-}" \
  "$MLB_SOURCE_DIR/mlb_model" \
  "$SITE_PARENT_DIR/sports/mlb/mlb_model")"
PGA_BASE_DIR="$(resolve_first_dir \
  "${EDGERANKED_PGA_BASE_DIR:-}" \
  "${EDGERANKED_PGA_PIPELINE_DIR:-}" \
  "$SITE_PARENT_DIR/sports/pga")"
PGA_PIPELINE_DIR="${EDGERANKED_PGA_PIPELINE_DIR:-$PGA_BASE_DIR}"
UFC_BASE_DIR="${EDGERANKED_UFC_BASE_DIR:-$LIVE_SITE_DIR/data/ufc}"
UFC_PIPELINE_DIR="$(resolve_first_dir \
  "${EDGERANKED_UFC_PIPELINE_DIR:-}" \
  "$SITE_PARENT_DIR/sports/ufc")"
PYTHON_BIN="${PYTHON_BIN:-$SITE_REPO_DIR/.venv/bin/python}"
MLB_PYTHON_BIN="${MLB_PYTHON_BIN:-$MLB_BASE_DIR/.venv/bin/python}"
PGA_PYTHON_BIN="${PGA_PYTHON_BIN:-$PGA_PIPELINE_DIR/.venv/bin/python}"
UFC_PYTHON_BIN="${UFC_PYTHON_BIN:-$UFC_PIPELINE_DIR/.venv/bin/python}"
MLB_READER_MODE="${MLB_READER_MODE:-canonical}"
MLB_PUBLISH_MODE="${MLB_PUBLISH_MODE:-legacy}"
LOG_DIR="${EDGERANKED_CRON_LOG_DIR:-$SITE_REPO_DIR/logs/cron}"
TMP_CRONTAB="$(mktemp)"

mkdir -p "$LOG_DIR"
trap 'rm -f "$TMP_CRONTAB"' EXIT

cat <<EOF
Installing AWS cron jobs

Reference file:
  $REFERENCE_CRONTAB_FILE

Resolved paths:
  SITE_REPO_DIR=$SITE_REPO_DIR
  LIVE_SITE_DIR=$LIVE_SITE_DIR
  MLB_PIPELINE_DIR=$MLB_PIPELINE_DIR
  PGA_PIPELINE_DIR=$PGA_PIPELINE_DIR
  UFC_PIPELINE_DIR=$UFC_PIPELINE_DIR
  LOG_DIR=$LOG_DIR
EOF

cat >"$TMP_CRONTAB" <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CRON_TZ=America/New_York
EDGERANKED_SITE_REPO_DIR=$SITE_REPO_DIR
EDGERANKED_LIVE_SITE_DIR=$LIVE_SITE_DIR
EDGERANKED_NBA_BASE_DIR=$NBA_BASE_DIR
EDGERANKED_MLB_BASE_DIR=$MLB_BASE_DIR
EDGERANKED_MLB_SOURCE_DIR=$MLB_SOURCE_DIR
EDGERANKED_MLB_PIPELINE_DIR=$MLB_PIPELINE_DIR
EDGERANKED_PGA_BASE_DIR=$PGA_BASE_DIR
EDGERANKED_PGA_PIPELINE_DIR=$PGA_PIPELINE_DIR
EDGERANKED_UFC_BASE_DIR=$UFC_BASE_DIR
EDGERANKED_UFC_PIPELINE_DIR=$UFC_PIPELINE_DIR
PYTHON_BIN=$PYTHON_BIN
MLB_PYTHON_BIN=$MLB_PYTHON_BIN
PGA_PYTHON_BIN=$PGA_PYTHON_BIN
UFC_PYTHON_BIN=$UFC_PYTHON_BIN
MLB_READER_MODE=$MLB_READER_MODE
MLB_PUBLISH_MODE=$MLB_PUBLISH_MODE
EDGERANKED_CRON_LOG_DIR=$LOG_DIR

# NBA: run_nba_day.sh sources /home/ubuntu/.edgeranked_env — set ODDS_API_KEY there for game-line fetch.

# NBA jobs
15 9 * * * mkdir -p "\$EDGERANKED_CRON_LOG_DIR" && EDGERANKED_NBA_FULL_RUN=1 bash "\$EDGERANKED_SITE_REPO_DIR/scripts/aws/run_nba_day.sh" >> "\$EDGERANKED_CRON_LOG_DIR/nba_0915.log" 2>&1
0 15 * * * mkdir -p "\$EDGERANKED_CRON_LOG_DIR" && bash "\$EDGERANKED_SITE_REPO_DIR/scripts/aws/run_nba_day.sh" >> "\$EDGERANKED_CRON_LOG_DIR/nba_1500.log" 2>&1
15 18 * * * mkdir -p "\$EDGERANKED_CRON_LOG_DIR" && bash "\$EDGERANKED_SITE_REPO_DIR/scripts/aws/run_nba_day.sh" >> "\$EDGERANKED_CRON_LOG_DIR/nba_1815.log" 2>&1

# MLB jobs
0 9 * * * mkdir -p "\$EDGERANKED_CRON_LOG_DIR" && bash "\$EDGERANKED_SITE_REPO_DIR/scripts/aws/run_mlb_day.sh" >> "\$EDGERANKED_CRON_LOG_DIR/mlb_0900.log" 2>&1
0 14 * * * mkdir -p "\$EDGERANKED_CRON_LOG_DIR" && bash "\$EDGERANKED_SITE_REPO_DIR/scripts/aws/run_mlb_day.sh" >> "\$EDGERANKED_CRON_LOG_DIR/mlb_1400.log" 2>&1
15 18 * * * mkdir -p "\$EDGERANKED_CRON_LOG_DIR" && bash "\$EDGERANKED_SITE_REPO_DIR/scripts/aws/run_mlb_day.sh" >> "\$EDGERANKED_CRON_LOG_DIR/mlb_1815.log" 2>&1

# PGA jobs
# Tournament-day schedule requested for Thursday through Sunday at 6:30 AM ET.
30 6 * * 4-7 mkdir -p "\$EDGERANKED_CRON_LOG_DIR" && bash "\$EDGERANKED_SITE_REPO_DIR/scripts/aws/run_pga_day.sh" >> "\$EDGERANKED_CRON_LOG_DIR/pga_0630.log" 2>&1

# UFC jobs
# Assumption: Sunday and Wednesday refresh at 7:00 AM ET, plus an early Saturday pre-fight refresh at 6:00 AM ET.
0 7 * * 0 mkdir -p "\$EDGERANKED_CRON_LOG_DIR" && bash "\$EDGERANKED_SITE_REPO_DIR/scripts/aws/run_ufc_day.sh" >> "\$EDGERANKED_CRON_LOG_DIR/ufc_sun_0700.log" 2>&1
0 7 * * 3 mkdir -p "\$EDGERANKED_CRON_LOG_DIR" && bash "\$EDGERANKED_SITE_REPO_DIR/scripts/aws/run_ufc_day.sh" >> "\$EDGERANKED_CRON_LOG_DIR/ufc_wed_0700.log" 2>&1
0 6 * * 6 mkdir -p "\$EDGERANKED_CRON_LOG_DIR" && bash "\$EDGERANKED_SITE_REPO_DIR/scripts/aws/run_ufc_day.sh" >> "\$EDGERANKED_CRON_LOG_DIR/ufc_sat_0600.log" 2>&1
EOF

crontab "$TMP_CRONTAB"

echo ""
echo "Installed cron jobs:"
crontab -l
echo ""
echo "Manual run helpers:"
echo "  bash $REPO_DIR/scripts/aws/run_nba_manual_refresh_and_publish.sh"
echo "  bash $REPO_DIR/scripts/aws/run_nba_grade_and_publish.sh"
echo "  bash $REPO_DIR/scripts/aws/run_mlb_day.sh"
echo "  bash $REPO_DIR/scripts/aws/run_pga_day.sh"
echo "  bash $REPO_DIR/scripts/aws/run_ufc_day.sh"
