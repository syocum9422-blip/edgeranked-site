# Promotion readiness — `<experiment_name>`

> Filled in by the experiment owner. A lab result is a recommendation, never a
> deployment. Promotion is a separate, human-approved production change made by
> the production tooling, not by anything under `analytics_lab/`.

**Date:** `<YYYY-MM-DD>`
**Question:** `<the single question this experiment set out to answer>`
**Verdict:** `PROMOTE` / `SHADOW` / `ITERATE` / `REJECT`

---

## 1. What was compared

| | Candidate | Baseline |
|---|---|---|
| Description | | |
| Baseline kind | — | `exact_historical_snapshot` / `reconstructed_production_logic` / `current_model_on_historical_features` / `naive_statistical` |
| Feature set | | |
| Training window | | |

State plainly if the baseline is a reconstruction rather than the real historical
production model, and what that changes about how the numbers should be read.

## 2. Evaluation design

- **Split:** chronological — train `<= date>`, validation `<= date>`, test `<= date>`
- **Test period touched:** once / more than once (if more than once, the test result is not a clean estimate — say so)
- **Checkpoint boundary:** tip-off timestamp / ET slate date (state which, and the limitation if date-only)
- **Slates replayed:** `<n>` | **Player-stat rows graded:** `<n>`

## 3. Headline accuracy

| Stat | n | Candidate MAE | Baseline MAE | Δ | Candidate bias | Baseline bias |
|---|---|---|---|---|---|---|
| points | | | | | | |
| rebounds | | | | | | |
| assists | | | | | | |
| threes_made | | | | | | |
| steals | | | | | | |
| blocks | | | | | | |
| minutes | | | | | | |

Include normalized MAE when comparing across categories.

## 4. Where the difference comes from

- **Disagreement rows** (|candidate − baseline| ≥ 2): n = , candidate win rate = , MAE Δ =
- **Top-5 / top-10 / top-20 projections:**
- **By expected-minutes bucket:**
- **By starter vs bench:**
- **By rest status:**
- **By season:**
- **Calibration by projection bucket:** (does the diagonal hold, or is there drift at the extremes)

An improvement that appears only in the pooled average and vanishes in the
segments is a pooling artifact, not an improvement.

## 5. Probabilistic outputs

Only if the candidate emits real probabilities. Log loss, Brier, reliability
curve. Betting profit is not a promotion criterion.

## 6. Risks and limitations

- Reconstruction gaps relied on:
- Data known to be missing or stale over the window:
- Ways this result could be wrong:

## 7. Recommendation

State the recommended next step and the conditions that would change it. If the
recommendation is shadow deployment, name the flag, the default (off), the
metric to watch, and the number of slates before a decision.

## 8. Reproduction

```bash
# exact commands
```

- Manifest: `experiments/<experiment_name>/manifest.json`
- Frozen artifacts: `experiments/<experiment_name>/frozen/`
- Grading report: `reports/<experiment_name>_grading_report.json`
