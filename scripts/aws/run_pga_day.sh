#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LIVE_SITE_DIR="${EDGERANKED_LIVE_SITE_DIR:-/home/ubuntu/edgeranked-sportsai}"
ENV_FILE="${EDGERANKED_ENV_FILE:-/home/ubuntu/.edgeranked_env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ -z "${EDGERANKED_PGA_BASE_DIR:-}" ]]; then
  echo "ERROR: EDGERANKED_PGA_BASE_DIR is required for PGA production runs." >&2
  echo "Set it in $ENV_FILE, cron, and the Gunicorn systemd environment." >&2
  exit 64
fi

PGA_PIPELINE_DIR="${EDGERANKED_PGA_PIPELINE_DIR:-$EDGERANKED_PGA_BASE_DIR}"

if [[ "$PGA_PIPELINE_DIR" != "$EDGERANKED_PGA_BASE_DIR" ]]; then
  echo "ERROR: EDGERANKED_PGA_PIPELINE_DIR must match EDGERANKED_PGA_BASE_DIR in production." >&2
  echo "EDGERANKED_PGA_BASE_DIR=$EDGERANKED_PGA_BASE_DIR" >&2
  echo "EDGERANKED_PGA_PIPELINE_DIR=$PGA_PIPELINE_DIR" >&2
  exit 64
fi

if [[ ! -d "$PGA_PIPELINE_DIR" ]]; then
  echo "ERROR: PGA pipeline directory does not exist: $PGA_PIPELINE_DIR" >&2
  exit 66
fi

if [[ ! -f "$PGA_PIPELINE_DIR/generate_bets.py" && ! -f "$PGA_PIPELINE_DIR/src/main.py" ]]; then
  echo "ERROR: PGA pipeline entrypoint not found under $PGA_PIPELINE_DIR" >&2
  exit 66
fi

if [[ -d "$PGA_PIPELINE_DIR/data" ]]; then
  find "$PGA_PIPELINE_DIR/data" -name '._*.json' -type f -delete
fi

PGA_PYTHON_BIN="${PGA_PYTHON_BIN:-$PGA_PIPELINE_DIR/.venv/bin/python}"

if [[ ! -x "$PGA_PYTHON_BIN" ]]; then
  PGA_PYTHON_BIN="python3"
fi

export EDGERANKED_PGA_BASE_DIR="$PGA_PIPELINE_DIR"
export EDGERANKED_LIVE_SITE_DIR="$LIVE_SITE_DIR"
# Enable the validated hole-by-hole PGA simulation engine for production
# runs.  Operators can pin the legacy engine by exporting
# PGA_HOLE_BY_HOLE_SIM=0 in $EDGERANKED_ENV_FILE before this script runs.
export PGA_HOLE_BY_HOLE_SIM="${PGA_HOLE_BY_HOLE_SIM:-1}"

cd "$PGA_PIPELINE_DIR"

if [[ -f "$PGA_PIPELINE_DIR/generate_bets.py" ]]; then
  "$PGA_PYTHON_BIN" "$PGA_PIPELINE_DIR/generate_bets.py" --round auto
else
  "$PGA_PYTHON_BIN" "$PGA_PIPELINE_DIR/src/main.py"
fi
