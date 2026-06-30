"""Phase 2 — pace/possession model.

Predicts the game possession total (the shared pace) as a DISTRIBUTION: a mean
(Ridge — pace is near-linear in the two teams' tendencies and the sample is small,
so regularized linear beats trees here) plus a residual std estimated from
walk-forward errors. The Monte Carlo engine (Phase 5) samples one game-pace value
per game and shares it across both teams' players, conserving pace correlation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from wnba_v2.config import RANDOM_SEED


@dataclass
class PaceModel:
    """Pace estimator with two modes:
      - "naive": game pace = mean of the two teams' rolling pace (the OOS winner today)
      - "ridge": learned model (auto-selected once Vegas/more data makes it beat naive)
    train.py picks the mode that wins walk-forward, so the engine self-upgrades."""
    mode: str = "naive"
    features: list = field(default_factory=list)
    pipe: Pipeline | None = None
    resid_std: float = 5.0          # game-possession residual std (set at fit)
    team_split_std: float = 1.5     # home/away per-team deviation from game pace
    naive_col: str = "pace_pair_mean5"

    def fit(self, df: pd.DataFrame, features: list[str], target: str = "target_game_possessions"):
        self.features = features
        fit_df = df[df[target].notna()]
        X, y = fit_df[features], fit_df[target]
        self.pipe = Pipeline([
            ("imp", SimpleImputer(strategy="median")),
            ("sc", StandardScaler()),
            ("reg", Ridge(alpha=5.0, random_state=RANDOM_SEED)),
        ])
        self.pipe.fit(X, y)
        resid = y - self.predict_mean(fit_df)
        self.resid_std = float(np.nanstd(resid))
        return self

    def predict_mean(self, df: pd.DataFrame) -> np.ndarray:
        if self.mode == "naive":
            naive = df[self.naive_col].values.astype(float)
            # fall back to learned model where the anchor is undefined (early season)
            learned = self.pipe.predict(df[self.features])
            return np.where(np.isfinite(naive), naive, learned)
        return self.pipe.predict(df[self.features])

    def sample_game_pace(self, df: pd.DataFrame, n_sims: int, rng: np.random.Generator) -> np.ndarray:
        """Draw n_sims game-possession values per game. Shape (len(df), n_sims).
        Truncated to a plausible WNBA band so tail draws stay realistic."""
        mu = self.predict_mean(df)
        draws = rng.normal(mu[:, None], self.resid_std, size=(len(df), n_sims))
        return np.clip(draws, 65.0, 100.0)
