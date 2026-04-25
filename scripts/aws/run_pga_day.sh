#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LIVE_SITE_DIR="${EDGERANKED_LIVE_SITE_DIR:-/home/ubuntu/edgeranked-sportsai}"
ENV_FILE="${EDGERANKED_ENV_FILE:-/home/ubuntu/.edgeranked_env}"
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

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

DEFAULT_PGA_PIPELINE_DIR="$(resolve_first_dir \
  "${EDGERANKED_PGA_PIPELINE_DIR:-}" \
  "${EDGERANKED_PGA_BASE_DIR:-}" \
  "$SITE_PARENT_DIR/sports/pga")"
PGA_PIPELINE_DIR="${EDGERANKED_PGA_PIPELINE_DIR:-${EDGERANKED_PGA_BASE_DIR:-$DEFAULT_PGA_PIPELINE_DIR}}"
PGA_PYTHON_BIN="${PGA_PYTHON_BIN:-$PGA_PIPELINE_DIR/.venv/bin/python}"

if [[ ! -x "$PGA_PYTHON_BIN" ]]; then
  PGA_PYTHON_BIN="python3"
fi

export EDGERANKED_PGA_BASE_DIR="$PGA_PIPELINE_DIR"
export EDGERANKED_LIVE_SITE_DIR="$LIVE_SITE_DIR"

cd "$PGA_PIPELINE_DIR"

if [[ -f "$PGA_PIPELINE_DIR/generate_bets.py" ]]; then
  "$PGA_PYTHON_BIN" "$PGA_PIPELINE_DIR/generate_bets.py" --round auto
else
  "$PGA_PYTHON_BIN" "$PGA_PIPELINE_DIR/src/main.py"
fi
