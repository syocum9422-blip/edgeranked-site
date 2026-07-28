"""EXP003 — exact rest from tip-off times vs production's date-differenced rest."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from analytics_lab.experiments.framework.base import Experiment, ExperimentContext
from analytics_lab.experiments.framework.manifest import ExperimentManifest


class ExactRestDays(Experiment):
    """Replace production's UTC-date-differenced rest with tip-off-derived rest.

    Production computes `rest_days` as `(utc_game_date - prev_utc_game_date) - 1`,
    clipped to [0, 7]. Because `game_date` is the UTC date, an evening game is
    filed a day late, so evening-to-evening pairs read one day short of their real
    layoff while afternoon games do not — the error is systematic, not random.
    Long layoffs also saturate at 7.
    """

    manifest = ExperimentManifest(
        experiment_id="EXP003",
        title="Exact rest days from tip-off times",
        question=(
            "Does rest computed from exact tip-off timestamps improve projections "
            "over production's UTC-date-differenced, 0-7-clipped rest_days?"
        ),
        hypothesis=(
            "Marginally. Rest genuinely affects minutes and efficiency, but the "
            "production construction is wrong by at most a day for most rows, and "
            "the stat models were fitted on the miscomputed version, so a corrected "
            "input may not help a fixed model."
        ),
        expected_improvement="Under 0.5% pooled MAE; possibly none without retraining.",
        features_modified=["rest_days"],
        description=(
            "`rest_days` is replaced with `floor(rest_hours / 24)` where `rest_hours` "
            "is the exact interval between the previous tip-off and this one. The "
            "same [0, 7] clip is applied so the change is the measurement, not the "
            "range. `is_back_to_back` is deliberately left on the production "
            "definition, keeping this to one variable."
        ),
        limitations=[
            "`is_back_to_back` still uses production's `rest_days <= 0` rule, so part "
            "of the rest signal reaching the model remains on the old construction. "
            "That is the price of the single-variable rule; a combined test is "
            "listed under future work.",
            "The models were trained on the miscomputed rest, so their fitted "
            "response is calibrated to it.",
        ],
        future_work=[
            "Run a two-variable version changing rest_days and is_back_to_back "
            "together, to measure the full rest correction.",
            "Test rest as continuous hours rather than clipped whole days.",
        ],
    )

    def build_variant(self, context: ExperimentContext) -> pd.DataFrame:
        frame = context.baseline_frame.copy()
        asof = context.asof_rows()
        exact = np.floor(asof["rest_hours"] / 24.0)
        # Same clip as production, so the comparison isolates the measurement.
        frame["rest_days"] = exact.fillna(3).clip(lower=0, upper=7).to_numpy()
        return frame

    def interpretation(self, result: dict) -> str:
        baseline_rest = result["baseline"].frame["rest_days"]
        asof = result["baseline"].rows
        exact = np.floor(asof["rest_hours"] / 24.0).fillna(3).clip(0, 7)
        differing = (baseline_rest.to_numpy() != exact.to_numpy()).mean()
        saturated = (exact >= 7).mean()
        return (
            f"The two constructions disagree on **{differing:.1%}** of rows — the "
            "systematic consequence of filing evening games under the next UTC date. "
            f"A further **{saturated:.1%}** of rows sit at the 7-day clip, where both "
            "constructions are equally blind to how long the layoff really was.\n\n"
            "A null result here is informative rather than disappointing: it would "
            "mean the date-convention defect, real as it is, costs little in "
            "projection accuracy, and should be prioritised for the join correctness "
            "problems it causes elsewhere rather than for model gain."
        )


EXPERIMENT = ExactRestDays()
