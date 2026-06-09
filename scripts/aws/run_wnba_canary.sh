#!/usr/bin/env bash
# WNBA Phase 6 weekly canary: shadow-only Production-vs-VariantC validation + promotion
# readiness scorecard. Reads production models read-only; writes only to outputs/phase6.
# Does NOT modify any production artifact.
set -euo pipefail

ENV_FILE="/home/ubuntu/.edgeranked_env"
if [ -f "$ENV_FILE" ]; then
  source "$ENV_FILE"
fi

LOG_DIR="${EDGERANKED_CRON_LOG_DIR:-/home/ubuntu/EdgeRanked/site/logs/cron}"
mkdir -p "$LOG_DIR"

WNBA_DIR="${EDGERANKED_WNBA_BASE_DIR:-/home/ubuntu/EdgeRanked/sports/wnba}"
WNBA_PY="${WNBA_PYTHON_BIN:-$WNBA_DIR/.venv/bin/python}"
SIMS="${WNBA_CANARY_SIMS:-8000}"

cd "$WNBA_DIR"
echo "[$(date -u +%FT%TZ)] WNBA canary start (sims=$SIMS)"
"$WNBA_PY" wnba_canary_validation.py --sims "$SIMS"
"$WNBA_PY" wnba_promotion_readiness.py
echo "[$(date -u +%FT%TZ)] WNBA canary done"
