"""Phase 4 — GBM rate model for high-volume continuous rates.

sklearn HistGradientBoosting quantile regression (LightGBM unavailable in the
venv; HGB quantile is the proven P1/P2 workhorse). Emits mean, variance, and
quantiles so Phase 5 can sample the rate distribution directly via inverse-CDF.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from wnba_v2.config import RANDOM_SEED
from wnba_v2.engines.efficiency.rates import gbm_features

QUANTILES = [0.1, 0.25, 0.5, 0.75, 0.9]
_Z = 2.5631  # q90-q10 spread -> sigma (normal approx)


def _pipe(loss, q=None):
    reg = HistGradientBoostingRegressor(
        loss=loss, quantile=q, max_depth=4, learning_rate=0.05, max_iter=300,
        l2_regularization=1.0, random_state=RANDOM_SEED)
    return Pipeline([("imp", SimpleImputer(strategy="median")), ("reg", reg)])


@dataclass
class RateGBM:
    name: str
    quantiles: list = field(default_factory=lambda: list(QUANTILES))
    qmodels: dict = field(default_factory=dict)

    def fit(self, train: pd.DataFrame) -> "RateGBM":
        feats = gbm_features(self.name)
        X, y = train[feats], train[f"rate_{self.name}"]
        for q in self.quantiles:
            self.qmodels[q] = _pipe("quantile", q).fit(X, y)
        return self

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        feats = gbm_features(self.name)
        X = df[feats]
        qp = {q: np.clip(self.qmodels[q].predict(X), 0, None) for q in self.quantiles}
        out = pd.DataFrame(np.sort(np.column_stack([qp[q] for q in self.quantiles]), axis=1),
                           index=df.index, columns=[f"q{int(q*100)}" for q in self.quantiles])
        out[f"{self.name}_mean"] = out["q50"]
        out[f"{self.name}_std"] = ((out["q90"] - out["q10"]) / _Z).clip(lower=1e-4)
        return out

    def sample(self, df: pd.DataFrame, n_sims: int, rng) -> np.ndarray:
        q = self.predict(df)[[f"q{int(x*100)}" for x in self.quantiles]].values
        taus = np.array([0.0] + self.quantiles + [1.0])
        out = np.zeros((len(df), n_sims))
        for i in range(len(df)):
            grid = np.concatenate([[max(q[i][0] * 0.5, 0)], q[i], [q[i][-1] * 1.5]])
            out[i] = np.interp(rng.random(n_sims), taus, grid)
        return np.clip(out, 0, None)
