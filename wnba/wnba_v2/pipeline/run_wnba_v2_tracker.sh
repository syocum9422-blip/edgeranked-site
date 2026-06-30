#!/usr/bin/env bash
#
# EdgeRanked WNBA V2 — parallel-tracker daily run (shadow production; READ-ONLY to
# the live product). Scores the slate with V2, records recommendations + CLV, grades
# completed games, refreshes the dashboard and the promotion/rollback gate.
#
# Never touches live serving: the gate writes a PROMOTE signal only; flipping the
# live product remains an explicit, separate action. Fail-soft (per-stage).
#
# Run after the nightly data refresh (run_wnba_v2_data.sh all).

set -uo pipefail

ENV_FILE="${EDGERANKED_ENV_FILE:-/home/ubuntu/.edgeranked_env}"
[ -f "$ENV_FILE" ] && set -a && source "$ENV_FILE" && set +a

WNBA_DIR="${EDGERANKED_WNBA_BASE_DIR:-/home/ubuntu/EdgeRanked/sports/wnba}"
WNBA_PY="${WNBA_PYTHON_BIN:-$WNBA_DIR/.venv/bin/python}"
LOG_DIR="${EDGERANKED_CRON_LOG_DIR:-/home/ubuntu/EdgeRanked/site/logs/cron}"
mkdir -p "$LOG_DIR"

cd "$WNBA_DIR" || { echo "FATAL: cannot cd $WNBA_DIR"; exit 1; }
echo "----- [$(date -u +%FT%TZ)] WNBA V2 tracker start -----"
"$WNBA_PY" -m wnba_v2.tracker.daily_run
rc=$?
echo "----- WNBA V2 tracker done (rc=$rc) -----"
exit $rc
