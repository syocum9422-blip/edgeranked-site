#!/usr/bin/env bash
#
# EdgeRanked WNBA V2 — daily data-prep jobs (fail-closed, last-good protected).
#
#   1. Incremental ESPN team box-score refresh (current season; cache preserved)
#   2. Game spread/total capture via The Odds API (no-ops safely if no key)
#   3. PrizePicks prop open/close consolidation (keeps CLV history current)
#
# Each job is isolated: a failure in one is logged and does NOT abort the others,
# and no job overwrites last-good data unless its validation passes (enforced in
# the Python layer). Safe to run repeatedly; the ESPN summary cache makes the
# box-score refresh fetch only games it hasn't seen.
#
# Usage:  run_wnba_v2_data.sh [all|boxscores|lines|props]   (default: all)

set -uo pipefail

ENV_FILE="${EDGERANKED_ENV_FILE:-/home/ubuntu/.edgeranked_env}"
[ -f "$ENV_FILE" ] && set -a && source "$ENV_FILE" && set +a

WNBA_DIR="${EDGERANKED_WNBA_BASE_DIR:-/home/ubuntu/EdgeRanked/sports/wnba}"
WNBA_PY="${WNBA_PYTHON_BIN:-$WNBA_DIR/.venv/bin/python}"
LOG_DIR="${EDGERANKED_CRON_LOG_DIR:-/home/ubuntu/EdgeRanked/site/logs/cron}"
SEASON="${WNBA_V2_CURRENT_SEASON:-$(date +%Y)}"
MODE="${1:-all}"
mkdir -p "$LOG_DIR"

cd "$WNBA_DIR" || { echo "FATAL: cannot cd $WNBA_DIR"; exit 1; }

rc_overall=0
run_job() {
  local name="$1"; shift
  echo "----- [$(date -u +%FT%TZ)] START $name -----"
  if "$@"; then
    echo "----- DONE  $name (ok) -----"
  else
    local rc=$?
    echo "----- FAIL  $name (rc=$rc) — last-good preserved, continuing -----"
    rc_overall=1
  fi
}

if [ "$MODE" = "all" ] || [ "$MODE" = "boxscores" ]; then
  run_job "team_boxscores(incremental $SEASON)" \
    "$WNBA_PY" -m wnba_v2.data.team_boxscores incremental "$SEASON"
fi

if [ "$MODE" = "all" ] || [ "$MODE" = "lines" ]; then
  run_job "capture_game_lines" "$WNBA_PY" - <<'PY'
from wnba_v2.data.line_capture import TheOddsAPIFetcher, capture_game_lines, consolidate_game_lines
n = capture_game_lines(TheOddsAPIFetcher())   # no key -> 0, no error
print(f"game lines captured: {n}")
if n:
    consolidate_game_lines()
PY
fi

if [ "$MODE" = "all" ] || [ "$MODE" = "props" ]; then
  run_job "consolidate_prop_snapshots" "$WNBA_PY" - <<'PY'
from wnba_v2.data.line_capture import consolidate_prop_snapshots
out = consolidate_prop_snapshots()
print(f"prop open/close rows consolidated (latest day): {len(out)}")
PY
fi

echo "===== run_wnba_v2_data.sh ($MODE) finished rc=$rc_overall ====="
exit $rc_overall
