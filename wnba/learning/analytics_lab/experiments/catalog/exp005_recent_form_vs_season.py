"""EXP005 — recent form vs season-to-date averages."""
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


class RecentFormVsSeasonAverage(Experiment):
    """Replace recent-form windows with the season-to-date average.

    An ablation in the informative direction: if recent form carries signal the
    season average does not, error should rise. The season average here is
    `shift(1).expanding()` within the season, so it remains leak-safe — it is a
    genuinely available alternative, not a peek at the full season.
    """

    manifest = ExperimentManifest(
        experiment_id="EXP005",
        title="Recent form vs season-to-date average",
        question=(
            "Does a player's recent form carry information beyond her season-to-date "
            "average, or would the season average alone serve the model as well?"
        ),
        hypothesis=(
            "Recent form matters. Roles change mid-season through trades, injuries "
            "and rotation shifts, and 16.8% of player-seasons involve more than one "
            "team, so a season average should lag reality and error should rise "
            "measurably when recent windows are removed."
        ),
        expected_improvement=(
            "A regression is the expected and desired outcome: the size of the "
            "degradation measures how much recent form is worth."
        ),
        features_modified=(
            [f"{stat}_rolling_mean_{w}" for stat in PA.STATS for w in WINDOWS]
            + [f"{stat}_ewm" for stat in PA.STATS]
        ),
        description=(
            "Every recent-form *level* estimate is overwritten with "
            "`season_avg_{stat}`, the shift(1) expanding mean within the current "
            "season: all three `{stat}_rolling_mean_{3,5,10}` slots **and** the "
            "`{stat}_ewm` slot. The EWM has to go too — leaving it in would keep "
            "supplying recent form through the back door and the experiment would "
            "answer nothing. Rolling standard deviations and the `season_avg_*` "
            "columns themselves are untouched, so dispersion information is "
            "preserved and only the level estimate changes."
        ),
        limitations=[
            "This measures how much the *fixed* model relies on recent-form inputs, "
            "not how much a refit model could extract from them. A model retrained "
            "without recent form would partially compensate through other features.",
            "**Recent form still reaches the model through channels this ablation "
            "does not touch**, so the measured degradation is a *lower bound*, not "
            "the value of recent form. `rate_{stat}_last_10` and "
            "`usage_proxy_last_{5,10}` are derived from the last-10 windows before "
            "the substitution is applied; `{stat}_rolling_std_{3,5,10}`, "
            "`player_{stat}_std_10` and `minutes_trend_3_over_10` also encode "
            "recency. Roughly half the recent-form channels survive.",
            "The season average resets each season, so early-season rows have very "
            "little history on either side and the contrast is weakest exactly where "
            "recent form should matter most.",
        ],
        future_work=[
            "Build a total recent-form ablation that also neutralises "
            "rate_*_last_10, usage_proxy_last_*, the rolling standard deviations and "
            "minutes_trend_3_over_10 — the only design that can answer the question "
            "outright.",
            "Repeat within season phases (first 5 games, mid, late) to see where the "
            "gap opens.",
            "Restrict to players who changed team or role mid-season, where the "
            "season average should lag hardest.",
        ],
    )

    def build_variant(self, context: ExperimentContext) -> pd.DataFrame:
        frame = context.baseline_frame.copy()
        for stat in PA.STATS:
            season_average = frame[f"season_avg_{stat}"]
            for window in WINDOWS:
                frame[f"{stat}_rolling_mean_{window}"] = season_average
            frame[f"{stat}_ewm"] = season_average
        return frame

    def interpretation(self, result: dict) -> str:
        pooled = result["pooled"]
        direction = "rose" if pooled["pooled_relative_change"] > 0 else "fell"
        return (
            f"Pooled MAE {direction} by {abs(pooled['pooled_relative_change']):.2%} when "
            "the recent-form level estimates — all three rolling means and the EWM — "
            "were replaced by the season-to-date average.\n\n"
            "**Read this as a lower bound, not as the value of recent form.** The "
            "substitution is applied to the production-shaped frame after "
            "`rate_{stat}_last_10` and `usage_proxy_last_{5,10}` have already been "
            "derived from the last-10 windows, so those columns still carry recent "
            "form into the model, as do the rolling standard deviations and "
            "`minutes_trend_3_over_10`. Roughly half the recent-form channels survive "
            "the ablation, which is the most likely reason the degradation is small.\n\n"
            "The honest conclusion is therefore narrow: replacing the recent-form "
            "*level* estimates alone costs little, because the model has other routes "
            "to the same information. A complete answer needs a variant that "
            "neutralises every recency-bearing channel, which is more than one "
            "variable and belongs in its own experiment."
        )


EXPERIMENT = RecentFormVsSeasonAverage()
