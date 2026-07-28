# Phase 3 — Research framework

**Date:** 2026-07-25
**Scope:** a permanent, reusable environment for answering analytical questions
about the existing production model.
**Production changes:** none. The production model remains the baseline.

---

## What this is

The Analytics Lab is a research environment, not a production branch. Its job is
to answer questions of the form *does X improve accuracy, for whom, and is the
improvement real?* — using historical evidence, against the production model as
the reference.

It is deliberately incapable of promoting anything. There is no code path from an
experiment to a production artifact, and a test asserts that no module under
`experiments/` calls `joblib.dump` or `.fit(`.

---

## Architecture

```
experiments/
  framework/                the runner and its machinery — knows no experiment
    manifest.py             ExperimentManifest: the pre-registered contract
    baseline.py             the shared production baseline
    base.py                 Experiment ABC + the single-variable guard
    registry.py             plug-in discovery
    significance.py         paired tests, Holm correction, verdict rules
    runner.py               the generic loop
    reporting.py            research report generation
    leaderboard.py          leaderboard + catalog generation
  catalog/                  one file per research question
    exp001_projected_minutes.py
    exp002_opponent_def_rating.py
    exp003_rest_days.py
    exp004_ewm_vs_simple.py
    exp005_recent_form_vs_season.py
  runs/<EXP>/               manifest.json, summary.json, per_stat.csv,
                            metrics.csv, segments.csv, top_n.csv
reports/experiments/        one research report per experiment
```

The runner imports no experiment. Experiments are discovered by scanning
`catalog/` for modules exposing a module-level `EXPERIMENT`; a test parses the
framework's ASTs to confirm nothing there imports the catalog. Adding a research
question is one file.

---

## The experiment contract

An experiment declares a manifest before it runs, then supplies one method:

```python
class MyExperiment(Experiment):
    manifest = ExperimentManifest(
        experiment_id="EXP0NN",
        title=...,
        question=...,              # rejected if it is not a real question
        hypothesis=...,            # stated before the numbers exist
        expected_improvement=...,  # stated before the numbers exist
        features_modified=[...],   # enforced, not documentation
        limitations=[...],
        future_work=[...],
    )

    def build_variant(self, context: ExperimentContext) -> pd.DataFrame:
        frame = context.baseline_frame.copy()
        frame["some_feature"] = ...        # change only what you declared
        return frame
```

The manifest is written first. Question, hypothesis and expected improvement are
recorded before results exist, so an experiment cannot be reframed into a success
after the fact. `ExperimentManifest.__post_init__` rejects an empty
`features_modified` and a "question" that is really a label.

### The single-variable guard

`assert_single_variable()` diffs the variant frame against the baseline frame,
NaN-aware, and raises `SingleVariableViolation` if any undeclared column moved,
if the row count differs, or if the index differs. "Only one variable may change
per experiment" is therefore mechanical, not a convention someone remembers.

Nulling a value counts as a change and filling a null counts as a change — an
ablation cannot slip through as "untouched".

---

## The baseline

Per `phase2_baseline_verdict.md` option 3: **reconstructed production logic**,
version `reconstructed_production_logic_v1`. The current production stat-model
binaries fed the inputs production actually serves:

| Production behaviour | Reproduced in the baseline |
|---|---|
| `minutes` = previous game's actual minutes | yes |
| rolling features one game stale | yes |
| `rest_days` = UTC-date difference − 1, clipped 0–7 | yes |

It is built **once per run session** and shared by every experiment, so all
experiments are scored on identical player-games and their MAE columns are
directly comparable. A test asserts the sample signature is identical across all
persisted runs, and that the baseline MAE agrees to 6 decimal places between
them.

The binaries are fingerprinted (SHA-256 prefix, recorded in every
`summary.json`). If production retrains, the fingerprint changes and past results
are known to be stale rather than silently misleading.

This is **not** the historical production model. Binaries are unversioned and
overwritten in place, so no past model exists to recover. The manifest schema
records the honest label.

### Sample

Regular-season games the player actually played, with enough history for both
feature sets to be defined: **13,802 paired player-games** across 260 slates,
2024-05-16 → 2026-07-22, 288 players, 727 games (2024: 4,426; 2025: 5,403;
2026: 3,973). Preseason and DNPs excluded.

---

## Statistics

Baseline and variant are scored on identical rows, so every test is **paired**.
Pairing removes the between-player variance that dominates absolute error.

