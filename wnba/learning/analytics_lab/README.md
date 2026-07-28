# WNBA Analytics Lab

An isolated environment for reconstructing historical pregame state, replaying
slates chronologically, and grading experimental projections against the live
production approach — without touching production.

Modeled on the MLB Analytics Lab, adapted to the WNBA tree's actual layout.

---

## Isolation contract

These are enforced by `config/lab_config.py` and by `tests/test_lab_isolation.py`,
not merely promised.

**The lab does not:**

- write to any production path — `sports/wnba/data`, `models`, `outputs`,
  `Best_Bets`, `logs`, `wnba_v2/`, `edgeranked-sportsai/`, `EdgeRanked/site/`, `/srv`
- write to canonical or published artifacts (`projections.csv`,
  `wnba_best_bets_today.csv`, `Projections_app_view.csv`, the dated archives)
- replace, retrain, or overwrite a production model
- restart a service, edit a cron entry, or change an environment variable
- change anything on the website
- import a production pipeline module (`simulate_wnba_today`,
  `build_wnba_features_today`, `build_wnba_dataset`, `build_wnba_best_bets`,
  `fetch_wnba_data`, `wnba_model_config`, `wnba_model_utils`) — those perform
  directory creation, file writes and network fetches at import or call time
- fall back silently to current-season aggregates when point-in-time data is
  missing; a missing input raises

**The lab does:**

- read production and V2 artifacts, read-only
- write every artifact it generates under `analytics_lab/` and nowhere else
- route every write through `lab_config.assert_lab_path()`, which resolves the
  path first so `..` traversal and symlinks cannot escape
- keep backfills resumable and idempotent — rerunning a step reproduces the same
  output and never rewrites a frozen projection

Promotion is out of scope. The lab produces a recommendation; changing
production is a separate, human-approved action taken with production tooling.

---

## Layout

```
analytics_lab/
  config/lab_config.py        paths, write guards, replay conventions
  inventory/
    inventory_datasets.py     dataset profiler -> data/normalized/
    build_game_index.py       tip-off timestamps from the ESPN summary cache
    parse_espn_cache.py       canonical player_games / team_games from the cache
    report_history_completion.py
  leakage/audit_features.py   feature classification + empirical leak checks
  replay/
    build_history.py          Phase 1 path; superseded by parse_espn_cache.py
    asof_features.py          upcoming-game as-of feature reconstruction
    as_of_state.py            point-in-time state; future data is unreachable
    runner.py                 chronological replay loop + Projector interface
  experiments/
    production_adapter.py     lab features -> production model input names
    minutes_leakage.py        Phase 2C variants A-D
    rolling_staleness.py      Phase 2D fresh vs stale
    team_context_reconstruction.py
    archive_integrity.py      Phase 2F archive ledger
    manifest_schema.json
  grading/
    metrics.py                error, calibration, segment, top-N metrics
    grader.py                 join to actuals, score, compare candidate vs baseline
  promotion/                  promotion report template
  reports/                    audit output and grading reports
  data/                       raw / normalized / features / actuals / baselines
  tests/                      isolation, integrity, leak-safety, regressions
```

---

## Getting started

```bash
cd /home/ubuntu/EdgeRanked/sports/wnba
python3 learning/analytics_lab/inventory/inventory_datasets.py
python3 learning/analytics_lab/inventory/parse_espn_cache.py
python3 learning/analytics_lab/inventory/report_history_completion.py
python3 learning/analytics_lab/replay/asof_features.py
python3 learning/analytics_lab/leakage/audit_features.py
python3 learning/analytics_lab/experiments/minutes_leakage.py
python3 learning/analytics_lab/experiments/rolling_staleness.py
python3 learning/analytics_lab/experiments/team_context_reconstruction.py
python3 learning/analytics_lab/experiments/archive_integrity.py
python3 -m pytest learning/analytics_lab/tests -q -p no:cacheprovider
```

Every step is idempotent. `parse_espn_cache.py` is also resumable — it skips
games already in its manifest.

Read the reports before building an experiment:

| Report | What it settles |
|---|---|
| `initial_feasibility_report.md` | What can and cannot be reconstructed |
| `history_completion_report.md` | The canonical 2024–2026 history and its defects |
| `minutes_leakage_audit.md` | How much accuracy the actual-minutes feature invents |
| `rolling_staleness_audit.md` | What one-game-stale serving costs |
| `team_context_reconstruction.md` | The dead pace feed and its replacement |
| `archive_integrity_report.md` | Which archived boards are genuinely pregame |
| `phase2_baseline_verdict.md` | Which baseline to use, and for what |
| `proposed_production_changes.md` | Production repairs, queued for separate review |
| `phase3_framework.md` | How to write and run an experiment |
| `experiment_catalog.md` | Every registered research question and its result |
| `research_leaderboard.md` | Ranked results across experiments |
| `phase3_summary.md` | Phase 3 outcome |

---

## Running an experiment

```bash
cd /home/ubuntu/EdgeRanked/sports/wnba
python3 learning/analytics_lab/experiments/framework/runner.py --list
python3 learning/analytics_lab/experiments/framework/runner.py EXP001
python3 learning/analytics_lab/experiments/framework/runner.py          # all
python3 learning/analytics_lab/experiments/framework/leaderboard.py
```

Adding a research question means adding one file under `experiments/catalog/`
that exposes a module-level `EXPERIMENT`. The runner discovers it; it imports no
experiment by name. See `reports/phase3_framework.md` for the contract.

The lab answers research questions. It cannot promote anything — there is no code
path from an experiment to a production artifact, and a test asserts that nothing
under `experiments/` calls `joblib.dump` or `.fit(`.

---

## Four conventions that are easy to get wrong

**1. `game_date` is a UTC date, not the slate date.** Verified: production
`game_date` matches the UTC date on 100% of rows and differs from the
America/New_York slate date on 46.6%. Every evening tip-off is filed under the
following day, and a day mixing an afternoon and an evening game puts two
different ET slates on one key. The lab keys all chronology off `start_utc` from
`data/normalized/game_index.csv`.

**2. The *published board* uses the ET slate date, not the UTC date.** Production
runs both conventions at once: `wnba_player_games.game_date` is the UTC date, but
the archived board's `GAME_DATE` is the ET slate date. Joining the two on a date
column silently mismatches every evening game. Join on ids and tip-off times.

**3. Production pregame features are one game stale.** `build_wnba_features_today.py`
serves each player's most recent *dataset row*, whose rolling columns were built
with `shift(1)` — so they exclude that very game. Verified: the served
`minutes_rolling_mean_3` matches the one-game-stale window on 100% of rows and
the up-to-date window on 5.8%. `AsOfState.rolling_mean()` and
`replay/asof_features.py` deliberately do not reproduce this; use
`experiments/rolling_staleness.build_stale_features()` to imitate production.

**4. A prior game counts only once it has *finished*.** `asof_features.py` uses
`end_utc <= target start_utc`, with `end_utc = tip + 2.25h`. Tip-off order alone
would let a 19:00 game that is still being played leak into a 20:00 game. The
equivalence to `shift(1)` is asserted at build time, not assumed.
