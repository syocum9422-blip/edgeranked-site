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

DEFAULT_UFC_PIPELINE_DIR="$(resolve_first_dir \
  "${EDGERANKED_UFC_PIPELINE_DIR:-}" \
  "$SITE_PARENT_DIR/sports/ufc")"
UFC_PIPELINE_DIR="${EDGERANKED_UFC_PIPELINE_DIR:-${EDGERANKED_UFC_BASE_DIR:-$DEFAULT_UFC_PIPELINE_DIR}}"
UFC_PYTHON_BIN="${UFC_PYTHON_BIN:-$UFC_PIPELINE_DIR/.venv/bin/python}"

if [[ ! -x "$UFC_PYTHON_BIN" ]]; then
  UFC_PYTHON_BIN="python3"
fi

export EDGERANKED_UFC_BASE_DIR="${EDGERANKED_UFC_BASE_DIR:-$LIVE_SITE_DIR/data/ufc}"
export EDGERANKED_LIVE_SITE_DIR="$LIVE_SITE_DIR"
export EDGERANKED_SITE_REPO_DIR="$SITE_REPO_DIR"

cd "$UFC_PIPELINE_DIR"

if [[ -f "$UFC_PIPELINE_DIR/refresh_ufc_site.py" ]]; then
  "$UFC_PYTHON_BIN" "$UFC_PIPELINE_DIR/refresh_ufc_site.py" -- --site-only
else
  "$UFC_PYTHON_BIN" "$UFC_PIPELINE_DIR/run_ufc_model.py"
fi
