# Phase 3 — Summary

**Date:** 2026-07-25
**Deliverable:** a permanent research environment capable of answering future
questions about the production model without touching it.
**Production changes:** none. 548 production files byte-identical; model binary
hashes unchanged; zero artifacts outside the lab.

---

## What was built

A plug-in experiment framework: pre-registered manifests, a shared production
baseline, a mechanical single-variable guard, paired significance testing with
Holm correction and a practical-effect threshold, automatic research reports, and
a leaderboard. Design and rationale in
[`phase3_framework.md`](phase3_framework.md); per-experiment detail in
[`experiment_catalog.md`](experiment_catalog.md).

Five experiments were registered and run against a shared sample of **13,802
paired player-games** (2024-05-16 → 2026-07-22, 288 players, 727 games, 260
slates).

---

## Results

| Experiment | Question | Verdict | Pooled MAE Δ |
|---|---|---|---|
| **EXP001** | Does projected minutes outperform previous-game minutes? | `meaningful` | **−2.35%** |
| **EXP003** | Does correct rest-day information improve projections? | `marginal` | +0.02% |
| **EXP002** | Does opponent defensive rating improve accuracy? | `marginal` | +0.05% |
| **EXP005** | Does recent form matter more than season averages? | `marginal` | +0.17% |
| **EXP004** | Do EWM averages outperform simple rolling averages? | `marginal` | +0.24% |

One clear positive, four null-to-slightly-negative results. That distribution is
what an honest framework should produce: most plausible ideas do not work, and
the value of the environment is that it says so cheaply.

### EXP001 is the only finding

Feeding the minutes model's own projection into the stat models' `minutes` slot
— a value production already computes and then discards — improves pooled MAE by
**2.35%**, significant after Holm correction on 3 of 6 stats.

| Stat | baseline MAE | variant MAE | rel. | Holm p | verdict |
|---|---|---|---|---|---|
| points | 4.4112 | 4.2627 | −3.37% | 2.9e-11 | `meaningful` |
| rebounds | 1.8410 | 1.7875 | −2.91% | 2.9e-11 | `meaningful` |
| threes_made | 0.7485 | 0.7352 | −1.78% | 8.3e-05 | `meaningful` |
| assists | 1.2459 | 1.2388 | −0.57% | 4.4e-01 | `not_significant` |
| blocks | 0.4869 | 0.4849 | −0.42% | 5.7e-01 | `not_significant` |
| steals | 0.7072 | 0.7094 | +0.32% | 2.2e-02 | `not_significant` |

The gain lands on volume stats and leaves the low-count stats alone, which is
what a better minutes estimate should do.

**Where it comes from matters more than the headline.** By expected-minutes
bucket:

| Bucket | Δ MAE |
|---|---|
| 0-10 min | **+0.023** (worse) |
| 10-20 min | −0.102 |
| 20-28 min | −0.072 |
| 28-34 min | −0.013 |
| 34+ min | **+0.072** (worse) |

The improvement is concentrated in rotation players and the model is *worse* at
both extremes. For a 35-minute starter the previous game's minutes are already an
excellent estimate and the projection regresses her toward the mean; for a
deep-bench player it does the same in the other direction. A production change
based on this should be evaluated with that shape in mind, not on the pooled
number.

Consistent across seasons (2024 −0.037, 2025 −0.041, 2026 −0.033), larger for
starters (−0.046) than bench (−0.027), and largest after long layoffs (6d+
−0.127), where a single prior observation is least informative. Top-10 points MAE
improves 5.582 → 5.429.

### The four null results are useful

- **EXP002** — putting the opponent's defensive rating into the `def_rating_last_10`
  slot (which production fills with the player's *own* team's rating) changes
  almost nothing. The likeliest explanation is not that opponent defence is
  uninformative but that the fixed model gives the slot little weight; only
  retraining can separate those.
- **EXP003** — correcting rest days from UTC-date differencing to exact tip-off
  intervals costs +0.02%, on rows that disagree substantially. The date-convention
  defect is real but should be prioritised for the join-correctness problems it
  causes elsewhere, not for model gain.
- **EXP004** — collapsing three rolling windows onto the EWM is mildly worse.
  Design caveat: this bundles "exponential vs equal weighting" with "one series vs
  three" and cannot separate them.
