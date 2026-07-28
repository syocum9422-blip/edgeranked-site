# WNBA Analytics Lab — Experiment catalog

**Generated:** 2026-07-25T15:18:50+00:00  |  **Registered experiments:** 5

Every experiment is a plug-in module under `experiments/catalog/` exposing a module-level `EXPERIMENT`. The runner discovers them; it imports none of them by name. Adding a research question means adding one file.

## EXP001 — Projected minutes vs previous-game minutes

**Question.** Does feeding the minutes model's projection into the stat models' `minutes` feature produce more accurate projections than the previous-game actual minutes production currently serves?

**Hypothesis.** Yes. A single previous observation is a noisy estimate of the minutes a player is about to log; a model fitted on prior-game features should estimate it better, and the stat models consume that slot heavily.

**Expected improvement.** 3-5% pooled MAE reduction, based on the Phase 2C variant sweep.

**Features modified** (1): `minutes`

**Seasons.** 2024, 2025, 2026  |  **Stats.** points, rebounds, assists, threes_made, steals, blocks

**Sample.** 13,802 paired player-games

**Result.** pooled MAE 1.5734 → 1.5364 (-2.35%), RMSE -1.98%, min Holm p = 2.86e-11

**Verdict.** `meaningful` — Significant and material across 3 stats. Warrants a dedicated follow-up study.

**Report.** [`experiments/exp001_research_report.md`](experiments/exp001_research_report.md)

**Known limitations.**

- **The minutes model is itself scored in-sample**, so its projection is flattered relative to what a freshly fitted minutes model would achieve out of sample. The gap this experiment measures is an upper bound.
- The stat models were trained with `minutes` meaning *actual* minutes. Substituting a projection shifts that input's distribution, so a refit could change the size of the effect in either direction.

---

## EXP002 — Opponent defensive rating in the def_rating slot

**Question.** Does supplying the opponent's rolling defensive rating, rather than the player's own team's, improve prediction accuracy in the model's `def_rating_last_10` feature?

**Hypothesis.** Yes, modestly. A player's own team's defensive rating carries almost no information about her own offensive output, so the slot is close to wasted; the opposing defence is the quantity the feature name implies and is genuinely predictive.

**Expected improvement.** 0.5-2% pooled MAE reduction on scoring-related stats.

**Features modified** (1): `def_rating_last_10`

**Seasons.** 2024, 2025, 2026  |  **Stats.** points, rebounds, assists, threes_made, steals, blocks

**Sample.** 13,802 paired player-games

**Result.** pooled MAE 1.5734 → 1.5743 (+0.05%), RMSE +0.05%, min Holm p = 5.98e-05

**Verdict.** `marginal` — Detectable but immaterial (+0.05%); directionally worse.

**Report.** [`experiments/exp002_research_report.md`](experiments/exp002_research_report.md)

**Known limitations.**

- The model was fitted with own-team ratings in this slot, so its learned coefficient reflects that relationship. A slot swap without retraining understates what a correctly specified feature could contribute.
- Both series come from the lab reconstruction, not the production feed, which has carried no ratings at all since 2026-06-28.

---

## EXP003 — Exact rest days from tip-off times

**Question.** Does rest computed from exact tip-off timestamps improve projections over production's UTC-date-differenced, 0-7-clipped rest_days?

**Hypothesis.** Marginally. Rest genuinely affects minutes and efficiency, but the production construction is wrong by at most a day for most rows, and the stat models were fitted on the miscomputed version, so a corrected input may not help a fixed model.

**Expected improvement.** Under 0.5% pooled MAE; possibly none without retraining.

**Features modified** (1): `rest_days`

**Seasons.** 2024, 2025, 2026  |  **Stats.** points, rebounds, assists, threes_made, steals, blocks

**Sample.** 13,802 paired player-games

**Result.** pooled MAE 1.5734 → 1.5738 (+0.02%), RMSE +0.00%, min Holm p = 2.24e-288

