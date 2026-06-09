#!/usr/bin/env bash
# Linux-safe nightly entrypoint for the MLB shadow learning subsystem.
#
# This script is INTENTIONALLY not scheduled in cron. Operations team
# adds the cron line manually after dry-run validation. See the README in
# /home/ubuntu/mlb_model/learning/shadow/README.md for the full
# activation procedure.
#
# Modes:
#   grading-only   ingest live tracking → shadow snapshots, build features
#   dry-run        grading-only + emit shadow predictions/comparisons
#   full-shadow    everything + retrain shadow models (creates a new version)
#
# Usage:
#   bash run_mlb_learning_night.sh grading-only
#   bash run_mlb_learning_night.sh dry-run [--date YYYY-MM-DD]
#   bash run_mlb_learning_night.sh full-shadow [--date YYYY-MM-DD]
#
# This script touches ONLY paths under /home/ubuntu/mlb_model/learning/shadow_*.

set -euo pipefail

MODE="${1:-grading-only}"
shift || true

PY="${MLB_LEARNING_PYTHON:-python3}"
PROJECT_ROOT="/home/ubuntu"
LOG_DIR="/home/ubuntu/EdgeRanked/site/logs/cron"
mkdir -p "$LOG_DIR"

case "$MODE" in
    grading-only|dry-run|full-shadow)
        ;;
    *)
        echo "Usage: $0 {grading-only|dry-run|full-shadow} [--date YYYY-MM-DD]" >&2
        exit 2
        ;;
esac

cd "$PROJECT_ROOT"
echo "=== MLB SHADOW LEARNING START $(date -u +%FT%TZ) mode=$MODE ==="
"$PY" -m mlb_model.learning.shadow.orchestrator --mode "$MODE" "$@"
echo "=== MLB SHADOW LEARNING END   $(date -u +%FT%TZ) ==="
