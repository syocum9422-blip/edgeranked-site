#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LIVE_SITE_DIR="${EDGERANKED_LIVE_SITE_DIR:-/home/ubuntu/edgeranked-sportsai}"
ENV_FILE="${EDGERANKED_ENV_FILE:-/home/ubuntu/.edgeranked_env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

export EDGERANKED_SITE_REPO_DIR="${EDGERANKED_SITE_REPO_DIR:-$REPO_DIR}"
export EDGERANKED_NBA_BASE_DIR="${EDGERANKED_NBA_BASE_DIR:-$REPO_DIR}"
export EDGERANKED_MLB_BASE_DIR="${EDGERANKED_MLB_BASE_DIR:-$REPO_DIR}"
export EDGERANKED_MLB_SOURCE_DIR="${EDGERANKED_MLB_SOURCE_DIR:-${EDGERANKED_MLB_PIPELINE_DIR:-$REPO_DIR}}"
export EDGERANKED_LIVE_SITE_DIR="$LIVE_SITE_DIR"
export EDGERANKED_PUBLISH_SPORTS="${EDGERANKED_PUBLISH_SPORTS:-nba}"
export PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"

cd "$REPO_DIR"
bash "$REPO_DIR/scripts/run_nba_manual_refresh.sh"
bash "$REPO_DIR/scripts/publish_render_site.sh"
