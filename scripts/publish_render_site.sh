#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
LIVE_SITE_DIR="${EDGERANKED_LIVE_SITE_DIR:-/home/ubuntu/edgeranked-sportsai}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi
STAMP=$(date '+%Y-%m-%d %H:%M')
PUBLISH_SPORTS="${EDGERANKED_PUBLISH_SPORTS:-all}"

publish_sport_enabled() {
  local sport="$1"
  [[ "$PUBLISH_SPORTS" == "all" ]] && return 0
  IFS=',' read -ra requested <<< "$PUBLISH_SPORTS"
  for item in "${requested[@]}"; do
    item="$(echo "$item" | tr '[:upper:]' '[:lower:]' | xargs)"
    [[ "$item" == "$sport" ]] && return 0
  done
  return 1
}

validate_nba_freshness() {
  "$PYTHON_BIN" - "$ROOT" <<'PY'
import csv
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

root = Path(sys.argv[1])
today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()

checks = [
    ("projections.csv", "GAME_DATE"),
    ("game_lines_today.csv", "GAME_DATE"),
    ("Best_Bets/nba_best_bets_today.csv", "DATE"),
]

errors = []
for rel_path, date_column in checks:
    path = root / rel_path
    if not path.exists():
        errors.append(f"{rel_path} is missing")
        continue
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or date_column not in reader.fieldnames:
            errors.append(f"{rel_path} is missing {date_column}")
            continue
        dates = {
            (row.get(date_column) or "").strip()[:10]
            for row in reader
            if (row.get(date_column) or "").strip()
        }
    if today not in dates:
        latest = max(dates) if dates else "none"
        errors.append(f"{rel_path} latest {date_column}={latest}; expected {today}")

if errors:
    print("ERROR: Refusing to publish stale NBA files:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)

print(f"[site_publish] NBA freshness guard passed for {today}")
PY
}

sync_one() {
  local rel_path="$1"
  local source="$ROOT/$rel_path"
  local target="$LIVE_SITE_DIR/$rel_path"

  if [[ ! -e "$source" ]]; then
    echo "SKIP live sync: missing $source"
    return 0
  fi

  if [[ -d "$source" ]]; then
    mkdir -p "$target"
    cp -R "$source"/. "$target"/
  else
    mkdir -p "$(dirname "$target")"
    cp -R "$source" "$target"
  fi
  echo "SYNCED live file: $rel_path"
}

sync_live_site() {
  if [[ ! -d "$LIVE_SITE_DIR" ]]; then
    echo "Live site dir not found at $LIVE_SITE_DIR. Skipping live sync."
    return 0
  fi

  echo "Syncing refreshed files into live site: $LIVE_SITE_DIR"
  if publish_sport_enabled "nba"; then
    validate_nba_freshness
    echo "[site_publish] syncing NBA files"
    sync_one "projections.csv"
    sync_one "Projections_app_view.csv"
    sync_one "lines_today.csv"
    sync_one "game_lines_today.csv"
    sync_one "injured_players.csv"
    sync_one "teams_today.csv"
    sync_one "Best_Bets/nba_best_bets_today.csv"
    sync_one "Best_Bets/record_summary.csv"
    sync_one "Best_Bets/nba_bets_history.csv"
    sync_one "Best_Bets/graded_bets.csv"
    sync_one "Best_Bets/match_audit_today.csv"
    sync_one "Best_Bets/calibration_summary.csv"
    sync_one "Best_Bets/calibration_report.txt"
    sync_one "Best_Bets/results_page.html"
  fi
  if publish_sport_enabled "mlb"; then
    echo "[site_publish] syncing MLB files"
    sync_one "mlb/outputs"
    sync_one "data/mlb/lines_today.csv"
  fi
}

cd "$ROOT"

if ! "$PYTHON_BIN" "$ROOT/scripts/publish_render_snapshot.py"; then
  echo "ERROR: Snapshot refresh failed. Aborting live-site sync so stale or invalid MLB files are not published."
  exit 1
fi
sync_live_site

if ! command -v git >/dev/null 2>&1; then
  echo "Git is not installed. Skipping git publish."
  exit 0
fi

if [[ ! -d "$ROOT/.git" ]] || ! git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "No git repo in $ROOT. Skipping git publish."
  exit 0
fi

git add \
  projections.csv \
  Projections_app_view.csv \
  lines_today.csv \
  injured_players.csv \
  teams_today.csv \
  Best_Bets/nba_best_bets_today.csv \
  Best_Bets/record_summary.csv \
  Best_Bets/nba_bets_history.csv \
  Best_Bets/graded_bets.csv \
  Best_Bets/match_audit_today.csv \
  Best_Bets/calibration_summary.csv \
  Best_Bets/calibration_report.txt \
  Best_Bets/results_page.html \
  mlb/outputs \
  data/mlb/lines_today.csv \
  sports/mlb/outputs/site/hitter_summary_today.csv \
  sports/mlb/outputs/site/payload_manifest.json \
  sports/mlb/outputs/site/validation_manifest.json
if git diff --cached --quiet; then
  echo "No snapshot changes to publish."
  exit 0
fi

if ! git commit -m "Refresh Render snapshot ${STAMP}"; then
  echo "WARNING: Git commit step failed after live-site sync."
  exit 0
fi

if ! git push; then
  echo "WARNING: Git push failed after live-site sync."
  exit 0
fi
