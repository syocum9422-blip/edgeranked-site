"""EXP001 — projected minutes vs previous-game minutes."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from analytics_lab.experiments import production_adapter as PA
from analytics_lab.experiments.framework.base import Experiment, ExperimentContext
from analytics_lab.experiments.framework.manifest import ExperimentManifest


class ProjectedMinutes(Experiment):
    """Feed the minutes model's own output into the stat models' `minutes` slot.

    Production computes `projected_minutes` in `build_projection_rows()` and then
    never writes it into the frame the stat models consume; that slot keeps the
    previous game's actual minutes. This substitutes the projection.

    The minutes model is safe to use historically: its feature list does not
    contain `minutes`, so it reads only prior-game information.
    """

    manifest = ExperimentManifest(
        experiment_id="EXP001",
        title="Projected minutes vs previous-game minutes",
        question=(
            "Does feeding the minutes model's projection into the stat models' "
            "`minutes` feature produce more accurate projections than the "
            "previous-game actual minutes production currently serves?"
        ),
        hypothesis=(
            "Yes. A single previous observation is a noisy estimate of the minutes "
            "a player is about to log; a model fitted on prior-game features should "
            "estimate it better, and the stat models consume that slot heavily."
        ),
        expected_improvement="3-5% pooled MAE reduction, based on the Phase 2C variant sweep.",
        features_modified=["minutes"],
        description=(
            "The minutes model (`models/wnba_minutes_model.joblib`) is run on the "
            "same as-of feature frame, its output clipped to [5, 40] exactly as "
            "production does, and written into the `minutes` column. Nothing else "
            "changes."
        ),
        limitations=[
            "**The minutes model is itself scored in-sample**, so its projection is "
            "flattered relative to what a freshly fitted minutes model would achieve "
            "out of sample. The gap this experiment measures is an upper bound.",
            "The stat models were trained with `minutes` meaning *actual* minutes. "
            "Substituting a projection shifts that input's distribution, so a refit "
            "could change the size of the effect in either direction.",
        ],
        future_work=[
            "Refit the stat models with projected minutes on both sides of training "
            "and serving, to measure the effect without the train/serve mismatch.",
            "Test whether a minutes model trained walk-forward, rather than the "
            "current in-sample binary, preserves the gain.",
        ],
    )

    def build_variant(self, context: ExperimentContext) -> pd.DataFrame:
        bundle = PA.load_minutes_model()
        if bundle is None:
            raise FileNotFoundError("minutes model not found")
        if "minutes" in bundle["feature_list"]:
            raise RuntimeError(
                "the minutes model now consumes `minutes`; it is no longer leak-safe "
                "to run historically and this experiment must be redesigned"
            )
        frame = context.baseline_frame.copy()
        projected = np.clip(PA.predict(bundle, frame), 5, 40)
        frame["minutes"] = projected
        return frame

    def interpretation(self, result: dict) -> str:
        pooled = result["pooled"]
        rows = result["baseline"].rows
        projected_note = (
            f"The substitution moves pooled MAE by {pooled['pooled_relative_change']:+.2%} "
            f"across {result['baseline'].n:,} paired player-games."
        )
        volatile = rows[(rows["minutes"] - rows["prev_game_minutes"]).abs() >= 8]
        return (
            f"{projected_note}\n\n"
            f"This is the one experiment in the catalog testing a change that requires "
            f"no new data and no retraining — the projection already exists in the "
            f"production run and is discarded. "
            f"{len(volatile):,} of {len(rows):,} rows ({len(volatile)/len(rows):.1%}) "
            f"have the player's minutes moving by 8 or more from their previous game; "
            f"those are the rows where a single prior observation is least defensible "
            f"as an estimate, and where the per-segment tables should be read first."
        )


EXPERIMENT = ProjectedMinutes()
