# WNBA Analytics Lab — Research leaderboard

**Generated:** 2026-07-25T15:18:50+00:00  |  **Experiments:** 5 registered, 5 run

Sorted by best validated improvement. A validated result outranks an unvalidated one regardless of raw MAE movement — an unverified 3% is worth less than a verified 1%.

All experiments share one baseline (`reconstructed_production_logic_v1`) and one fixed set of player-games, so the MAE column is directly comparable across rows.

| Experiment | Question | Result | MAE Δ | MAE Δ % | RMSE Δ | Status | Notes |
|---|---|---|---|---|---|---|---|
| **EXP001** | Does feeding the minutes model's projection into the stat models' `minutes` feature produce more accurate projections than the previous-game actual minutes production currently serves? | `meaningful` | -0.0370 | -2.35% | -0.0421 | `complete` | Significant and material across 3 stats. Warrants a dedicated follow-up study. |
| **EXP003** | Does rest computed from exact tip-off timestamps improve projections over production's UTC-date-differenced, 0-7-clipped rest_days? | `marginal` | +0.0004 | +0.02% | +0.0001 | `complete` | Detectable but immaterial (+0.02%); directionally worse. |
| **EXP002** | Does supplying the opponent's rolling defensive rating, rather than the player's own team's, improve prediction accuracy in the model's `def_rating_last_10` feature? | `marginal` | +0.0008 | +0.05% | +0.0010 | `complete` | Detectable but immaterial (+0.05%); directionally worse. |
| **EXP005** | Does a player's recent form carry information beyond her season-to-date average, or would the season average alone serve the model as well? | `marginal` | +0.0027 | +0.17% | +0.0040 | `complete` | Detectable but immaterial (+0.17%); directionally worse. |
| **EXP004** | Do exponentially weighted rolling averages of a player's recent stats outperform the simple fixed-window rolling averages production feeds the model? | `marginal` | +0.0038 | +0.24% | +0.0060 | `complete` | Detectable but immaterial (+0.24%); directionally worse. |

## Standing

**Best validated result: EXP001 — Projected minutes vs previous-game minutes** (-2.35% pooled MAE, verdict `meaningful`).

Sample: 13,802 paired player-games, identical across every row above. Model fingerprint `e7353c24f46e9ada` — results are invalidated if the production binaries are retrained, because the baseline would no longer be the same model.

## Verdict counts

| Verdict | Experiments |
|---|---|
| `marginal` | 4 |
| `meaningful` | 1 |

## How to read this

- **Negative MAE Δ favours the variant.**
- `meaningful` requires statistical significance (Wilcoxon signed-rank, Holm-corrected, α = 0.01) **and** a relative MAE change of at least 1%. `regression` requires the same two conditions in the opposite direction.
- `marginal` means exactly one of those two bars was cleared. At ~14k paired rows almost any change is statistically significant, so `marginal` is the common landing place and is not a finding.
- **Nothing here is a deployment recommendation.** Promotion is a separate human decision made with `promotion/PROMOTION_REPORT_TEMPLATE.md`.

