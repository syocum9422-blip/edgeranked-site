"""The production baseline every experiment is measured against.

Per `reports/phase2_baseline_verdict.md` option 3: a **reconstructed
production-logic baseline** — the current production stat-model binaries, fed the
inputs production actually serves.

Two production behaviours are reproduced deliberately, because they are what a
candidate has to beat:

* `minutes` holds the player's **previous game's actual minutes**
  (`simulate_wnba_today.build_projection_rows` never writes `projected_minutes`
  into the stat feature frame)
* rolling features are **one game stale** — production serves the player's last
  stored row, whose rolling columns were `shift(1)`-computed relative to it
* `rest_days` is **differenced from UTC dates**, not tip-off times, then
  `clip(0, 7)` — so an evening-to-evening pair reads one day short and long
  layoffs saturate at 7 (`build_wnba_features_today.py`)

This is not the exact historical production model. The binaries are unversioned
and overwritten in place, so no historical model exists to recover. The honest
label is `reconstructed_production_logic`, which the manifest schema enforces.
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from analytics_lab.config import lab_config as C
from analytics_lab.experiments import production_adapter as PA
from analytics_lab.experiments import rolling_staleness as RS

BASELINE_VERSION = "reconstructed_production_logic_v1"


@dataclass(frozen=True)
class Baseline:
    """Frozen baseline: the rows, the inputs, and the predictions."""

    version: str
    rows: pd.DataFrame               # as-of rows, one per eligible player-game
    frame: pd.DataFrame              # production-shaped feature frame
    predictions: pd.DataFrame        # one column per stat
    model_fingerprint: str
    description: str

    @property
    def n(self) -> int:
        return len(self.rows)


def _fingerprint_models() -> str:
    """Hash the model binaries so a silent retrain invalidates stale results."""
    digest = hashlib.sha256()
    for stat in PA.STATS:
        path = C.PROD_STAT_MODEL_DIR / f"wnba_{stat}_model.joblib"
        digest.update(path.read_bytes() if path.exists() else b"missing")
    return digest.hexdigest()[:16]


def eligible_rows(asof: pd.DataFrame, seasons: list[int] | None = None) -> pd.DataFrame:
    """Rows every experiment shares.

    Restricted to regular-season games the player actually played, with enough
    history for both the fresh and the stale feature sets to be defined. Fixing
    this set once is what makes paired comparison valid — experiments are never
    scored on different samples.
    """
    frame = asof[(asof["played"] == 1) & (asof["season_type"] == "regular")].copy()
    if seasons:
        frame = frame[frame["season"].isin(seasons)]
    required = ["minutes", "prev_game_minutes", "minutes_last_3", "minutes_last_5",
                "minutes_last_10", "minutes_ewm"]
    frame = frame.dropna(subset=required)
    return frame.sort_values(["start_utc", "game_id", "player_id"])


def load_asof() -> pd.DataFrame:
    path = C.LAB_ROOT / "data" / "features" / "asof_features.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run replay/asof_features.py first")
    return pd.read_parquet(path)


def production_rest_days(asof: pd.DataFrame) -> pd.DataFrame:
    """Rest as production computes it: UTC date difference minus one, clipped 0-7.

    `build_wnba_features_today.py` differences the UTC `game_date` column rather
    than tip-off times, so an 8pm-to-8pm pair reads as one day less rest than an
    afternoon-to-afternoon pair of the same real length, and any layoff beyond
    eight days saturates at 7.
    """
    frame = asof.sort_values(["player_id", "start_utc"]).copy()
    utc_date = pd.to_datetime(frame["start_utc"], utc=True).dt.normalize()
    previous = utc_date.groupby(frame["player_id"]).shift(1)
    difference = (utc_date - previous).dt.days
    rest = (difference - 1).fillna(3).clip(lower=0, upper=7)
    out = pd.DataFrame({
        "rest_days_production": rest,
        "is_back_to_back_production": (rest <= 0).astype(int),
    }, index=frame.index)
    return out.loc[asof.index]


def build_baseline(asof: pd.DataFrame | None = None,
                   seasons: list[int] | None = None) -> Baseline:
    asof = load_asof() if asof is None else asof
    rows = eligible_rows(asof, seasons=seasons)

    # Production serves the previous game's stored row, so rolling values are
    # one game stale. Reproduce that on the same index.
    stale = RS.build_stale_features(asof).loc[rows.index]
    frame = PA.to_production_frame(stale, minutes_column="minutes")
    frame["minutes"] = rows["prev_game_minutes"].to_numpy()

    rest = production_rest_days(asof).loc[rows.index]
    frame["rest_days"] = rest["rest_days_production"].to_numpy()
    frame["is_back_to_back"] = rest["is_back_to_back_production"].to_numpy()

    models = PA.load_stat_models()
    if not models:
        raise FileNotFoundError(f"no production stat models in {C.PROD_STAT_MODEL_DIR}")
    predictions = pd.DataFrame(
        {stat: PA.predict(bundle, frame) for stat, bundle in models.items()},
        index=rows.index,
    )
    return Baseline(
        version=BASELINE_VERSION,
        rows=rows,
        frame=frame,
        predictions=predictions,
        model_fingerprint=_fingerprint_models(),
        description=(
            "Current production stat-model binaries fed the inputs production "
            "actually serves: previous-game actual minutes, one-game-stale rolling "
            "features, and UTC-date-differenced rest days clipped to 0-7."
        ),
    )
