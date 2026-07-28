# WNBA Analytics Lab — Initial Feasibility Report

**Date:** 2026-07-25
**Scope:** repository/data inventory, historical backfill feasibility, leak-safe replay
architecture, baseline reconstruction planning, isolated lab scaffolding.
**Production changes made:** none. Verified byte-for-byte at the end of this document.

---

## 1. Executive summary

The WNBA repository contains **enough historical information to build a genuine
analytics lab**, and considerably more than the production pipeline currently
uses. The decisive asset is not the production data directory — it is the
811-file cache of raw ESPN game summaries under `wnba_v2/data/team_games/_cache/`,
which supplies exact tip-off timestamps, per-game starting lineups, DNP reasons,
per-game positions and closing odds for **every game from 2024-05-03 to
2026-07-22**.

Three findings dominate everything else.

**1. The production stat models are trained on a feature they cannot have at
prediction time.** `minutes` is in `feature_columns()`. In training it is the
target game's *actual* minutes. At serving time the same column holds the
player's *previous game's* actual minutes, because `build_wnba_features_today.py`
serves each player's last completed dataset row and never writes the minutes
model's own `projected_minutes` back into the feature frame. Verified: 100% of
served rows carry the previous game's actual minutes in the `minutes` slot;
`corr(minutes, points) = 0.780` versus `0.624` for the rolling form. Consequence:
the reported validation MAE (points 3.25) is optimistic and is **not** an estimate
of deployed error, and the models are being served a feature whose meaning
differs from the one they learned. This is the single highest-value thing a lab
can measure and fix.

**2. Production pregame features are systematically one game stale.** Serving
rows come from the player's most recent dataset row, whose rolling columns were
computed with `shift(1)` — so they exclude that very game. Verified on the live
2026-07-22 board: served `minutes_rolling_mean_3` matches the one-game-stale
window on 100% of rows and the up-to-date window on 5.8%. A worked example:
A'ja Wilson's board value was 28.67 (mean of the three games *before* 07-20)
rather than 28.0 (mean of her last three including 07-20). This is not a leak —
it is conservative — but it discards the most recent observation on every player,
every slate.

**3. `game_date` is a UTC date, not the slate date.** Verified across 16,345
joined rows: `game_date` differs from the America/New_York slate date on 46.63%
of rows and from the UTC date on 0.00%. Every evening tip is filed under the
following day. On days mixing an afternoon and an evening game this collapses two
different ET slates onto one key, which is the mechanism behind the 126 duplicate
`(player_key, game_date)` rows on 7 dates. Any replay ordered by `game_date`
inherits this. The lab keys chronology off tip-off timestamps instead.

Two live production defects surfaced in passing and are worth separate attention:

- **`wnba_team_context.csv` has had no `pace` / `off_rating` / `def_rating` since
  2026-06-28** (0 of 118 rows; 33% coverage in June). Those feed three production
  model features. On the live 2026-07-22 board, 25.3% of rows have NaN
  `pace_last_10` / `off_rating_last_10` / `def_rating_last_10` and are
  median-imputed. `wnba_v2/data/team_games/team_game_logs.csv` has real
  possessions and ratings through 2026-07-23, so the repair source already exists
  in-repo.
- **The dated projection archive is not a clean pregame snapshot for ~23% of
  games.** It is written by the 22:30 UTC (18:30 ET) run, and 23.2% of the 185
  games inside the archive window tip before that. For those games the archived
  board is a post-game rebuild.

**Overall verdict: READY_WITH_RECONSTRUCTION.** Full-fidelity leak-safe replay
of the **2024, 2025 and 2026 seasons** is achievable from local data with no
network access. The one capability that is genuinely blocked is historical
pregame *injury/availability*, which no data source in this repository retains
for 2024–2025.

---

## 2. Existing WNBA architecture

**Model root:** `/home/ubuntu/EdgeRanked/sports/wnba`
(edit here; `/home/ubuntu/edgeranked-sportsai/` is the Render deploy copy that
cron overwrites).

**Entry point:** `run_wnba_model.py` → `wnba_model/pipeline/service.py::main()`.
Settings live in `wnba_model/settings.py`, re-exported through
`wnba_model_config.py`.

