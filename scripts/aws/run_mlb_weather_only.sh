#!/usr/bin/env bash
set -euo pipefail

cd /home/ubuntu/EdgeRanked/site
source /home/ubuntu/EdgeRanked/site/venv/bin/activate

echo "[MLB WEATHER ONLY] $(date -Is) starting"

python3 /home/ubuntu/EdgeRanked/site/scripts/mlb_weather/build_mlb_weather_today.py \
  --output /home/ubuntu/EdgeRanked/site/mlb/outputs/mlb_weather_today.json

python3 /home/ubuntu/EdgeRanked/site/scripts/mlb_weather/validate_mlb_weather_today.py \
  --input /home/ubuntu/EdgeRanked/site/mlb/outputs/mlb_weather_today.json \
  || echo "[MLB WEATHER ONLY] WARNING: validation failed — continuing"

echo "[MLB WEATHER ONLY] $(date -Is) done"
