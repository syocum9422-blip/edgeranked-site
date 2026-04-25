#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

SITE_REPO_DIR="${EDGERANKED_SITE_REPO_DIR:-$REPO_DIR}"
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

MLB_PIPELINE_DIR="$(resolve_first_dir \
  "${EDGERANKED_MLB_PIPELINE_DIR:-}" \
  "${EDGERANKED_MLB_SOURCE_DIR:-}" \
  "$SITE_PARENT_DIR/sports/mlb/mlb_model")"
PGA_PIPELINE_DIR="$(resolve_first_dir \
  "${EDGERANKED_PGA_PIPELINE_DIR:-}" \
  "${EDGERANKED_PGA_BASE_DIR:-}" \
  "$SITE_PARENT_DIR/sports/pga")"
UFC_PIPELINE_DIR="$(resolve_first_dir \
  "${EDGERANKED_UFC_PIPELINE_DIR:-}" \
  "${EDGERANKED_UFC_BASE_DIR:-}" \
  "$SITE_PARENT_DIR/sports/ufc")"

SITE_VENV_PYTHON="${PYTHON_BIN:-$SITE_REPO_DIR/.venv/bin/python}"
MLB_VENV_PYTHON="${MLB_PYTHON_BIN:-$MLB_PIPELINE_DIR/.venv/bin/python}"
PGA_VENV_PYTHON="${PGA_PYTHON_BIN:-$PGA_PIPELINE_DIR/.venv/bin/python}"
UFC_VENV_PYTHON="${UFC_PYTHON_BIN:-$UFC_PIPELINE_DIR/.venv/bin/python}"

echo "AWS Lightsail bootstrap for EdgeRanked cron jobs"
echo ""
echo "Resolved paths:"
echo "  SITE_REPO_DIR=$SITE_REPO_DIR"
echo "  MLB_PIPELINE_DIR=$MLB_PIPELINE_DIR"
echo "  PGA_PIPELINE_DIR=$PGA_PIPELINE_DIR"
echo "  UFC_PIPELINE_DIR=$UFC_PIPELINE_DIR"
echo ""

chmod +x "$SCRIPT_DIR"/*.sh
chmod +x "$SITE_REPO_DIR"/scripts/*.sh

mkdir -p "$SITE_REPO_DIR/logs/cron"

require_path() {
  local path="$1"
  local label="$2"
  if [[ ! -e "$path" ]]; then
    echo "Missing $label: $path" >&2
    exit 1
  fi
}

require_optional_python() {
  local path="$1"
  local label="$2"
  if [[ -x "$path" ]]; then
    echo "Found $label: $path"
  else
    echo "Warning: $label not found at $path" >&2
    echo "Install its virtualenv before relying on cron for that pipeline." >&2
  fi
}

require_path "$SITE_REPO_DIR" "site repo"
require_path "$SITE_REPO_DIR/scripts/aws/install_cron_jobs.sh" "cron installer"
require_path "$SITE_REPO_DIR/scripts/aws/run_nba_day.sh" "NBA AWS wrapper"
require_path "$SITE_REPO_DIR/scripts/aws/run_mlb_day.sh" "MLB AWS wrapper"
require_path "$SITE_REPO_DIR/scripts/aws/run_pga_day.sh" "PGA AWS wrapper"
require_path "$SITE_REPO_DIR/scripts/aws/run_ufc_day.sh" "UFC AWS wrapper"
require_path "$MLB_PIPELINE_DIR" "MLB pipeline dir"
require_path "$PGA_PIPELINE_DIR" "PGA pipeline dir"
require_path "$UFC_PIPELINE_DIR" "UFC pipeline dir"

require_optional_python "$SITE_VENV_PYTHON" "site venv python"
require_optional_python "$MLB_VENV_PYTHON" "MLB venv python"
require_optional_python "$PGA_VENV_PYTHON" "PGA venv python"
require_optional_python "$UFC_VENV_PYTHON" "UFC venv python"

bash "$SITE_REPO_DIR/scripts/aws/install_cron_jobs.sh"

echo ""
echo "Bootstrap complete."
echo "Check installed jobs with:"
echo "  crontab -l"
echo "Check logs with:"
echo "  ls -lah $SITE_REPO_DIR/logs/cron"
