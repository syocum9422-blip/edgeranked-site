"""Phase 1 — Minutes engine models.

Stage A: P(meaningful minutes | appears)  -> HistGradientBoostingClassifier
Stage B: minutes quantile distribution    -> HistGradientBoostingRegressor(loss="quantile")
         fit at tau in {.1,.25,.5,.75,.9}, monotonically sorted at predict time.

Native sklearn quantile loss = no new dependency vs the prod stack. The output is a
full per-player minutes distribution the Monte Carlo engine (Phase 5) will sample.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder

from wnba_v2.config import RANDOM_SEED
from wnba_v2.engines.minutes.features import (
    ALL_FEATURES,
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    feature_matrix,
)

QUANTILES = [0.1, 0.25, 0.5, 0.75, 0.9]


def _ord_pre() -> ColumnTransformer:
    """Ordinal-encode categoricals; pass numerics through (HGB handles NaN natively)."""
    return ColumnTransformer(
        [("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
          CATEGORICAL_FEATURES)],
        remainder="passthrough",
    )


@dataclass
class MinutesModel:
    """Two-stage minutes engine. Stage A gates DNP/garbage; Stage B gives the dist."""
    stage_a: Pipeline | None = None
    stage_b: dict = field(default_factory=dict)   # tau -> Pipeline
    quantiles: list = field(default_factory=lambda: list(QUANTILES))

    # ---- fit ----
    def fit(self, train: pd.DataFrame) -> "MinutesModel":
        X = feature_matrix(train)
        # Stage A on ALL rows (target = meaningful minutes).
        self.stage_a = Pipeline([
            ("pre", _ord_pre()),
            ("clf", HistGradientBoostingClassifier(
                max_depth=4, learning_rate=0.05, max_iter=300,
                l2_regularization=1.0, random_state=RANDOM_SEED)),
        ])
        self.stage_a.fit(X, train["y_meaningful"])

        # Stage B on appearance rows only (minutes >= 1): model the played distribution.
        played = train[train["minutes"] >= 1]
        Xb = feature_matrix(played)
        yb = played["y_minutes"]
        self.stage_b = {}
        for q in self.quantiles:
            pipe = Pipeline([
                ("pre", _ord_pre()),
                ("reg", HistGradientBoostingRegressor(
                    loss="quantile", quantile=q,
                    max_depth=4, learning_rate=0.05, max_iter=300,
                    l2_regularization=1.0, random_state=RANDOM_SEED)),
            ])
            pipe.fit(Xb, yb)
            self.stage_b[q] = pipe
        return self

    # ---- predict ----
    def predict_quantiles(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return a frame of minutes quantiles (q10..q90), monotone-sorted, clipped [0,44]."""
        X = feature_matrix(df)
        preds = {q: np.clip(self.stage_b[q].predict(X), 0, 44) for q in self.quantiles}
        out = pd.DataFrame(preds, index=df.index)
        out = pd.DataFrame(np.sort(out.values, axis=1), index=df.index,
                           columns=[f"q{int(q*100)}" for q in self.quantiles])
        return out

    def predict_play_prob(self, df: pd.DataFrame) -> np.ndarray:
        return self.stage_a.predict_proba(feature_matrix(df))[:, 1]

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        q = self.predict_quantiles(df)
        q["play_prob"] = self.predict_play_prob(df)
        q["minutes_p50"] = q["q50"]
        return q

    # ---- sampling for Monte Carlo (Phase 5 will call this) ----
    def sample(self, df: pd.DataFrame, n_sims: int, rng: np.random.Generator) -> np.ndarray:
        """Draw n_sims minutes per row via inverse-CDF interp of the predicted quantiles,
        gated by a Bernoulli play draw and a low-minutes garbage component.
        Returns array shape (len(df), n_sims)."""
        q = self.predict_quantiles(df).values            # (N, 5)
        pp = self.predict_play_prob(df)                   # (N,)
        taus = np.array([0.0] + self.quantiles + [1.0])
        out = np.zeros((len(df), n_sims))
        for i in range(len(df)):
            qs = q[i]
            grid = np.concatenate([[max(qs[0] - 4, 0)], qs, [min(qs[-1] + 5, 44)]])
            u = rng.random(n_sims)
            mins = np.interp(u, taus, grid)
            plays = rng.random(n_sims) < pp[i]            # Stage A gate
            out[i] = np.where(plays, mins, 0.0)
        return np.clip(out, 0, 44)
