#!/usr/bin/env bash
set -euo pipefail

SCHEDULED_REPO="${EDGERANKED_SITE_REPO_DIR:-/home/ubuntu/EdgeRanked/site}"
LIVE_SITE_DIR="${EDGERANKED_LIVE_SITE_DIR:-/home/ubuntu/edgeranked-sportsai}"
LEGACY_NBA_DIR="${EDGERANKED_LEGACY_NBA_DIR:-/home/ubuntu/NBA_Model}"
SERVICE_FILE="$SCHEDULED_REPO/nba_model/projections/service.py"

echo "=== EdgeRanked repo path verification ==="
echo "Scheduled NBA repo: $SCHEDULED_REPO"
echo "Live site dir default: $LIVE_SITE_DIR"
echo "Legacy NBA dir: $LEGACY_NBA_DIR"
echo

echo "-- Cron NBA path --"
if command -v crontab >/dev/null 2>&1 && crontab -l >/tmp/edgeranked_cron_check.$$ 2>/dev/null; then
  grep -E 'EDGERANKED_SITE_REPO_DIR=|EDGERANKED_NBA_BASE_DIR=|PYTHON_BIN=|run_nba_day.sh' /tmp/edgeranked_cron_check.$$ || true
else
  echo "WARNING: unable to read installed crontab for current user."
fi
rm -f /tmp/edgeranked_cron_check.$$
if [[ -f "$SCHEDULED_REPO/scripts/aws/aws_crontab.txt" ]]; then
  echo "Repo crontab reference:"
  grep -E 'EDGERANKED_SITE_REPO_DIR=|EDGERANKED_NBA_BASE_DIR=|PYTHON_BIN=|run_nba_day.sh' "$SCHEDULED_REPO/scripts/aws/aws_crontab.txt" || true
fi
echo

echo "-- Gunicorn WorkingDirectory --"
if command -v systemctl >/dev/null 2>&1; then
  mapfile -t gunicorn_units < <(systemctl list-units --type=service --all --no-legend 2>/dev/null | awk '/gunicorn|edgeranked|sportsai/ {print $1}')
  if [[ "${#gunicorn_units[@]}" -eq 0 ]]; then
    echo "WARNING: no obvious Gunicorn/EdgeRanked systemd service found."
  else
    for unit in "${gunicorn_units[@]}"; do
      wd="$(systemctl show "$unit" -p WorkingDirectory --value 2>/dev/null || true)"
      echo "$unit WorkingDirectory=${wd:-<empty>}"
    done
  fi
else
  echo "WARNING: systemctl not available; cannot inspect Gunicorn WorkingDirectory."
fi
echo

echo "-- Realism patch markers --"
if [[ -f "$SERVICE_FILE" ]]; then
  echo "Checking $SERVICE_FILE"
  for marker in \
    "apply_playoff_team_simulated_minute_reconciliation_to_cores" \
    "PLAYOFF_PRIOR_KIND" \
    "MARKET_GUARDRAIL_MODE" \
    "filter_playoff_projection_universe"; do
    if grep -q "$marker" "$SERVICE_FILE"; then
      echo "OK: found marker $marker"
    else
      echo "WARNING: missing realism patch marker $marker"
    fi
  done
else
  echo "ERROR: scheduled service file not found: $SERVICE_FILE"
fi
echo

echo "-- Legacy/stale path warnings --"
if [[ -d "$LEGACY_NBA_DIR" ]]; then
  echo "WARNING: legacy NBA path exists: $LEGACY_NBA_DIR"
  if [[ -f "$LEGACY_NBA_DIR/nba_model/projections/service.py" ]]; then
    if ! grep -q "apply_playoff_team_simulated_minute_reconciliation_to_cores" "$LEGACY_NBA_DIR/nba_model/projections/service.py"; then
      echo "WARNING: $LEGACY_NBA_DIR appears stale; realism patch marker is absent."
    else
      echo "NOTE: $LEGACY_NBA_DIR contains the realism marker, but it is still not the scheduled cron repo."
    fi
  fi
else
  echo "OK: legacy NBA path not present."
fi
echo

echo "-- Edits outside scheduled repo --"
for other in "$LIVE_SITE_DIR" "$LEGACY_NBA_DIR"; do
  if [[ -d "$other/.git" ]]; then
    status="$(git -C "$other" status --short 2>/dev/null || true)"
    if [[ -n "$status" ]]; then
      echo "WARNING: git changes detected outside scheduled repo: $other"
      echo "$status"
    else
      echo "OK: no git changes in $other"
    fi
  elif [[ -d "$other" ]]; then
    echo "NOTE: $other exists but is not a git repo or git metadata is unavailable."
  fi
done

echo "=== End repo path verification ==="