| Component | Choice | Why |
|---|---|---|
| Test | Wilcoxon signed-rank on paired absolute errors | paired, no normality assumption, robust to the heavy right tail of absolute error |
| Multiplicity | Holm-Bonferroni across the 6 stats | six simultaneous tests is six chances at a false positive; Holm controls family-wise error without Bonferroni's conservatism |
| α | 0.01 | |
| Interval | 95% percentile bootstrap on the mean paired difference, 2,000 resamples, seed 42 | reproducible, distribution-free |
| Effect size | Cohen's *d* on paired differences, plus relative MAE change | |
| Practical threshold | 1% relative MAE change | |

### Why significance alone is not enough

At ~14k paired rows a difference of 0.02% reaches p < 0.001 while meaning
nothing. Every verdict therefore needs **both** bars:

| Verdict | Condition |
|---|---|
| `meaningful` | significant **and** ≥ 1% relative improvement |
| `regression` | significant **and** ≥ 1% relative degradation |
| `marginal` | exactly one of the two bars cleared, either direction |
| `not_significant` | neither |

The rule is **symmetric on purpose**. An early version demoted a variant to
`regression` on statistical evidence alone; EXP002 and EXP003, at +0.05% and
+0.02%, were both labelled regressions. That is the same error as promoting on a
tiny move, pointed the other way. Both now land at `marginal`, with the direction
stated. A test pins the symmetry.

At the pooled level, a `regression` on any single stat sinks the whole variant: a
change that helps points while breaking rebounds is not an improvement.

---

## Reported metrics

Per stat, for baseline and variant on identical rows: MAE, RMSE, bias, median
absolute error, correlation, paired Δ with 95% CI, Holm-corrected p, Cohen's *d*,
and the share of rows where the variant is closer.

Segmented (all stats pooled): **by season**, **by player role** (starter/bench),
**by expected-minutes bucket** (0-10 / 10-20 / 20-28 / 28-34 / 34+), **by rest
status** (b2b / 2-3d / 4-5d / 6d+).

**Top-10 and top-20** projections per slate are reported separately and flagged,
because each side is judged on the rows *it* would have surfaced — those row sets
differ by construction, so those numbers are not paired and must not be read as
if they were.

---

## Research reports

Every run generates `reports/experiments/exp0NN_research_report.md` with:
executive summary, question, method, sample, results, interpretation,
limitations, recommendation, future work, reproduction command.

They are research documents. The recommendation section never proposes a
production change; it says whether the finding justifies further study. Promotion
remains a separate human decision made with
`promotion/PROMOTION_REPORT_TEMPLATE.md`.

Five limitations are injected into every report automatically, because they apply
to the whole framework and are too easy to forget:

1. **No retraining.** Binaries are held fixed, so an experiment measures how the
   *deployed* model responds to a different input construction — not the value
   that feature would have in a refit model. A feature the current model cannot
   exploit may still be valuable after retraining.
2. **In-sample.** The binaries were trained on data covering this window, so
   absolute MAE is optimistic. Only the paired *difference* is trustworthy.
3. **Not the historical production model.** Unversioned binaries; the baseline
   reconstructs production *logic*, not a snapshot.
4. **Conditional on playing.** Availability prediction is excluded.
5. **Positions are anachronistic.** ESPN's box-score position is an athlete
   profile attribute, constant across seasons, scraped in 2026.

---

## Usage

```bash
cd /home/ubuntu/EdgeRanked/sports/wnba

python3 learning/analytics_lab/experiments/framework/runner.py --list
python3 learning/analytics_lab/experiments/framework/runner.py EXP001
python3 learning/analytics_lab/experiments/framework/runner.py            # all
python3 learning/analytics_lab/experiments/framework/leaderboard.py
python3 -m pytest learning/analytics_lab/tests -q -p no:cacheprovider
```

Running the whole catalog takes about 35 seconds and builds the baseline once.

---

## Isolation

Enforced by `config/lab_config.assert_lab_path()` and by the test suite:

- no write outside `analytics_lab/` — verified by walking every generated artifact
- no `joblib.dump` and no `.fit(` anywhere under `experiments/`
- no import of a side-effecting production pipeline module
- no cron, service, environment, deployment or website touchpoint anywhere in the
  lab

Verified after this phase: **548 production files byte-identical**, model binary
hashes unchanged, zero files created outside the lab.
