#!/bin/zsh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

cd "$ROOT" || exit 1

"$PYTHON_BIN" fetch_games.py || exit 1
"$PYTHON_BIN" build_dataset.py || exit 1
"$PYTHON_BIN" train_models.py || exit 1
"$PYTHON_BIN" train_minutes_model.py || exit 1
"$PYTHON_BIN" fetch_today_teams.py || exit 1
"$PYTHON_BIN" predict_today.py || exit 1
