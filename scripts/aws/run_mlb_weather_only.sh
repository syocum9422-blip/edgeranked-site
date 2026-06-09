#!/usr/bin/env bash
set -euo pipefail

SITE="/home/ubuntu/EdgeRanked/site"
LIVE="/home/ubuntu/edgeranked-sportsai"
LOG_DIR="$SITE/logs/cron"

mkdir -p "$LOG_DIR"
mkdir -p "$SITE/mlb/outputs"
mkdir -p "$LIVE/mlb/outputs"

cd "$SITE"

echo "[MLB WEATHER ONLY] $(date -Is) starting"

source "$SITE/venv/bin/activate"

python3 "$SITE/scripts/mlb_weather/build_mlb_weather_today.py" \
  --output "$SITE/mlb/outputs/mlb_weather_today.json"

python3 "$SITE/scripts/mlb_weather/validate_mlb_weather_today.py" \
  --input "$SITE/mlb/outputs/mlb_weather_today.json"

echo "[MLB WEATHER ONLY] Publishing weather board to live site..."

cp -f "$SITE/mlb/outputs/mlb_weather_today.json" \
      "$LIVE/mlb/outputs/mlb_weather_today.json"

echo "[MLB WEATHER ONLY] Published: $LIVE/mlb/outputs/mlb_weather_today.json"

echo "[MLB WEATHER ONLY] $(date -Is) done"