**Cron** (UTC): full rebuild 11:30, refreshes 18:00 and 22:30, late board
refreshes 23:15 and 00:45, grading/canaries 04:10–04:40.
Runner: `site/scripts/aws/run_wnba_day.sh`.

### Stage map

| Stage | File | Key functions |
|---|---|---|
| **raw data** | `fetch_wnba_data.py` | ESPN endpoints → `data/raw/wnba_player_games_raw.csv`, `wnba_team_context_raw.csv`, `wnba_schedule_today_raw.csv`, `wnba_player_status_raw.csv` |
| | `auto_backfill_wnba_live_players.py` | fills lined players missing history |
| | `fetch_wnba_lines.py` | PrizePicks props → `wnba_sportsbook_lines.csv`, `data/raw/line_snapshots/` |
| **normalization** | `wnba_model_utils.py` | `normalize_player_games`, `normalize_team_context`, `normalize_schedule`, `normalize_positions`, `normalize_player_status`, `canonicalize_name`, `standardize_team_abbrev`, `load_inputs_for_pipeline` |
| | `wnba_model/pipeline/service.py` | `validate_current_file`, `validate_slate_against_trusted_source`, `refresh_last_good_snapshot`, `restore_last_good_snapshot` |
| **feature generation** | `build_wnba_dataset.py` | `add_schedule_features`, `add_usage_features`, `add_player_trend_features`, `enrich_with_team_context`, `build_team_game_aggregates`, `build_opponent_allowance` → `data/processed/wnba_training_dataset.csv` |
| | `wnba_model_utils.py` | `add_group_rolling_features` (all `shift(1)`), `feature_columns()` (84 features) |
| | `build_wnba_features_today.py` | `latest_player_rows`, `latest_team_snapshot`, `latest_opponent_snapshot`, `latest_position_snapshot`, `apply_status_filter`, `apply_recency_filter` → `wnba_today_features.csv` |
| **training** | `train_wnba_models.py` | `train_ensemble_models` (ridge + tree, chronological 0.8-quantile split) → `data/models/wnba_{stat}_model.joblib` |
| | `train_wnba_minutes_model.py` | → `models/wnba_minutes_model.joblib` |
| **model inference** | `simulate_wnba_today.py` | `build_projection_rows`, `simulate_player_row`, `apply_absence_redistribution`, `apply_phase13_combo_hybrid_minutes`, `compute_minutes_distribution` |
| **projection output** | `simulate_wnba_today.py:1263` | `projections.csv`, `Projections_app_view.csv`, **and `archive_dataframe(...)` → `outputs/archive/projections/wnba_projections_YYYYMMDD.csv`** |
| | `build_wnba_best_bets.py` | `wnba_best_bets_today.csv` + dated best-bets archive |
| **publication** | `site/scripts/publish_render_snapshot.py`, `publish_render_site.sh` | gated by `require_publish_safety_check()` |
| **grading/validation** | `fill_wnba_actuals.py`, `grade_wnba_best_bets.py`, `track_wnba_results.py`, `calibrate_wnba_model.py`, `update_wnba_learning_outputs.py` | → `learning/graded_predictions_ledger.csv`, `learning/errors/*` |
| | `projection_accuracy/grade_projection_accuracy.py` | **already grades archived boards vs box scores** — read-only, reusable |
| | `wnba_v2/` | parallel engine rebuild with its own walk-forward evaluation, market/ROI-oriented |

**Existing shadow/canary machinery** (all shadow-only, already wired to cron):
`wnba_selective_feature_canary.py`, `wnba_combo_hybrid_minutes_canary.py`,
`wnba_learning_audit.py`, `accuracy_recovery/`, `wnba_v2/tracker/`.
The lab complements these: they are market/selection-oriented, the lab is
projection-accuracy-oriented.

---

## 3. Historical data inventory

Generated by `inventory/inventory_datasets.py`; full detail in
`data/normalized/dataset_inventory.{csv,json}` and `dataset_schema.csv`.

