#!/usr/bin/env bash
set -euo pipefail

cd /srv/edgeranked-prod

git fetch origin main
git checkout main
git pull --ff-only origin main

set -a
source /home/ubuntu/.edgeranked_env
set +a

venv/bin/python -m py_compile app.py wsgi.py
venv/bin/python -c "import wsgi; print('wsgi import ok')"

sudo systemctl restart edgerankai.service
sleep 3
sudo systemctl status edgerankai.service --no-pager
