# Phase 2F — Archive pregame integrity

**Date:** 2026-07-25  |  **Artifacts inventoried:** 69

## Method

Boards carry **no internal generation timestamp** — the only non-projection
column is `SIM_RUNS`. File mtime is the creation proxy.
`simulate_wnba_today.py` rewrites the dated file on every pipeline run, so
mtime is the last run of that day, which is the freeze instant for the
archived content. mtime is filesystem metadata and would not survive a copy
or restore; that caveat applies to every row below.

A game counts as tipped when `start_utc < creation`, and as completed when
`start_utc + 2.25h < creation`.

## Classification counts

| Classification | Artifacts | Share |
|---|---|---|
| `CLEAN_PREGAME` | 47 | 68.1% |
| `PARTIAL_POST_TIP` | 17 | 24.6% |
| `SLATE_MISMATCH` | 2 | 2.9% |
| `POSTGAME_REBUILD` | 2 | 2.9% |
| `INVALID` | 1 | 1.4% |

**Only `CLEAN_PREGAME` artifacts may be used as exact historical production
snapshots.**

## Usable exact-snapshot range

- **47 clean slates**, 2026-05-08 → 2026-07-20
- **2,460 projection rows**
- covering **137 games**

## Per-artifact ledger

| Artifact | rows | games | created (UTC) | earliest tip | tipped before creation | class |
|---|---|---|---|---|---|---|
| `wnba_projections_20250705.csv` | 20 | 2.0 | 2026-04-26 15:57 | 2025-07-05 23:00 | 2/2 | `SLATE_MISMATCH` |
| `wnba_projections_20260331.csv` | 20 |  | 2026-04-17 18:04 | nan |  | `INVALID` |
| `wnba_projections_20260426.csv` | 20 | 2.0 | 2026-04-26 15:32 | 2025-07-05 23:00 | 2/2 | `SLATE_MISMATCH` |
| `wnba_projections_20260508.csv` | 27 | 3.0 | 2026-05-08 19:29 | 2026-05-08 23:30 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260509.csv` | 29 | 4.0 | 2026-05-09 14:31 | 2026-05-09 17:00 | 0/4 | `CLEAN_PREGAME` |
| `wnba_projections_20260510.csv` | 33 | 4.0 | 2026-05-10 12:16 | 2026-05-10 17:00 | 0/4 | `CLEAN_PREGAME` |
| `wnba_projections_20260512.csv` | 27 | 3.0 | 2026-05-12 22:32 | 2026-05-13 00:00 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260513.csv` | 30 | 4.0 | 2026-05-13 22:32 | 2026-05-13 23:00 | 0/4 | `CLEAN_PREGAME` |
| `wnba_projections_20260514.csv` | 16 | 2.0 | 2026-05-14 22:32 | 2026-05-15 00:00 | 0/2 | `CLEAN_PREGAME` |
| `wnba_projections_20260515.csv` | 32 | 4.0 | 2026-05-15 22:32 | 2026-05-15 23:30 | 0/4 | `CLEAN_PREGAME` |
| `wnba_projections_20260517.csv` | 35 | 4.0 | 2026-05-17 11:32 | 2026-05-17 17:30 | 0/4 | `CLEAN_PREGAME` |
| `wnba_projections_20260518.csv` | 17 | 2.0 | 2026-05-18 22:32 | 2026-05-19 00:00 | 0/2 | `CLEAN_PREGAME` |
| `wnba_projections_20260519.csv` | 7 | 1.0 | 2026-05-19 22:32 | 2026-05-20 02:00 | 0/1 | `CLEAN_PREGAME` |
| `wnba_projections_20260520.csv` | 22 | 3.0 | 2026-05-20 22:32 | 2026-05-20 23:00 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260521.csv` | 25 | 3.0 | 2026-05-21 22:32 | 2026-05-22 00:00 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260522.csv` | 25 | 3.0 | 2026-05-22 22:32 | 2026-05-22 23:30 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260523.csv` | 37 | 3.0 | 2026-05-24 00:19 | 2026-05-23 17:00 | 3/3 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260524.csv` | 34 | 3.0 | 2026-05-24 22:32 | 2026-05-24 19:00 | 3/3 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260525.csv` | 12 | 2.0 | 2026-05-25 22:32 | 2026-05-26 00:00 | 0/2 | `CLEAN_PREGAME` |
| `wnba_projections_20260527.csv` | 33 | 5.0 | 2026-05-27 22:32 | 2026-05-27 23:00 | 0/5 | `CLEAN_PREGAME` |
| `wnba_projections_20260528.csv` | 18 | 2.0 | 2026-05-28 22:32 | 2026-05-29 00:00 | 0/2 | `CLEAN_PREGAME` |
| `wnba_projections_20260529.csv` | 28 | 4.0 | 2026-05-29 22:32 | 2026-05-29 23:30 | 0/4 | `CLEAN_PREGAME` |
| `wnba_projections_20260530.csv` | 18 | 3.0 | 2026-05-30 11:32 | 2026-05-30 17:00 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260531.csv` | 13 | 1.0 | 2026-05-31 22:32 | 2026-05-31 19:30 | 1/1 | `POSTGAME_REBUILD` |
| `wnba_projections_20260601.csv` | 18 | 2.0 | 2026-06-01 22:32 | 2026-06-02 00:00 | 0/2 | `CLEAN_PREGAME` |
| `wnba_projections_20260602.csv` | 37 | 4.0 | 2026-06-02 22:32 | 2026-06-02 23:30 | 0/4 | `CLEAN_PREGAME` |
| `wnba_projections_20260603.csv` | 16 | 2.0 | 2026-06-03 22:32 | 2026-06-03 23:30 | 0/2 | `CLEAN_PREGAME` |
| `wnba_projections_20260604.csv` | 19 | 2.0 | 2026-06-04 22:32 | 2026-06-04 23:00 | 0/2 | `CLEAN_PREGAME` |
| `wnba_projections_20260606.csv` | 52 | 4.0 | 2026-06-06 23:19 | 2026-06-06 17:00 | 3/4 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260607.csv` | 57 | 2.0 | 2026-06-07 22:32 | 2026-06-07 19:00 | 1/2 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260608.csv` | 88 | 3.0 | 2026-06-08 22:32 | 2026-06-08 23:00 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260609.csv` | 85 | 3.0 | 2026-06-09 22:32 | 2026-06-09 23:00 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260610.csv` | 58 | 2.0 | 2026-06-10 22:32 | 2026-06-10 23:00 | 0/2 | `CLEAN_PREGAME` |
| `wnba_projections_20260611.csv` | 114 | 4.0 | 2026-06-11 22:32 | 2026-06-11 23:00 | 0/4 | `CLEAN_PREGAME` |
| `wnba_projections_20260612.csv` | 59 | 2.0 | 2026-06-12 22:32 | 2026-06-12 23:30 | 0/2 | `CLEAN_PREGAME` |
| `wnba_projections_20260613.csv` | 114 | 4.0 | 2026-06-13 22:32 | 2026-06-13 22:00 | 1/4 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260614.csv` | 56 | 2.0 | 2026-06-14 22:32 | 2026-06-14 19:00 | 2/2 | `POSTGAME_REBUILD` |
| `wnba_projections_20260615.csv` | 87 | 3.0 | 2026-06-15 22:32 | 2026-06-16 00:00 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260616.csv` | 29 | 1.0 | 2026-06-16 22:32 | 2026-06-16 23:00 | 0/1 | `CLEAN_PREGAME` |
| `wnba_projections_20260617.csv` | 175 | 6.0 | 2026-06-17 22:32 | 2026-06-17 23:00 | 0/6 | `CLEAN_PREGAME` |
| `wnba_projections_20260618.csv` | 27 | 1.0 | 2026-06-18 22:32 | 2026-06-18 23:30 | 0/1 | `CLEAN_PREGAME` |
| `wnba_projections_20260619.csv` | 90 | 3.0 | 2026-06-19 22:32 | 2026-06-19 23:30 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260620.csv` | 84 | 3.0 | 2026-06-20 22:32 | 2026-06-20 17:00 | 2/3 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260621.csv` | 85 | 3.0 | 2026-06-21 22:32 | 2026-06-21 20:00 | 2/3 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260622.csv` | 112 | 4.0 | 2026-06-22 22:32 | 2026-06-22 23:00 | 0/4 | `CLEAN_PREGAME` |
| `wnba_projections_20260623.csv` | 26 | 1.0 | 2026-06-23 22:32 | 2026-06-24 02:00 | 0/1 | `CLEAN_PREGAME` |
| `wnba_projections_20260624.csv` | 113 | 4.0 | 2026-06-24 22:32 | 2026-06-24 23:30 | 0/4 | `CLEAN_PREGAME` |
| `wnba_projections_20260625.csv` | 84 | 3.0 | 2026-06-25 22:32 | 2026-06-25 23:00 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260626.csv` | 85 | 3.0 | 2026-06-26 22:32 | 2026-06-26 23:30 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260627.csv` | 84 | 3.0 | 2026-06-27 22:32 | 2026-06-27 18:00 | 1/3 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260628.csv` | 111 | 4.0 | 2026-06-28 22:32 | 2026-06-28 18:00 | 3/4 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260630.csv` | 26 | 1.0 | 2026-07-01 00:35 | 2026-06-30 23:00 | 1/1 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260705.csv` | 43 | 2.0 | 2026-07-05 22:30 | 2026-07-05 19:00 | 1/2 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260706.csv` | 76 | 3.0 | 2026-07-06 22:30 | 2026-07-06 23:30 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260707.csv` | 50 | 2.0 | 2026-07-07 22:30 | 2026-07-08 00:00 | 0/2 | `CLEAN_PREGAME` |
| `wnba_projections_20260708.csv` | 73 | 3.0 | 2026-07-08 22:31 | 2026-07-08 23:00 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260709.csv` | 67 | 3.0 | 2026-07-09 22:30 | 2026-07-10 00:00 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260710.csv` | 71 | 3.0 | 2026-07-10 22:30 | 2026-07-10 23:30 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260711.csv` | 66 | 3.0 | 2026-07-11 22:30 | 2026-07-11 17:00 | 3/3 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260712.csv` | 95 | 4.0 | 2026-07-12 22:31 | 2026-07-12 19:00 | 2/4 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260713.csv` | 49 | 2.0 | 2026-07-13 22:30 | 2026-07-13 23:00 | 0/2 | `CLEAN_PREGAME` |
| `wnba_projections_20260714.csv` | 47 | 2.0 | 2026-07-14 22:31 | 2026-07-14 15:00 | 1/2 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260715.csv` | 71 | 3.0 | 2026-07-15 22:31 | 2026-07-15 16:00 | 2/3 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260716.csv` | 50 | 1.0 | 2026-07-16 22:31 | 2026-07-16 23:00 | 0/1 | `CLEAN_PREGAME` |
| `wnba_projections_20260717.csv` | 99 | 4.0 | 2026-07-17 22:31 | 2026-07-17 23:30 | 0/4 | `CLEAN_PREGAME` |
| `wnba_projections_20260718.csv` | 73 | 3.0 | 2026-07-18 22:31 | 2026-07-19 00:00 | 0/3 | `CLEAN_PREGAME` |
| `wnba_projections_20260719.csv` | 70 | 3.0 | 2026-07-19 22:31 | 2026-07-19 17:00 | 2/3 | `PARTIAL_POST_TIP` |
| `wnba_projections_20260720.csv` | 96 | 4.0 | 2026-07-20 22:31 | 2026-07-21 00:00 | 0/4 | `CLEAN_PREGAME` |
| `wnba_projections_20260722.csv` | 146 | 6.0 | 2026-07-22 22:31 | 2026-07-22 19:00 | 2/6 | `PARTIAL_POST_TIP` |

## Why the partial artifacts are contaminated

17 artifacts were written after at least one game tipped. Across
them, 33 of 53 games (62.3%) had already
started. Because the pipeline refetches actuals at the start of every run and
then serves each player's latest stored row, projections for the *remaining*
games on such a board can incorporate results from the games that already
finished. Those rows are not pregame and must not be graded as if they were.

## Valid and invalid uses

| Use | Verdict |
|---|---|
| Exact historical production snapshot, `CLEAN_PREGAME` rows only | **Valid** |
| Exact snapshot using all archived rows | **Invalid** — mixes in post-tip rebuilds |
| Measuring production *projection* accuracy over the clean slates | **Valid** |
| Claiming this represents the historical model *version* | **Invalid** — binaries are overwritten in place, unversioned |
| Extending the baseline before the first archived date | **Invalid** — no artifact exists |