| Dataset | Rows | Grain | Timing | Span | Notes |
|---|---|---|---|---|---|
| `data/raw/wnba_player_games.csv` | 19,769 | player-game | postgame | 2023-06-03 → 2026-07-22 | Canonical actuals. `game_id`/`starter`/`played`/`position` null on 17.3% overall and **56% of 2026**. 2023 is 34 junk rows. |
| `data/raw/wnba_team_context.csv` | 1,698 | team-game | postgame | 2024-05-04 → 2026-07-22 | **`pace`/`off_rating`/`def_rating` dead since 2026-06-28.** 6 duplicate `(team, game_date)` rows. |
| `data/raw/wnba_player_status.csv` | 42 | snapshot | pregame | current only | Overwritten every run. **No history retained.** |
| `data/raw/wnba_player_positions.csv` | 20 | snapshot | reference | undated | Manually maintained; merged onto all history. |
| `data/raw/wnba_sportsbook_lines.csv` | 51 | snapshot | pregame | current only | Overwritten every run. |
| `data/raw/line_snapshots/` | 38 files | snapshot | pregame | 2026-06-11 → 2026-07-22 | Intraday line movement. |
| `data/processed/wnba_training_dataset.csv` | 19,769 × 137 | player-game | mixed | 2023-06-03 → 2026-07-22 | Rebuilt daily. Rolling cols `shift(1)`; `minutes` and targets are same-game actuals. |
| `data/processed/wnba_today_features.csv` | 146 × 145 | slate | pregame | current slate | Carries each player's last completed game row. |
| `outputs/archive/projections/` | **68 slates**, 3,811 rows × 119 cols | projection | pregame* | 2026-05-08 → 2026-07-22 | Frozen full-slate boards. *23.2% of window games tip before the freeze. |
| `outputs/archive/best_bets/` | 71 files | projection | pregame | 2026-03-31 → 2026-07-22 | Lined picks only. |
| `learning/graded_predictions_ledger.csv` | 2,689 | projection | mixed | 2025-07-05 → 2026-07-22 | 67 dates, all with actuals. **`usage`, `pace`, `rest_days` are 100% null; `injury_flags` 96.6% null; `model_version` constant.** |
| **`wnba_v2/data/team_games/_cache/*.json`** | **811 games** | game | mixed | 2024-05-03 → 2026-07-22 | **The key asset.** Start times, starters, DNP+reason, positions, injuries block, odds, play-by-play. |
| `wnba_v2/data/team_games/player_boxscores.csv` | 17,360 | player-game | postgame | 2024-05-03 → 2026-06-28 | Has `starter`/`played`/`position` at 100%. Stale after 06-28. |
| `wnba_v2/data/team_games/team_game_logs.csv` | 1,622 | team-game | postgame | 2024-05-04 → 2026-07-23 | Real `possessions`, `pace_proxy`, off/def/net rating. **Fresh.** |
| `wnba_v2/data/line_history/prop_open_close.csv` | 10,240 | prop | pregame | 2026-06-12 → 2026-07-23 | Open/close per prop. `date` column is a malformed integer date. 349 duplicate keys. |
| `wnba_v2/data/line_history/game_open_close.csv` | 67 | team-game | pregame | 2026-06-30 → 2026-07-30 | Spread/total open and close. |

### Availability by category

**Already present.** Minutes, points, rebounds, assists, threes, steals, blocks,
turnovers, FGA/FGM, FTA/FTM, offensive/defensive rebounds, plus-minus, starter
flag, played flag, DNP reason, per-game position, game date, opponent, home/away,
team and opponent scores, real possessions and pace, off/def/net rating,
tip-off timestamps, closing odds (2026), prop open/close (2026-06-12 onward).

