# WNBA Accuracy Recovery — Phase 2 Candidate Improvements
*Every candidate maps to a Phase 1 root cause. Nothing here is implemented in production; C1–C4 are
selection/probability-layer changes that can be replayed honestly on the full historical prop pool
(line_history Jun 11–Jul 9 + archived boards + actuals). Ranked by expected gain × confidence / risk.*

| # | Candidate | Root cause | Expected gain (late window) | Complexity | Risk | Confidence |
|---|---|---|---|---|---|---|
| C1 | **Variance-honesty repair**: inflate sim std per market by trailing realized z-std (point-in-time, ~1.7–2.2×) before computing hit_rate; existing 0.56 gate then does real work | RC2/RC1 | +3–6pp | Low (one multiplier layer at selection time) | Med (changes all published probs → shadow first) | High |
| C2 | **Combo exposure gate**: combos must clear a stricter threshold (or are dropped entirely); portfolio balance requirement singles-first | RC1 | +5–7pp (singles-only late = 55.5% vs 49.0% all) | Low (filter in build_wnba_best_bets selection) | Low (volume drops ~60%) | High |
| C3 | **Tail-confidence cap**: reject/downweight picks whose claimed prob > ~0.70 (empirically inverted region) | RC2 | +1–2pp | Trivial | Low | High (monotone inversion, n=156 late) |
| C4 | **Combo variance from measured correlations**: rebuild combo std from component stds with corr(PTS,REB)=0.30 etc. instead of near-independent sampling | RC2 | +2–4pp on combos (may re-admit good combos C2 removes) | Med | Med | Med |
| C5 | **Minutes recency repair**: use existing rolling recent-minutes features / trailing-5 blend to remove −1.7 bias | RC4 | +1–3pp | Med (model retrain — needs own validation) | Med | Med |
| C6 | **Role-change guard**: exclude players whose starter status flipped in last 10 days or with <8 games history on current team (expansion/breakout blind spot) | RC5 | +0.5–1pp | Low | Low | Med (n=77, 41.6%) |
| C7 | Line-movement incorporation (fade when line moves against us) | RC1 | unknown | Med | Med | Low (snapshots only since Jun 11) |
| C8 | Opponent-defense/pace refinements | — | ~0 | High | Med | Low (no drift detected; projections already improved) |

**Selected for Phase 3 shadow validation: C1, C2, C3, C6 and combinations.**
C4/C5 are second-wave (require sim/model changes; validate after selection-layer wins are banked).
C7/C8 rejected for now — no Phase 1 evidence of gain.

Key design principle from Phase 1: the projections are fine (MAE improved); the failure is
*probability honesty and pick selection*. Fix selection first — it is lowest-risk, fully
backtestable, and reversible.
