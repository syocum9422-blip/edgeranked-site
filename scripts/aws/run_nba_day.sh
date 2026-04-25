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
  echo "run_nba_day.sh: sourced secrets from $ENV_FILE"
else
  echo "run_nba_day.sh: WARNING — $ENV_FILE not found; ODDS_API_KEY and other secrets will not load" >&2
fi

# Deployment-only: fetch_nba_game_lines.py requires ODDS_API_KEY in the environment.
if [[ -z "${ODDS_API_KEY:-}" ]]; then
  echo "run_nba_day.sh: WARNING — ODDS_API_KEY is unset after env load; NBA game-line fetch will be skipped" >&2
fi

export EDGERANKED_SITE_REPO_DIR="${EDGERANKED_SITE_REPO_DIR:-$REPO_DIR}"
export EDGERANKED_NBA_BASE_DIR="${EDGERANKED_NBA_BASE_DIR:-$REPO_DIR}"
export EDGERANKED_MLB_BASE_DIR="${EDGERANKED_MLB_BASE_DIR:-$REPO_DIR}"
export EDGERANKED_MLB_SOURCE_DIR="${EDGERANKED_MLB_SOURCE_DIR:-${EDGERANKED_MLB_PIPELINE_DIR:-$REPO_DIR}}"
export EDGERANKED_PGA_BASE_DIR="${EDGERANKED_PGA_BASE_DIR:-${EDGERANKED_PGA_PIPELINE_DIR:-$REPO_DIR}}"
export EDGERANKED_LIVE_SITE_DIR="$LIVE_SITE_DIR"
export EDGERANKED_PUBLISH_SPORTS="${EDGERANKED_PUBLISH_SPORTS:-nba}"
export PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"

cd "$REPO_DIR"
echo "=== AWS NBA wrapper ==="
echo "Repo: $REPO_DIR"
echo "Publish scope: $EDGERANKED_PUBLISH_SPORTS"
exec bash "$REPO_DIR/scripts/run_nba_best_bets.sh"
