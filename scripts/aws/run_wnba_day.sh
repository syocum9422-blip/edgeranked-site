#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="/home/ubuntu/.edgeranked_env"

if [ -f "$ENV_FILE" ]; then
  source "$ENV_FILE"
fi

LOG_DIR="${EDGERANKED_CRON_LOG_DIR:-/home/ubuntu/EdgeRanked/site/logs/cron}"
mkdir -p "$LOG_DIR"

WNBA_DIR="${EDGERANKED_WNBA_BASE_DIR:-/home/ubuntu/EdgeRanked/sports/wnba}"
WNBA_PY="${WNBA_PYTHON_BIN:-$WNBA_DIR/.venv/bin/python}"
FULL_RUN="${EDGERANKED_WNBA_FULL_RUN:-0}"
STATUS_PATH="$WNBA_DIR/data/processed/wnba_production_status.json"
LIVE_SITE_DIR="${EDGERANKED_LIVE_SITE_DIR:-/home/ubuntu/edgeranked-sportsai}"
LIVE_STATUS_PATH="$LIVE_SITE_DIR/wnba/data/processed/wnba_production_status.json"

print_final_status() {
  python3 - "$STATUS_PATH" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {}
if path.exists():
    try:
        payload = json.loads(path.read_text())
    except Exception as exc:
        payload = {"WNBA_PRODUCTION_STATUS": "FAIL", "error": f"could not read status file: {exc}"}
else:
    payload = {"WNBA_PRODUCTION_STATUS": "FAIL", "error": f"missing status file: {path}"}

print("===== WNBA FINAL PRODUCTION STATUS =====")
for key in [
    "WNBA_PRODUCTION_STATUS",
    "canonical_teams",
    "projected_teams",
    "included_players",
    "excluded_players",
    "excluded_reasons",
    "published",
    "stale_output_blocked",
]:
    value = payload.get(key)
    if isinstance(value, (list, dict)):
        value = json.dumps(value, sort_keys=True)
    print(f"{key}={value}")
if payload.get("error"):
    print(f"error={payload['error']}")
PY
}

mark_published() {
  python3 - "$STATUS_PATH" "$LIVE_STATUS_PATH" <<'PY'
import json
import sys
from pathlib import Path

for raw_path in sys.argv[1:]:
    path = Path(raw_path)
    if not path.exists():
        continue
    payload = json.loads(path.read_text())
    payload["published"] = "yes"
    payload["stale_output_blocked"] = "yes"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY
}

echo "===== WNBA RUN START $(date) ====="
echo "WNBA_DIR=$WNBA_DIR"
echo "FULL_RUN=$FULL_RUN"
echo "REQUIRE_LIVE_DATA=${EDGERANKED_WNBA_REQUIRE_LIVE_DATA:-0}"

cd "$WNBA_DIR"

if [ "$FULL_RUN" = "1" ]; then
  echo "Running WNBA grading workflow before refresh..."
  bash /home/ubuntu/EdgeRanked/site/scripts/aws/run_wnba_grade_and_publish.sh --grade-only || true
fi

set +e
if [ "$FULL_RUN" = "1" ]; then
  echo "Running FULL WNBA workflow"
  WNBA_SOURCE_MODE="${WNBA_SOURCE_MODE:-auto}" \
  EDGERANKED_WNBA_REQUIRE_LIVE_DATA="${EDGERANKED_WNBA_REQUIRE_LIVE_DATA:-0}" \
  "$WNBA_PY" run_wnba_model.py
  MODEL_STATUS=$?
else
  echo "Running REFRESH-ONLY WNBA workflow"
  WNBA_SOURCE_MODE="${WNBA_SOURCE_MODE:-auto}" \
  EDGERANKED_WNBA_REQUIRE_LIVE_DATA="${EDGERANKED_WNBA_REQUIRE_LIVE_DATA:-0}" \
  "$WNBA_PY" run_wnba_model.py
  MODEL_STATUS=$?
fi
set -e

if [ "$MODEL_STATUS" -ne 0 ]; then
  echo "ERROR: WNBA model run failed. Status file was written; skipping publish so stale slate is not refreshed as current."
  print_final_status
  exit "$MODEL_STATUS"
fi

cd /home/ubuntu/EdgeRanked/site

EDGERANKED_PUBLISH_SPORTS=wnba python3 scripts/publish_render_snapshot.py
EDGERANKED_PUBLISH_SPORTS=wnba bash scripts/publish_render_site.sh
mark_published
print_final_status
"$WNBA_PY" "$WNBA_DIR/daily_wnba_monitoring_summary.py" || echo "WARNING: WNBA monitoring summary generation failed."

echo "===== WNBA RUN COMPLETE $(date) ====="
