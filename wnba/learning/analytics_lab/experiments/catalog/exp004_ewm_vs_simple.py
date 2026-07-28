"""EXP004 — exponentially weighted vs simple rolling averages."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from analytics_lab.experiments import production_adapter as PA
from analytics_lab.experiments.framework.base import Experiment, ExperimentContext
from analytics_lab.experiments.framework.manifest import ExperimentManifest

WINDOWS = (3, 5, 10)


class EwmVsSimpleRolling(Experiment):
    """Feed the exponentially weighted mean into every simple-rolling slot.

    Production supplies both forms: three simple rolling means per stat and one
    EWM (alpha 0.35). This asks whether the recency weighting the EWM applies is
    better information than equal weighting over a fixed window.
    """

    manifest = ExperimentManifest(
        experiment_id="EXP004",
        title="Exponentially weighted vs simple rolling averages",
        question=(
            "Do exponentially weighted rolling averages of a player's recent stats "
            "outperform the simple fixed-window rolling averages production feeds "
            "the model?"
        ),
        hypothesis=(
            "No, or barely. Both summarise the same games; the EWM only reweights "
            "them. With three windows already present the model can approximate any "
            "reasonable weighting itself, so replacing all three with one series is "
            "more likely to lose information than gain it."
        ),
        expected_improvement=(
            "None expected. This is designed as a falsification test — a plausible "
            "idea that should be ruled out cheaply."
        ),
        features_modified=[f"{stat}_rolling_mean_{w}" for stat in PA.STATS for w in WINDOWS],
        description=(
            "Every `{stat}_rolling_mean_{3,5,10}` slot is overwritten with that "
            "stat's `{stat}_ewm` value (alpha 0.35, shift(1) applied, so the target "
            "game is still excluded). The rolling *standard deviations* and the "
            "existing `{stat}_ewm` columns are untouched, so the only change is the "
            "weighting scheme behind the level estimates."
        ),
        limitations=[
            "Collapsing three windows onto one series removes the model's ability to "
            "read short-term vs long-term divergence, which is a second change riding "
            "along with the weighting change. A cleaner design substitutes one window "
            "at a time; that is listed under future work.",
            "Alpha is fixed at production's 0.35 and was not tuned. A different alpha "
            "could change the sign of the result.",
        ],
        future_work=[
            "Substitute one window at a time to separate 'EWM vs simple' from "
            "'one series vs three'.",
            "Sweep alpha from 0.1 to 0.6 and report the response curve.",
        ],
    )

    def build_variant(self, context: ExperimentContext) -> pd.DataFrame:
        frame = context.baseline_frame.copy()
        for stat in PA.STATS:
            ewm = frame[f"{stat}_ewm"]
            for window in WINDOWS:
                frame[f"{stat}_rolling_mean_{window}"] = ewm
        return frame

    def interpretation(self, result: dict) -> str:
        return (
            "Two changes are bundled here and the design cannot separate them: the "
            "weighting scheme (exponential vs equal) and the loss of multi-window "
            "structure (three series collapsed to one). If the result is a "
            "regression, the second is the more likely cause — the model can no "
            "longer see the gap between a player's last-3 and last-10 form, which is "
            "exactly the signal `minutes_trend_3_over_10` was built to expose.\n\n"
            "Read this as a bound, not an answer: it says whether the EWM alone can "
            "carry the recent-form load, not whether exponential weighting is better "
            "per window."
        )


EXPERIMENT = EwmVsSimpleRolling()
