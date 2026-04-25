# EdgeRanked Repo Paths

This server has multiple NBA/site repo-looking directories. Treat only one as
the scheduled NBA projection source of truth.

## Production Scheduled NBA Repo

Cron uses:

```text
/home/ubuntu/EdgeRanked/site
```

The production NBA projection file to edit is:

```text
/home/ubuntu/EdgeRanked/site/nba_model/projections/service.py
```

The installed AWS crontab should point NBA jobs at:

```text
EDGERANKED_SITE_REPO_DIR=/home/ubuntu/EdgeRanked/site
EDGERANKED_NBA_BASE_DIR=/home/ubuntu/EdgeRanked/site
PYTHON_BIN=/home/ubuntu/EdgeRanked/site/.venv/bin/python
```

Going forward, NBA model, pipeline, cron, and projection edits should be made
under `/home/ubuntu/EdgeRanked/site`.

## Live Web App / Publish Target

Gunicorn should be checked with:

```bash
systemctl show <gunicorn-service> -p WorkingDirectory
```

The current publish scripts default the live site directory to:

```text
/home/ubuntu/edgeranked-sportsai
```

This path should be treated as the live web app / publish target unless the
Gunicorn unit proves otherwise. Do not edit NBA model source here unless a
deployment/publish workflow explicitly requires syncing generated app assets.

## Legacy / Stale Copy

Treat this path as legacy/stale unless proven otherwise:

```text
/home/ubuntu/NBA_Model
```

Do not edit NBA production code there. Do not rely on files there for cron.
Do not delete it in cleanup passes unless a separate backup/retention decision
has been made.

## Do Edit

Edit these paths for production NBA work:

```text
/home/ubuntu/EdgeRanked/site/nba_model/projections/service.py
/home/ubuntu/EdgeRanked/site/scripts/aws/*
/home/ubuntu/EdgeRanked/site/scripts/run_nba_*.sh
/home/ubuntu/EdgeRanked/site/teams_today.csv
/home/ubuntu/EdgeRanked/site/lines_today.csv
/home/ubuntu/EdgeRanked/site/game_lines_today.csv
```

## Do Not Edit For NBA Model Changes

Avoid NBA model edits in:

```text
/home/ubuntu/edgeranked-sportsai
/home/ubuntu/NBA_Model
```

`/home/ubuntu/edgeranked-sportsai` may need publish syncs for live web assets,
but it is not the scheduled NBA projection source of truth.
