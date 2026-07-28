# Phase 2G — Honest baseline verdict

**Date:** 2026-07-25

Four baseline options exist. They answer different questions and are **not
combinable into one metric** — each has a different date range, a different
authenticity profile, and different valid uses. An experiment should name the
one it used and stay with it.

---

## 1. Exact archived production snapshot

The dated boards under `outputs/archive/projections/`, restricted to the
`CLEAN_PREGAME` artifacts identified in
[`archive_integrity_report.md`](archive_integrity_report.md).

| | |
|---|---|
| **Range** | 2026-05-08 → 2026-07-20 |
| **Coverage** | 47 of 69 archived slates; 2,460 projection rows |
| **Model binary historically authentic?** | **No.** Binaries are overwritten in place with no versioning. The board's *output* is authentic; the model that produced it is unrecoverable. |
| **Features historically authentic?** | **Yes** — these are the values production actually used, whatever their defects. |
| **Frozen pregame?** | **Yes**, by construction — that is the classification criterion. |

**Valid uses.** Measuring what production actually published, and how accurate
it was, over those 47 slates. The only baseline that can answer "how good is the
live board?" without reconstruction assumptions.

**Invalid uses.** Any date before 2026-05-08. The 22 non-clean artifacts. Any
claim about a historical *model version*. Any statement that a reconstruction
matches it — it is the reference, not a reproducible target.

---

## 2. Current model binaries on reconstructed historical features

The current `wnba_*_model.joblib` files scored on the lab's as-of features. This
is what Phase 2C and 2D used.

| | |
|---|---|
| **Range** | 2024-05-14 → 2026-07-22 (13,802 eligible player-games) |
| **Model binary historically authentic?** | **No** — current binaries, and the only ones that exist. |
| **Features historically authentic?** | **Yes** — reconstructed as-of, verified by the Phase 2B test suite. |
| **Frozen pregame?** | **No** — computed now, from a model trained on data covering the whole window. |

**Valid uses.** Controlled A/B contrasts where the model and rows are held
identical and one input varies — exactly the Phase 2C/2D design. The
*differences* between variants are trustworthy.

**Invalid uses.** Any absolute accuracy claim. Every number is in-sample: the
models saw this window during training. Reporting a headline MAE from this
baseline as production accuracy would repeat the mistake Phase 2C exists to
expose.

---

## 3. Reconstructed production-logic baseline

Reimplementing the production serving path — serve each player's last stored row,
with its one-game-stale rolling values and previous-game actual minutes — and
scoring it as production would.

| | |
|---|---|
| **Range** | 2024-05-14 → 2026-07-22, wherever two prior games exist |
| **Model binary historically authentic?** | **No** — current binaries. |
| **Features historically authentic?** | **Yes**, and faithful to production's defects, which is the point. |
| **Frozen pregame?** | **No** — reconstructed. |

Phase 2D showed the reconstruction is exact enough to reproduce production's
behaviour: the stale variant differs from fresh as-of features on **71.7%** of
carried-forward feature values, matching the observed live board.

**Valid uses.** Extending a production-like comparison to dates with no archived
board, and isolating the cost of individual production defects.

**Invalid uses.** Calling it "the historical production model". Per the Phase 1
decision policy, a reconstruction may never be labelled an exact snapshot. The
experiment manifest schema enforces this with a `baseline.kind` enum.

---

## 4. Naive statistical baselines

Last-3 / last-5 / last-10 averages, prior-games season average, minutes-adjusted
rolling rate, opponent-adjusted rolling average — all leak-safe by construction
from the as-of feature table.

| | |
|---|---|
| **Range** | 2024-05-14 → 2026-07-22, full coverage |
| **Model binary historically authentic?** | **N/A** — no model. |
| **Features historically authentic?** | **Yes.** |
| **Frozen pregame?** | **N/A** — deterministic from prior games. |

**Valid uses.** The floor any candidate must clear. Cheap, transparent, available
over the whole window.

**Invalid uses.** As a production replacement, or as evidence that a model is
good — beating a last-5 average is necessary, not sufficient.

---

## Recommended experimental baseline

**For accuracy experiments: option 3 (reconstructed production-logic), with
option 4 as the floor and option 1 as the reality check on its 47 clean slates.**

Rationale: option 3 covers the full 2024–2026 window, reproduces production's
actual behaviour including its defects, and shares rows with any candidate, so
paired comparison is available. Option 1 is the only honest answer to "what did
production really publish", but 47 slates in one partial season is too thin to
carry an experiment on its own — and it cannot separate a model change from a
feature change, because the model is unrecoverable.

Report option 1 alongside option 3 whenever the dates overlap. If the two
disagree about production's accuracy, the reconstruction is wrong and should be
fixed before any candidate is judged against it.

---

## Phase 2 findings that constrain every baseline

| Finding | Consequence |
|---|---|
| Actual-minutes leakage inflates apparent accuracy by **16.3%** (pooled MAE 1.293 leaked vs 1.503 best leak-safe) | No baseline may use target-game minutes. The production training MAE is not a comparison point. |
| Production's shipped minutes input (previous game's actual) is the **worst of eight** variants, 1.567 pooled MAE | The reconstructed production-logic baseline is a genuinely weak bar; clearing it is not evidence of a good model. |
| One-game-stale rolling features cost **+0.0091 pooled MAE (+0.59%)** | Real but second-order. Do not oversell it: it is ~1/7th the size of the recoverable minutes gap. |
| Team-context pace/ratings dead in production since **2026-06-28** | Baselines spanning that date mix two feature regimes. Use the lab reconstruction throughout, or restrict the window. |
| Positions are a **current-profile** label in both sources | Position-conditioned features are anachronistic in every baseline. Disclose, do not silently exclude. |
| The board's `GAME_DATE` is the **ET slate date**, while `wnba_player_games.game_date` is the **UTC date** | Joining archive to actuals on a date column silently mismatches evening games. Join on ids and tip-off times. |

---

## Verdict

An honest experimental lab is available now over **2024-05-14 → 2026-07-22**,
using reconstructed as-of features and reconstructed production-logic baselines,
with a 47-slate exact-snapshot reference in 2026.

The exact historical production *model* remains unrecoverable and will stay so
unless model binaries start being versioned. That limits what can be claimed —
but not what can be learned, because the two largest defects found so far are
properties of the *serving path*, not of the model weights, and both are
measurable without an authentic historical binary.
