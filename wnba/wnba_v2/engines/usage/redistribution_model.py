"""Phase 3.5 — redistribution usage model.

Same conserved-allocation contract as Phase 3 (renormalize within the active
roster), but each per-share GBM is trained on the role + vacated-by-role + on/off
context features, so it learns who absorbs vacated opportunity instead of spreading
it proportionally.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from wnba_v2.config import RANDOM_SEED
from wnba_v2.engines.usage.features import SHARE_COLS
from wnba_v2.engines.usage.roles import REDIS_FEATURES


@dataclass
class RedistributionUsageModel:
    models: dict = field(default_factory=dict)
    features: list = field(default_factory=lambda: list(REDIS_FEATURES))

    def fit(self, train: pd.DataFrame) -> "RedistributionUsageModel":
        X = train[self.features]
        for share in SHARE_COLS:
            m = HistGradientBoostingRegressor(
                max_depth=4, learning_rate=0.05, max_iter=300,
                l2_regularization=1.0, random_state=RANDOM_SEED)
            m.fit(X, train[share])
            self.models[share] = m
        return self

    def predict_raw(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df[self.features]
        return pd.DataFrame({s: np.clip(self.models[s].predict(X), 0, None) for s in SHARE_COLS},
                            index=df.index)

    def allocate(self, df: pd.DataFrame, raw: pd.DataFrame | None = None) -> pd.DataFrame:
        raw = self.predict_raw(df) if raw is None else raw
        alloc = raw.copy()
        key = df[["game_id", "team"]].copy()
        for s in SHARE_COLS:
            tmp = pd.concat([key, raw[s].rename("v")], axis=1)
            denom = tmp.groupby(["game_id", "team"])["v"].transform("sum").replace(0, np.nan)
            alloc[s] = (tmp["v"] / denom).fillna(0.0).values
        return alloc