- **EXP005** — replacing recent-form level estimates with season averages costs
  only +0.17%. **This does not mean recent form is worthless.** The substitution
  is applied after `rate_*_last_10` and `usage_proxy_last_*` have been derived
  from the last-10 windows, so roughly half the recent-form channels survive the
  ablation. The result is a lower bound and the experiment's own report says so.

---

## What the framework guarantees

| Guarantee | How |
|---|---|
| Experiments never compare different samples | one baseline built per session, shared; a test asserts identical sample signatures and identical baseline MAE across all persisted runs |
| Only one variable changes | `assert_single_variable()` diffs the frames NaN-aware and aborts on any undeclared change |
| No promotion on a tiny MAE move | `meaningful` needs significance **and** ≥1% relative effect; `regression` needs both in the other direction; everything else is `marginal` |
| Hypotheses are not retrofitted | manifest with question, hypothesis and expected improvement written before the run |
| Stale results are detectable | model binaries fingerprinted into every `summary.json` |
| No path to production | no `joblib.dump`, no `.fit(` anywhere under `experiments/`, asserted by test |

### One correction made during this phase

The first verdict rule classified *any* statistically significant degradation as
a `regression`, so EXP002 (+0.05%) and EXP003 (+0.02%) were both labelled
regressions. At 13,802 paired rows almost anything is significant; demoting on
statistical evidence alone is the same mistake as promoting on it. The rule is
now symmetric and a test pins it.

Similarly, EXP005 originally modified only the rolling-mean slots, leaving the
EWM columns to supply recent form — the experiment could not have answered its
own question. It now ablates both, and its report states plainly that even this
is a lower bound.

---

## Files created

```
experiments/framework/{manifest,baseline,base,registry,significance,runner,reporting,leaderboard}.py
experiments/catalog/exp00{1..5}_*.py
experiments/runs/EXP00{1..5}/{manifest,summary}.json + per_stat/metrics/segments/top_n.csv
reports/phase3_framework.md
reports/experiment_catalog.md
reports/research_leaderboard.md
reports/phase3_summary.md
reports/experiments/exp00{1..5}_research_report.md
data/baselines/leaderboard.csv
tests/test_experiment_framework.py
```

**Modified:** `experiments/framework/*` only. No production file.

---

## Tests

```
python3 -m pytest learning/analytics_lab/tests -q -p no:cacheprovider
103 passed
```

34 new Phase 3 tests covering manifest validation, the single-variable guard
(including NaN handling in both directions), the verdict rules and their
symmetry, Holm monotonicity, registry discovery, baseline determinism and
production fidelity, cross-run sample identity, and isolation.

Pre-existing WNBA tests: 7 passed, unchanged.

---

## Isolation verification

- 548 production files byte-identical (deep manifest of `data/`, `models/`,
  `outputs/`, `Best_Bets/`, `learning/`, excluding the lab)
- production model binary MD5s unchanged
- zero files created or modified outside `analytics_lab/`
- no cron, service, environment variable, deployment or website touchpoint

---

## What this phase does not claim

Nothing here is a deployment recommendation, and none of these results licenses a
production change on its own. Every result is subject to the framework-wide
limitations printed in each report — chiefly that **no model was retrained**, so
an experiment measures how the *deployed* model responds to a different input,
not what a refit model could achieve. A feature the current model cannot exploit
may still be valuable.

EXP001 is the one result strong enough to justify a dedicated follow-up study. It
already has a corresponding entry (P1) in
[`proposed_production_changes.md`](proposed_production_changes.md), queued for
separate human review — which is where that decision belongs, not here.

---

## Next questions the framework is ready for

- Retrain-capable experiments: refit the stat models under a variant feature
  construction, so ceilings can be measured rather than inferred. The runner's
  baseline abstraction already supports swapping the model bundle.
- A total recent-form ablation that neutralises every recency-bearing channel,
  which EXP005 cannot.
- Walk-forward evaluation, replacing the in-sample binaries with models fit only
  on prior data — the single largest improvement available to the framework's
  credibility.
- Per-segment experiments aimed at the EXP001 shape: a minutes estimate that
  blends toward the previous game for high-minute starters.
