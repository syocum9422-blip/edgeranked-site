# Phase 2E — Team-context reconstruction

**Date:** 2026-07-25

## The production outage

`wnba_team_context.csv` holds 1,698 team-game rows. `pace` / `off_rating` / `def_rating` are present on 1,422 (83.7%).

- **Last healthy game date:** 2026-06-28
- **Rows after that date with no pace at all:** 118

Monthly coverage:

| Month | team-game rows | share with pace |
|---|---|---|
| 2024-10 | 24 | 100.0% |
| 2025-05 | 108 | 100.0% |
| 2025-06 | 138 | 100.0% |
| 2025-07 | 134 | 100.0% |
| 2025-08 | 164 | 100.0% |
| 2025-09 | 100 | 100.0% |
| 2025-10 | 10 | 100.0% |
| 2026-05 | 138 | 100.0% |
| 2026-06 | 240 | 33.3% |
| 2026-07 | 116 | 0.0% |

## Reconstruction

Rebuilt from cached ESPN box scores, independent of the production feed:

```
possessions = FGA - OREB + TOV + 0.44 * FTA        (per team)
game_possessions = mean of the two teams' estimates  (shared, keeps a game consistent)
off_rating = 100 * team_points     / game_possessions
def_rating = 100 * opponent_points / game_possessions
pace       = game_possessions                       (40-minute regulation game)
```

- **Team-game rows reconstructed:** 1,558
- **Span:** 2024-05-14 → 2026-07-22
- **Coverage of pace/off/def:** 100.0% / 100.0% / 100.0%
- **Season openers (no prior form):** 19 — flagged, never back-filled with a league average
- **Low-sample rows (< 3 prior games):** 49

Rolling forms use `shift(1)`, so no target-game total enters its own feature.
Teams are matched by ESPN `team_id`; the opponent is the other competitor on
the same `game_id`.

## Agreement with production over the healthy period

| Metric | n | correlation | lab mean | production mean | mean diff | mean abs diff | p90 abs diff |
|---|---|---|---|---|---|---|---|
| pace | 873 | 0.9888 | 81.87 | 80.86 | +1.016 | 1.016 | 2.000 |
| off_rating | 873 | 0.9861 | 100.45 | 101.74 | -1.287 | 2.004 | 4.129 |
| def_rating | 873 | 0.9868 | 101.00 | 102.33 | -1.327 | 2.021 | 4.127 |

## Rows affected by the outage

- Live board (146 rows): **25.3%** have a null `pace_last_10` / `off_rating_last_10` / `def_rating_last_10` and are median-imputed by the model pipeline's `SimpleImputer`.
- Archived boards: **18 of 69** dated after the outage, covering **1,268 of 3,811** rows (**33.3%**).

## Verdict

The reconstruction is a valid drop-in for lab work across the full
2024–2026 span and needs no external data. Its scale differs slightly from
the production feed (see the table above), so lab results are not directly
comparable to production numbers computed before the outage — an experiment
should use one source throughout, and say which.

No production file was written. The proposed production repair is recorded
in `reports/proposed_production_changes.md` for separate review.