**Derivable from existing files.** Rest days and back-to-backs (from tip-off
timestamps), schedule density, usage proxies, rotation share and rank, opponent
positional allowance (using per-game positions rather than the current roster
file), team form, minutes-adjusted rates, roster membership as of any date
(any player appearing in a team's box score, played or not).

**Externally backfillable if wanted.** Pregame injury reports for 2024–2025,
starting-lineup *announcements* (as opposed to realized lineups), travel
distance, betting lines before 2026-06-12, player biographical data.
None are required for the first phase of lab work.

**Cannot be reconstructed reliably.** Historical *pregame* injury designations
and expected-minutes estimates for 2024–2025; what the production pipeline
*would* have projected on a date with no archived board; the exact production
model binary as of any past date (models are overwritten in place — current
mtime 2026-07-25 11:31, no versioning).

---

## 4. Date ranges and sample sizes

Normalized by `replay/build_history.py`, indexed on true tip-off timestamps.

| Season | Player-games | Games | Players | Span (ET slate dates) |
|---|---|---|---|---|
| 2024 | 6,214 | 274 | 197 | 2024-05-03 → 2024-10-20 |
| 2025 | 7,510 | 326 | 231 | 2025-05-02 → 2025-10-10 |
| 2026 | 3,636 | 150 | 246 | 2026-05-01 → 2026-06-28 |
| **Total** | **17,360** | **750** | — | **2024-05-03 → 2026-06-28** |

Integrity of the normalized history: **0 rows dropped** for want of an indexed
game, **0 duplicate `(player_key, game_id)` keys**, `starter` / `played` /
`position` non-null at **100%**, tip-off timestamp known at **100%**.

The game index itself covers **811 games through 2026-07-22** — 59 more 2026
games than the V2 box-score table, because that table was last built on 2026-07-01.
Closing that gap is a local reparse of the cache, described in §12.

Coverage of pregame extras by season:

| Season | Games | Closing odds present | ≥1 injury entry dated before tip |
|---|---|---|---|
| 2024 | 275 | 0.0% | 0.0% |
| 2025 | 327 | 0.0% | 0.0% |
| 2026 | 209 | 99.5% | 64.1% |

---

## 5. Feature-by-feature leakage audit

Produced by `leakage/audit_features.py`; per-feature rows in
`reports/leakage_audit.csv`, evidence in `reports/leakage_checks.csv`.

Across the 84 columns in production `feature_columns()`:

| Classification | Count |
|---|---|
| Safe to reconstruct | 77 |
| Safe only with a date-aware transform | 2 |
| Requires a historical snapshot | 4 |
| Cannot be reconstructed | 1 |
| Unknown | 0 |

### Flagged features

| Feature | Class | Finding |
|---|---|---|
| `minutes` | **cannot_reconstruct** | Training value is the target game's actual minutes; serving value is the previous game's actual minutes. Not reconstructible as-is — must be redefined as a projection. |
| `pace_last_10` | requires_snapshot | Source column dead since 2026-06-28. Rebuild from `team_game_logs.possessions`. |
| `off_rating_last_10` | requires_snapshot | Same. |
| `def_rating_last_10` | requires_snapshot | Same. |
| `position` | requires_snapshot | Merged from the current 20-row roster file onto every historical row. Replace with the per-game ESPN position. |
| `rest_days`, `is_back_to_back` | date_aware | Correct only off true tip-off times; the UTC `game_date` shifts evening games by a day. |
| `pos_*_allowed_last_10` | date_aware | Rolling logic is safe, but the grouping position label is the anachronistic one above. |

### Empirical checks — all seven confirmed against live artifacts

| Check | Result | Evidence |
|---|---|---|
| Rolling features exclude the target game | **CONFIRMED SAFE** | `points_rolling_mean_3` matches the `shift(1)` form on 100.0% of rows, the target-inclusive form on 20.2% |
| `minutes` feature is the target game's actual | **CONFIRMED LEAK** | corr with points 0.780 vs 0.624 for the rolling form |
| Served `minutes` is the previous game's actual | **CONFIRMED MISMATCH** | 100.0% of 122 served rows |
| Served rolling features are one game stale | **CONFIRMED** | matches stale window 100.0%, fresh window 5.8% (n=137) |
| `position` is a current-roster snapshot | **CONFIRMED ANACHRONISM** | 20-row undated file merged onto all history |
| `game_date` follows UTC, not ET | **CONFIRMED** | 46.63% ET mismatch, 0.00% UTC mismatch across 16,345 rows |
| Archived boards frozen before tip-off | **CONFIRMED RISK** | 23.2% of 185 in-window games tip before the 18:30 ET freeze |

### Leakage patterns checked for and **not** found

- Full-season averages applied to earlier games — no. `season_avg_*` uses
  `shift(1).expanding().mean()` within `(player_key, season)`.
- Rolling statistics without a shift — no. Every rolling/EWM path goes through
  `add_group_rolling_features`, which shifts.
- Random train/test splitting — no. `train_ensemble_models` splits on the 0.8
  quantile of `game_date`, so a given game falls entirely on one side.
- Same-game teammates split across folds — no, by the same mechanism.
- Season totals including the predicted game — no.

The production feature *engineering* is, apart from `minutes`, notably
leak-clean. The problems are elsewhere: a target-derived feature, stale serving
state, anachronistic reference data, and a date convention.

---

## 6. Backfill feasibility matrix

| Capability | Verdict | Evidence |
|---|---|---|
| Historical actuals grading | **READY** | 17,360 indexed player-games, 0 dup keys, 100% timestamped. `projection_accuracy/grade_projection_accuracy.py` already does this against archived boards. |
| Player rolling-form reconstruction | **READY** | Full box-score history per player-game; `AsOfState.rolling_mean()` computes any window from completed games only. |
| Team-form reconstruction | **READY_WITH_RECONSTRUCTION** | Must use `wnba_v2` `team_game_logs` (real possessions, fresh to 2026-07-23), not `wnba_team_context.csv`, which is dead after 2026-06-28. |
| Opponent matchup reconstruction | **READY_WITH_RECONSTRUCTION** | Opponent allowance is derivable; positional allowance requires swapping in per-game ESPN positions for the current-roster label. |
| Rest / schedule-context reconstruction | **READY** | Exact tip-off timestamps for 100% of 811 games make rest, back-to-backs and schedule density exact rather than date-approximated. |
| Minutes reconstruction (as a projection) | **READY_WITH_RECONSTRUCTION** | All inputs exist. The production minutes model must be rebuilt as-of, and the stat models retrained to consume *projected* minutes — the current train/serve mismatch cannot simply be replayed. |
| Injury / availability reconstruction | **BLOCKED for 2024–2025, PARTIAL for 2026** | `wnba_player_status.csv` keeps no history. The ESPN summary `injuries` block reflects scrape time: 0.0% of 2024 and 2025 games have an injury entry dated before tip; 64.1% of 2026 games have at least one. Postgame `didNotPlay` + `reason` is complete (16.0% of athlete-rows, with specific reasons) but is an outcome, not a pregame signal. |
| Starting-lineup reconstruction | **READY (realized), BLOCKED (announced)** | Exactly 10 starters flagged in 100% of 811 games. These are realized lineups; pregame *announcements* were never captured. |
| Historical production baseline | **PARTIAL** | See §10. |
| Experimental-model training | **READY** | 17,360 rows, 750 games, 3 seasons, chronologically ordered. |
| Walk-forward validation | **READY** | Tip-off ordering supports per-game checkpoints; `wnba_v2` already runs walk-forward folds on the same data. |
| Calibration analysis | **READY** for point projections; **PARTIAL** for probabilities | Point calibration by projection bucket is fully supported. Probabilistic calibration needs simulator over/under probabilities, which are archived only for 2026-05-08 onward. |
| Top-ranked projection analysis | **READY** | Top-N metrics implemented in `grading/metrics.py`. |
| Full slate replay | **READY_WITH_RECONSTRUCTION** | Everything works except who was expected to play. Replay must adopt an explicit availability convention (§9). |

---

## 7. Missing-data risks

| Risk | Severity | Detail | Mitigation |
|---|---|---|---|
| No historical injury feed | **High** | Blocks faithful pregame availability for 2024–2025 | Adopt an explicit, documented availability convention; never present a replay as if availability were known |
| Team-context pace dead since 2026-06-28 | **High** (production) | 3 model features NaN on 25.3% of the live board | Use `team_game_logs` in the lab; flag the production repair separately |
| V2 box scores stale after 2026-06-28 | Medium | 59 games of 2026 missing `starter`/`played`/`position` | Local reparse of the cache — no network |
| Production `game_id` null on 56% of 2026 rows | Medium | Those rows cannot be joined to the game index | Use V2 box scores as the primary player-game source |
| Archived boards contaminated for early tips | Medium | 23.2% of in-window games | Filter the baseline to games tipping after 18:30 ET |
| 126 duplicate `(player_key, game_date)` rows on 7 dates | Low | UTC/ET boundary artifact, 0.64% of rows | Resolved by keying on `game_id` + tip-off time |
| Models overwritten in place, no versioning | Medium | No historical model binary exists | Baseline must be reconstructed, not recovered (§10) |
| Ledger `usage`/`pace`/`rest_days` 100% null | Low | Those columns are unusable | Do not rely on them; recompute from history |
| `prop_open_close.date` malformed | Low | Stored as integer-like, parses to 1970 | Parse explicitly when market work begins |
| 2023 season is 34 junk rows, 1 player | Low | Not a usable season | Exclude; recommend 2024+ only |

---

## 8. Recommended replay architecture

Chronological, checkpointed on **tip-off timestamps**, never on `game_date`.

```
for each game in chronological order of start_utc:
    1. state  = HistoryStore.as_of(start_utc)      # strictly-before; enforced
    2. slate  = resolve_slate(game)                # roster + availability convention
    3. feats  = projector.build_features(state, slate)
    4. proj   = projector.project(feats)
    5. freeze proj -> experiments/<exp>/frozen/<game_id>.csv   # written once
    6. attach actuals from normalized history
    7. grade and advance
```

Guarantees:

- `AsOfState.__post_init__` raises `LeakageError` if any row at or after the
  cutoff is present. The cutoff is **exclusive**: a game starting exactly at the
  cutoff is future.
- The only history a projector receives is the `AsOfState` slice. No season
  aggregate computed through a later date is reachable.
- Frozen artifacts are never rewritten, which makes replay both resumable and
  honest — a re-run cannot quietly improve a past projection.
- `HistoryStore.from_lab_data()` raises if normalized history is missing rather
  than falling back to date-only ordering.

**Same-date games.** Exact start times exist for 100% of games, so per-game
checkpoints are used. An evening game may legitimately use an afternoon game's
result; an afternoon game never sees the evening's. No conservative date
boundary is needed, and no limitation needs documenting on this point.

**Splits.** Chronological only. Random row splits are rejected by the experiment
manifest schema, because same-game teammates are correlated and would leak
across folds.

Recommended windows:

| Split | Period | Player-games |
|---|---|---|
| train | 2024-05-03 → 2025-08-31 | ~11,300 |
| validation | 2025-09-01 → 2026-06-15 | ~4,000 |
| test (touch once) | 2026-06-16 → season end | ~2,000 |

**Recommended seasons to replay: 2024, 2025 and 2026.** 2023 is excluded (34
rows, one player). 2026 replays should be read alongside the caveat that the
season is in progress and the last four weeks of team-context inputs are
degraded in production.

---

## 9. Availability convention (the one deliberate choice)

Because pregame injury data does not exist for 2024–2025, a replay must pick an
availability rule. Each changes what the result means, so `ReplayRunner.resolve_slate`
deliberately raises rather than defaulting:

| Option | What it means | Honest use |
|---|---|---|
| **A. Realized-availability** — project only players who actually played | Removes availability prediction from the experiment entirely | Comparing *conditional-on-playing* accuracy. Optimistic vs a real board; must be stated. |
| **B. Roster-minus-known-out** — project everyone on the team's box score, minus 2026 pregame-dated injury entries | Closest to a real board where data allows | 2026 only |
| **C. Predicted-availability** — train an availability model on `didNotPlay`/`reason` | Fully end-to-end | Most faithful, most work; a second model to validate |

Recommendation: **start with A** for the minutes/stat accuracy question, which is
where the real finding is, and state the conditioning plainly. Move to B for
2026-only board-level replays.

---

## 10. Baseline reconstruction verdict

**Classification: PARTIAL — a filtered exact historical snapshot for a narrow
window, and a reconstructed production-logic baseline everywhere else.**

| Baseline kind | Available? | Detail |
|---|---|---|
| **Exact historical snapshot** | **Yes, but narrow and filtered** | 68 archived boards, 3,811 rows, 119 stable columns, 2026-05-08 → 2026-07-22. Valid only for the ~77% of games tipping after the 18:30 ET freeze. Roughly **52 usable slates**. |
| **Reconstructed production-logic** | Yes | The production serving path is unusually reproducible: features are the player's last dataset row, so "filter to `start_utc <`, take the last row per player" reproduces it exactly, including the one-game staleness. |
| **Current-model-on-historical-features** | Yes, with a caveat | The current `.joblib` files can be scored on reconstructed features, but they were trained on data covering the replay window — this is an in-sample baseline and must be labelled as such. |
| **Naive statistical** | Yes | Fully supported. |

**The exact historical production model cannot be recovered for any past date.**
Model binaries are overwritten in place with no versioning (current mtime
2026-07-25 11:31), and `model_version` in the ledger is a single constant string.
Per the decision policy: this does not prevent a valid experimental lab. It means
any reconstruction must be labelled `reconstructed_production_logic`, never
`exact_historical_snapshot` — a distinction the manifest schema enforces.

**Recommended leak-safe naive baselines** (experiment references, not production
candidates): previous-season average; prior-games season average
(`shift(1).expanding()`); last-3, last-5, last-10 averages; minutes-adjusted
rolling average (per-minute rate × projected minutes); opponent-adjusted rolling
average.

The minutes-adjusted rolling average deserves priority — given finding #1, a
simple rate × projected-minutes baseline may well beat the production stat models
end-to-end, and that comparison is the fastest way to size the problem.

---

## 11. Proposed evaluation framework

Implemented in `grading/metrics.py` and `grading/grader.py`.

**Point projections** (minutes, points, rebounds, assists, threes, steals,
blocks, and the PRA/PR/PA/RA combos): MAE, RMSE, mean bias, median absolute
error, % within 1, % within 2, correlation, normalized MAE (MAE ÷ actual mean,
for cross-category comparison), and calibration by projection bucket.

**Segments:** split, slate date, season, team, starter vs bench, expected-minutes
bucket (0-10 / 10-20 / 20-28 / 28-34 / 34+), rest status, stat category.

**Ranked output:** accuracy among the top 5, 10 and 20 projections per slate —
the rows a user actually reads, scored separately rather than averaged into the
pool.

**Candidate vs baseline:** metrics restricted to rows where the two disagree by
≥ 2 units, plus the candidate's win rate there. Agreement rows carry no
information about which model is better.

**Probabilistic outputs only:** log loss, Brier score, reliability curve. Applied
to simulator over/under probabilities, not to point projections.

**Betting profit is not an objective.** It is a downstream consequence of
accuracy and selection, and optimizing it directly rewards variance. `wnba_v2`
already covers market/ROI evaluation separately.

---

## 12. Safe work completed

- Created the isolated lab with an enforced write guard (`assert_lab_path`)
  that resolves paths before checking, so `..` traversal and symlinks cannot
  escape.
- Built and **ran** the dataset inventory across 13 datasets plus the archive
  directory.
- Built and **ran** the game index: 811 games parsed from the ESPN summary
  cache in 8.5s, 100% with tip-off times, 100% with 10 flagged starters.
  Verified idempotent — a second run parses 0 files and leaves the output
  byte-identical.
- Built and **ran** history normalization: 17,360 player-games and 1,622
  team-games onto true timestamps, 0 dropped, 0 duplicate keys.
- Built and **ran** the leakage audit: 84 features classified, 7 empirical
  checks all confirmed against live artifacts.
- Implemented the point-in-time `AsOfState` / `HistoryStore`, the replay runner
  interface, the grading metric suite and grader, the experiment manifest
  schema, and the promotion report template.
- Wrote 29 tests, all passing.

**Not done, deliberately:** no backfill from uncertain sources, no model
training, no promotion, no production change. `ReplayRunner.resolve_slate`
raises rather than guessing at availability.

### Smallest practical backfill to close the remaining gap

One local step, no network: reparse `wnba_v2/data/team_games/_cache/*.json` for
the 59 games between 2026-06-28 and 2026-07-22 into the lab's normalized
player-game table, extending `starter` / `played` / `position` coverage to the
present. Everything else needed for a 2024–2026 replay is already on disk.

---

## 13. Files created or modified

**Created — all under `sports/wnba/learning/analytics_lab/`:**

```
README.md
config/lab_config.py
inventory/inventory_datasets.py
inventory/build_game_index.py
leakage/audit_features.py
replay/build_history.py
replay/as_of_state.py
replay/runner.py
grading/metrics.py
grading/grader.py
experiments/manifest_schema.json
promotion/PROMOTION_REPORT_TEMPLATE.md
tests/test_lab_isolation.py
reports/initial_feasibility_report.md
__init__.py + package __init__.py files
```

**Generated artifacts (all inside the lab):**

```
data/normalized/dataset_inventory.csv | .json
data/normalized/dataset_schema.csv
data/normalized/game_index.csv                (811 rows)
data/normalized/player_games_indexed.csv      (17,360 rows)
data/normalized/team_games_indexed.csv        (1,622 rows)
reports/leakage_audit.csv                     (84 rows)
reports/leakage_checks.csv                    (7 rows)
```

**Modified:** none.

**Production verification.** A manifest of size and mtime for the 83 top-level
production files (`*.py`, `*.csv`, `*.joblib`, `*.json`, `*.sh` at depth ≤ 2) was
captured before any work and re-captured after: **`diff` is empty**. A
`find -newermt` sweep of the whole WNBA tree confirms every touched file lives
under `learning/analytics_lab/`. A stray `.pytest_cache/` created at the WNBA
root by the first test run was removed; tests are documented to run with
`-p no:cacheprovider`.

---

## 14. Tests run and results

```
python3 -m pytest learning/analytics_lab/tests -q -p no:cacheprovider
29 passed in 1.01s
```

| Group | Tests | What is proven |
|---|---|---|
| Path guards | 15 | Writes to `projections.csv`, `wnba_best_bets_today.csv`, the raw/processed/model dirs, the archives, `Best_Bets/`, `wnba_v2/`, `edgeranked-sportsai/` and `EdgeRanked/site/` all raise. `..` escape raises. Sibling `learning/` ledgers raise. Legal lab paths accept. |
| Artifact containment | 1 | Every artifact the lab has generated resolves inside the lab |
| Import hygiene | 1 | No lab module imports a side-effecting production pipeline module |
| Date integrity | 3 | All 811 start timestamps parse; game IDs unique; ET/UTC divergence holds at 44.5% |
| Key uniqueness | 2 | 0 duplicate `(player_key, game_id)`; every row timestamped |
| Starter integrity | 1 | Exactly 10 starters in every indexed game |
| Leak-safety | 6 | Target game excluded from `AsOfState`; rolling means use prior games only; construction rejects future rows; cutoff exclusive at exact tip-off; rest measured from previous tip-off; missing history raises instead of falling back |

Existing WNBA tests, unchanged and still passing:

```
python3 -m pytest accuracy_recovery/test_recovery_selection.py projection_accuracy/test_accuracy_page.py -q
```

---

## 15. Exact next recommended phase

**Phase 1 — Quantify the minutes leak (highest value, fully unblocked).**

1. Reparse the 59-game cache gap so the normalized history runs to 2026-07-22.
2. Build an as-of feature reconstruction using `AsOfState`, with three variants:
   production-equivalent (one game stale), fresh (includes the last completed
   game), and fresh + per-game position + `team_game_logs` pace.
3. Train minutes and stat models chronologically, with the stat models consuming
   **projected** minutes, and compare end-to-end against:
   (a) the filtered exact-snapshot baseline on the ~52 clean archived slates,
   (b) a reconstructed production-logic baseline across 2024–2026,
   (c) the minutes-adjusted rolling-average naive baseline.
4. Report MAE, bias and calibration per stat, per minutes bucket and per
   starter/bench, plus top-5/10/20, using the availability convention from §9
   stated explicitly.

The question this answers: *how much of the production stat models' apparent
accuracy is the actual-minutes feature, and does removing it while feeding
projected minutes make the deployed board better or worse?* Nothing about that
requires a production change, and the answer determines whether the rest of the
lab roadmap is worth building.

**Then, separately from the lab** — two production repairs this audit surfaced,
each independently actionable: the dead `pace`/`off_rating`/`def_rating` feed
since 2026-06-28, and the UTC-vs-ET `game_date` convention that produces
duplicate player-date rows.