**Verdict.** `marginal` — Detectable but immaterial (+0.02%); directionally worse.

**Report.** [`experiments/exp003_research_report.md`](experiments/exp003_research_report.md)

**Known limitations.**

- `is_back_to_back` still uses production's `rest_days <= 0` rule, so part of the rest signal reaching the model remains on the old construction. That is the price of the single-variable rule; a combined test is listed under future work.
- The models were trained on the miscomputed rest, so their fitted response is calibrated to it.

---

## EXP004 — Exponentially weighted vs simple rolling averages

**Question.** Do exponentially weighted rolling averages of a player's recent stats outperform the simple fixed-window rolling averages production feeds the model?

**Hypothesis.** No, or barely. Both summarise the same games; the EWM only reweights them. With three windows already present the model can approximate any reasonable weighting itself, so replacing all three with one series is more likely to lose information than gain it.

**Expected improvement.** None expected. This is designed as a falsification test — a plausible idea that should be ruled out cheaply.

**Features modified** (18): `points_rolling_mean_3`, `points_rolling_mean_5`, `points_rolling_mean_10`, `rebounds_rolling_mean_3`, `rebounds_rolling_mean_5`, `rebounds_rolling_mean_10` …

**Seasons.** 2024, 2025, 2026  |  **Stats.** points, rebounds, assists, threes_made, steals, blocks

**Sample.** 13,802 paired player-games

**Result.** pooled MAE 1.5734 → 1.5773 (+0.24%), RMSE +0.28%, min Holm p = 1.08e-03

**Verdict.** `marginal` — Detectable but immaterial (+0.24%); directionally worse.

**Report.** [`experiments/exp004_research_report.md`](experiments/exp004_research_report.md)

**Known limitations.**

- Collapsing three windows onto one series removes the model's ability to read short-term vs long-term divergence, which is a second change riding along with the weighting change. A cleaner design substitutes one window at a time; that is listed under future work.
- Alpha is fixed at production's 0.35 and was not tuned. A different alpha could change the sign of the result.

---

## EXP005 — Recent form vs season-to-date average

**Question.** Does a player's recent form carry information beyond her season-to-date average, or would the season average alone serve the model as well?

**Hypothesis.** Recent form matters. Roles change mid-season through trades, injuries and rotation shifts, and 16.8% of player-seasons involve more than one team, so a season average should lag reality and error should rise measurably when recent windows are removed.

**Expected improvement.** A regression is the expected and desired outcome: the size of the degradation measures how much recent form is worth.

**Features modified** (24): `points_rolling_mean_3`, `points_rolling_mean_5`, `points_rolling_mean_10`, `rebounds_rolling_mean_3`, `rebounds_rolling_mean_5`, `rebounds_rolling_mean_10` …

**Seasons.** 2024, 2025, 2026  |  **Stats.** points, rebounds, assists, threes_made, steals, blocks

**Sample.** 13,802 paired player-games

**Result.** pooled MAE 1.5734 → 1.5762 (+0.17%), RMSE +0.19%, min Holm p = 1.01e-06

**Verdict.** `marginal` — Detectable but immaterial (+0.17%); directionally worse.

**Report.** [`experiments/exp005_research_report.md`](experiments/exp005_research_report.md)

**Known limitations.**

- This measures how much the *fixed* model relies on recent-form inputs, not how much a refit model could extract from them. A model retrained without recent form would partially compensate through other features.
- **Recent form still reaches the model through channels this ablation does not touch**, so the measured degradation is a *lower bound*, not the value of recent form. `rate_{stat}_last_10` and `usage_proxy_last_{5,10}` are derived from the last-10 windows before the substitution is applied; `{stat}_rolling_std_{3,5,10}`, `player_{stat}_std_10` and `minutes_trend_3_over_10` also encode recency. Roughly half the recent-form channels survive.
- The season average resets each season, so early-season rows have very little history on either side and the contrast is weakest exactly where recent form should matter most.

---

