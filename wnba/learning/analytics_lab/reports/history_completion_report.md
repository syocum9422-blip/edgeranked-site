# Phase 2A — Historical completion report

**Date:** 2026-07-25  |  **Source:** local ESPN summary cache only, no network access

## Parse results

| | |
|---|---|
| Cache files discovered | 811 |
| Games successfully parsed | 811 |
| Games skipped | 0 |
| Parse failures | 0 |
| Player-game rows | 18,894 |
| Team-game rows | 1,622 |
| Date range (ET slate) | 2024-05-03 → 2026-07-22 |

The Phase 1 pipeline (`replay/build_history.py`) produced 17,360 player-game
rows through 2026-06-28, because it merged the V2 box-score CSV, last built
2026-07-01. Reparsing the cache directly adds **1,534 rows** and
closes the gap to the latest locally available game.

## Integrity

| Check | Result |
|---|---|
| Duplicate `(player_id, game_id)` | 0 |
| Duplicate `(team_id, game_id)` | 0 |
| Missing `player_id` | 0 |
| Missing `team_id` | 0 |
| Missing `opponent_id` | 0 |
| Missing tip-off time | 0 |
| Missing position | 0 |
| Team-games without exactly 5 starters | 0 |

## Season coverage

| Season | Type | Player-games | Games | Players | First | Last |
|---|---|---|---|---|---|---|
| 2024 | postseason | 517 | 22 | 95 | 2024-09-22 | 2024-10-20 |
| 2024 | preseason | 322 | 11 | 199 | 2024-05-03 | 2024-05-11 |
| 2024 | regular | 5,412 | 242 | 157 | 2024-05-14 | 2024-09-19 |
| 2025 | postseason | 568 | 24 | 99 | 2025-09-14 | 2025-10-10 |
| 2025 | preseason | 442 | 15 | 238 | 2025-05-02 | 2025-05-12 |
| 2025 | regular | 6,572 | 288 | 185 | 2025-05-16 | 2025-09-11 |
| 2026 | preseason | 173 | 6 | 173 | 2026-05-01 | 2026-05-03 |
| 2026 | regular | 4,888 | 203 | 227 | 2026-05-08 | 2026-07-22 |

### Preseason is present and unlabelled in production

937 player-game rows across 32 preseason games sit in the
cache, and all of them also appear in `wnba_player_games.csv` — which has no
`season_type` column, so the production trainer cannot exclude them. Preseason
rotations are not representative of regular-season roles. The lab excludes
preseason from feature history by default and records the exclusion.

## DNP summary

- **3,161 DNP rows** (16.7% of player-games)
- Coach's decision: **1,760** (55.7% of DNPs)
- Injury / rest / personal: **1,401** (44.3%)
- Distinct reason strings: **118**

DNP status and reason are recorded per game, so they are historically
authentic — but they are **postgame outcomes**, not pregame designations. They
can label an availability model's training target; they cannot serve as a
pregame availability feature.

## Data-quality findings

**Phantom listings (32 rows, 0.169%).** A player appears
on a box score with no stat line and no DNP flag. All occur around trades — a
traded player is left on her former team's roster listing. The clearest case is
Celeste Taylor on 2024-08-23, listed for both PHX (12 minutes, real) and CON
(no stat line) in two simultaneously tipping games. These rows are excluded
from feature history and covered by a regression test.

**Trades are common.** 122 of 727 player-seasons (16.8%) involve
more than one team. Name-based identity would corrupt those histories, which is
why every join in the lab uses ESPN numeric ids.

**Overtime is not adjusted for.** `pace` is the possession estimate for the game
as played; the observed range is 67.8–122.6
possessions. Overtime games sit at the top of that range and are left as-is
rather than normalized to 40 minutes, so the value stays a faithful description
of what happened.

## Schema

`data/normalized/player_games.parquet` — uniqueness `(player_id, game_id)`

```
identity   game_id, player_id, player_name, jersey, position
teams      team_id, team_abbrev, opponent_id, opponent_abbrev, home_away, is_home
time       start_utc (exact tip), slate_date_et (derived local date), tip_hour_et,
           season, season_type, completed
status     starter, active, played, did_not_play, dnp_reason, ejected
box score  minutes, points, rebounds, assists, threes_made, steals, blocks,
           turnovers, fga, fgm, fta, ftm, threes_attempted,
           offensive_rebounds, defensive_rebounds, fouls, plus_minus
context    team_score, opponent_score
```

`data/normalized/team_games.parquet` — uniqueness `(team_id, game_id)`; adds
team totals plus derived `possessions`, `game_possessions`, `pace`, `off_rating`,
`def_rating`, `net_rating`, `starters_flagged`.

`start_utc` and `slate_date_et` are stored separately and the production UTC
`game_date` is deliberately not reproduced.

## Reproducibility

```bash
python3 learning/analytics_lab/inventory/parse_espn_cache.py            # resumable
python3 learning/analytics_lab/inventory/parse_espn_cache.py --rebuild  # full reparse
```

Idempotent: a second run reports `newly parsed 0` and leaves the outputs
unchanged. Games already in the manifest are skipped, so an interrupted run
resumes where it stopped.

