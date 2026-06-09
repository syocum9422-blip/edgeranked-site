#!/usr/bin/env bash
# Linux-safe nightly MLB grading + reporting.
#
# This script INGESTS yesterday's MLB results, updates hitter_tracking.csv
# and pitcher_tracking.csv, refreshes calibration reports, runs the shadow
# subsystem in grading-only mode, and writes learning/reports/latest_*.
#
# It does NOT:
#   - retrain any live model (no .pkl writes under mlb/models/)
#   - touch frontend/public CSVs in /home/ubuntu/edgeranked-sportsai/
#   - modify projection formulas
#   - promote shadow models
#   - install itself in cron
#
# Modes:
#   bash run_mlb_grading_night.sh            # full run
#   bash run_mlb_grading_night.sh --dry-run  # print steps, write no live files
#
# Logs land under /home/ubuntu/EdgeRanked/site/logs/cron/mlb_grading/<UTC_STAMP>/

set -uo pipefail

DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run|-n) DRY_RUN=1 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

PY="${MLB_GRADING_PYTHON:-python3}"
PROJECT_ROOT="/home/ubuntu"
MLB_DIR="/home/ubuntu/mlb_model"
LOG_ROOT="/home/ubuntu/EdgeRanked/site/logs/cron/mlb_grading"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="$LOG_ROOT/$STAMP"
mkdir -p "$LOG_DIR"
SUMMARY_LOG="$LOG_DIR/summary.log"

log() {
    local msg="[$(date -u +%FT%TZ)] $*"
    echo "$msg" | tee -a "$SUMMARY_LOG"
}

# Run a single step, capture its own log, never abort the wrapper.
run_step() {
    local name="$1"
    shift
    local step_log="$LOG_DIR/${name}.log"
    log "STEP START: $name"
    if [ "$DRY_RUN" -eq 1 ]; then
        log "DRY-RUN would execute: $*  (log -> $step_log)"
        log "STEP SKIP (dry-run): $name"
        return 0
    fi
    if ( cd "$MLB_DIR" && "$@" ) >"$step_log" 2>&1; then
        log "STEP OK: $name  (log -> $step_log)"
        return 0
    else
        local rc=$?
        log "STEP FAIL ($rc): $name  (log -> $step_log)"
        return 0  # never propagate; grading must not abort the wrapper
    fi
}

log "=== MLB GRADING NIGHT START dry_run=$DRY_RUN ==="
log "log_dir=$LOG_DIR python=$PY"

# Snapshot LIVE invariants BEFORE the run so we can detect any accidental write.
LIVE_INVARIANT_FILE="$LOG_DIR/live_invariants_pre.txt"
{
    for f in "$MLB_DIR"/mlb/models/*.pkl \
             /home/ubuntu/edgeranked-sportsai/mlb/outputs/hitter_predictions_full.csv \
             /home/ubuntu/edgeranked-sportsai/mlb/outputs/mlb_pitcher_projections_today.csv \
             /home/ubuntu/edgeranked-sportsai/mlb/outputs/pitcher_props_today.csv; do
        [ -f "$f" ] && stat -c '%Y %s %n' "$f"
    done
} | sort > "$LIVE_INVARIANT_FILE"

# Step 1: grade hitters → updates hitter_tracking.csv
run_step "01_grade_hitters"             "$PY" auto_grade_hitters_api.py

# Step 2: grade pitchers → updates pitcher_tracking.csv
run_step "02_grade_pitchers"            "$PY" auto_grade_pitchers_api.py

# Step 3: grade betting sheet → updates bet_history.csv
run_step "03_grade_betting_sheet"       "$PY" grade_betting_sheet_api.py

# Step 4: hitter calibration report → hitter_calibration_report.csv
run_step "04_hitter_calibration"        "$PY" hitter_calibration_report.py

# Step 5: pitcher calibration report → pitcher_calibration_report.csv
run_step "05_pitcher_calibration"       "$PY" pitcher_calibration_report.py

# Step 6: shadow grading-only — ingest tracking snapshots + feature store
# Uses module form so the orchestrator's relative imports resolve.
run_step "06_shadow_grading_only"       "$PY" -c "import sys; sys.path.insert(0, '$PROJECT_ROOT'); from mlb_model.learning.shadow.orchestrator import run; run('grading-only')"

# Step 7: latest grading + learning report
run_step "07_latest_report"             "$PY" -c "import sys; sys.path.insert(0, '$PROJECT_ROOT'); from mlb_model.learning.build_latest_report import run; run()"

# Verify LIVE invariants did not change
LIVE_INVARIANT_POST="$LOG_DIR/live_invariants_post.txt"
{
    for f in "$MLB_DIR"/mlb/models/*.pkl \
             /home/ubuntu/edgeranked-sportsai/mlb/outputs/hitter_predictions_full.csv \
             /home/ubuntu/edgeranked-sportsai/mlb/outputs/mlb_pitcher_projections_today.csv \
             /home/ubuntu/edgeranked-sportsai/mlb/outputs/pitcher_props_today.csv; do
        [ -f "$f" ] && stat -c '%Y %s %n' "$f"
    done
} | sort > "$LIVE_INVARIANT_POST"

if diff -q "$LIVE_INVARIANT_FILE" "$LIVE_INVARIANT_POST" > /dev/null; then
    log "LIVE INVARIANTS UNCHANGED (no model pickles or frontend CSVs modified)"
else
    log "WARNING: live invariants drift detected — see diff below"
    diff "$LIVE_INVARIANT_FILE" "$LIVE_INVARIANT_POST" | tee -a "$SUMMARY_LOG"
fi

log "=== MLB GRADING NIGHT END dry_run=$DRY_RUN ==="
