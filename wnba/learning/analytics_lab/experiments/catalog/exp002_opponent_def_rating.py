"""EXP002 — opponent defensive rating vs own-team defensive rating."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from analytics_lab.experiments.framework.base import Experiment, ExperimentContext
from analytics_lab.experiments.framework.manifest import ExperimentManifest


class OpponentDefensiveRating(Experiment):
    """Put the *opponent's* defensive rating in the `def_rating_last_10` slot.

    Despite the name, production fills that slot with the **player's own team's**
    defensive rating. `build_wnba_features_today.latest_team_snapshot()` reads it
    from the team snapshot; the opponent snapshot only carries
    `opponent_*_allowed_*` columns, so the opponent's rating never reaches the
    model. Own-team defensive rating says little about how many points a player
    will score; the opposing defence plausibly says a great deal.
    """

    manifest = ExperimentManifest(
        experiment_id="EXP002",
        title="Opponent defensive rating in the def_rating slot",
        question=(
            "Does supplying the opponent's rolling defensive rating, rather than the "
            "player's own team's, improve prediction accuracy in the model's "
            "`def_rating_last_10` feature?"
        ),
        hypothesis=(
            "Yes, modestly. A player's own team's defensive rating carries almost no "
            "information about her own offensive output, so the slot is close to "
            "wasted; the opposing defence is the quantity the feature name implies "
            "and is genuinely predictive."
        ),
        expected_improvement="0.5-2% pooled MAE reduction on scoring-related stats.",
        features_modified=["def_rating_last_10"],
        description=(
            "`def_rating_last_10` is replaced with `opp_def_rating_last_10` from the "
            "lab's as-of team-context reconstruction — the opposing team's shift(1) "
            "rolling defensive rating over its last 10 completed games. Both series "
            "are built by the same code from the same box scores, so the only change "
            "is whose defence is described."
        ),
        limitations=[
            "The model was fitted with own-team ratings in this slot, so its learned "
            "coefficient reflects that relationship. A slot swap without retraining "
            "understates what a correctly specified feature could contribute.",
            "Both series come from the lab reconstruction, not the production feed, "
            "which has carried no ratings at all since 2026-06-28.",
        ],
        future_work=[
            "Add opponent defensive rating as an additional feature rather than a "
            "substitution, and retrain — the two are not mutually exclusive.",
            "Split by stat: an opposing defence should matter far more for points "
            "than for rebounds or blocks.",
        ],
    )

    def build_variant(self, context: ExperimentContext) -> pd.DataFrame:
        frame = context.baseline_frame.copy()
        asof = context.asof_rows()
        frame["def_rating_last_10"] = asof["opp_def_rating_last_10"].to_numpy()
        return frame

    def interpretation(self, result: dict) -> str:
        asof = result["baseline"].rows
        own = result["baseline"].frame["def_rating_last_10"]
        return (
            "The baseline slot holds the player's own team's defensive rating, which "
            "describes how well *her* team defends — a quantity with no direct bearing "
            "on her own scoring. The variant holds the opposing defence's rating.\n\n"
            f"Baseline slot: mean {own.mean():.2f}, sd {own.std():.2f}, "
            f"{own.isna().mean():.1%} null. If the substitution barely moves error, the "
            "likeliest explanation is not that opponent defence is uninformative but "
            "that the fixed model gives this slot little weight — a hypothesis that "
            "only retraining can separate from the alternative."
        )


EXPERIMENT = OpponentDefensiveRating()
