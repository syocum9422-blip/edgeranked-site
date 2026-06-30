"""Phase 3 — conserved usage/role allocation model.

Per share: a small GBM predicts each player's RAW share from lagged role form.
The allocation step then renormalizes predictions within the ACTIVE roster so the
team total is exactly 1 — this is what conserves opportunity and, crucially,
redistributes an absent player's share to teammates with no hard-coded boosts.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from wnba_v2.config import RANDOM_SEED
from wnba_v2.engines.usage.features import SHARE_COLS


def _feats(share: str) -> list[str]:
    return [f"{share}_lag5", f"{share}_lag10",
            "minutes_share_lag5", "minutes_share_lag10", "rotation_rank"]


@dataclass
class ConservedUsageModel:
    models: dict = field(default_factory=dict)

    def fit(self, train: pd.DataFrame) -> "ConservedUsageModel":
        for share in SHARE_COLS:
            X = train[_feats(share)]
            y = train[share]
            m = HistGradientBoostingRegressor(
                max_depth=3, learning_rate=0.05, max_iter=200,
                l2_regularization=1.0, random_state=RANDOM_SEED)
            m.fit(X, y)
            self.models[share] = m
        return self

    def predict_raw(self, df: pd.DataFrame) -> pd.DataFrame:
        out = {s: np.clip(self.models[s].predict(df[_feats(s)]), 0, None) for s in SHARE_COLS}
        return pd.DataFrame(out, index=df.index)

    def allocate(self, df: pd.DataFrame, raw: pd.DataFrame | None = None) -> pd.DataFrame:
        """Renormalize raw shares within each (game_id, team) so they sum to 1.
        df is the ACTIVE roster only — absent players excluded => their share flows
        to teammates automatically. Returns allocated shares aligned to df.index."""
        raw = self.predict_raw(df) if raw is None else raw
        alloc = raw.copy()
        key = df[["game_id", "team"]].copy()
        for s in SHARE_COLS:
            tmp = pd.concat([key, raw[s].rename("v")], axis=1)
            denom = tmp.groupby(["game_id", "team"])["v"].transform("sum").replace(0, np.nan)
            alloc[s] = (tmp["v"] / denom).fillna(0.0).values
        return alloc
