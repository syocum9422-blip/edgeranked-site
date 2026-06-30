"""Phase 4 — Bayesian partial-pooling models for low-count / proportion rates.

For steals, blocks (counts per defensive possession) and 3P% (a proportion), raw
per-game rates are dominated by small-sample noise. Empirical-Bayes shrinkage pulls
each player toward a position/league prior by exactly how much evidence they have,
which beats a GBM that chases streaks. Each predict() returns a posterior MEAN and
VARIANCE that Phase 5 samples directly.

  Gamma-Poisson  : steals/blocks rate = (prior_events + k*league) / (prior_opp + k)
  Beta-Binomial  : 3P% = (3pm + a) / (3pa + a + b),  prior from league 3P%
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class GammaPoissonRate:
    """Partial-pooled per-defensive-possession count rate (steals / blocks)."""
    name: str
    num_cum: str          # e.g. "cum_stl"
    den_cum: str = "cum_defposs"
    k: float = 40.0       # prior strength in "possessions" (shrinks rookies/low-sample)
    league_rate_: float = 0.0
    pos_rate_: dict = None

    def fit(self, train: pd.DataFrame) -> "GammaPoissonRate":
        self.league_rate_ = float(train[f"rate_{self.name}"].mean())
        self.pos_rate_ = train.groupby("position")[f"rate_{self.name}"].mean().to_dict()
        return self

    def _prior(self, df: pd.DataFrame) -> np.ndarray:
        return df["position"].map(self.pos_rate_).fillna(self.league_rate_).values

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        prior = self._prior(df)
        ev = df[self.num_cum].fillna(0).values
        opp = df[self.den_cum].fillna(0).values
        post_mean = (ev + self.k * prior) / (opp + self.k)
        # Gamma posterior variance: shape/rate^2 = (ev + k*prior) / (opp + k)^2
        post_var = (ev + self.k * prior) / (opp + self.k) ** 2
        return pd.DataFrame({f"{self.name}_mean": post_mean,
                             f"{self.name}_std": np.sqrt(post_var)}, index=df.index)

    def sample(self, df: pd.DataFrame, n_sims: int, rng) -> np.ndarray:
        prior = self._prior(df)
        shape = df[self.num_cum].fillna(0).values + self.k * prior
        rate = df[self.den_cum].fillna(0).values + self.k
        return rng.gamma(shape[:, None], 1.0 / rate[:, None], size=(len(df), n_sims))


@dataclass
class BetaBinomial3P:
    """Partial-pooled 3P% with a league-prior; shrinkage scales with attempts."""
    prior_strength: float = 30.0   # equivalent prior 3PA
    league_p_: float = 0.33

    def fit(self, train: pd.DataFrame) -> "BetaBinomial3P":
        made = train["fg3m"].sum()
        att = train["fg3a"].sum()
        self.league_p_ = float(made / att) if att > 0 else 0.33
        return self

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        a0 = self.prior_strength * self.league_p_
        b0 = self.prior_strength * (1 - self.league_p_)
        made = df["cum_fg3m"].fillna(0).values
        att = df["cum_fg3a"].fillna(0).values
        a, b = made + a0, (att - made).clip(min=0) + b0
        mean = a / (a + b)
        var = (a * b) / ((a + b) ** 2 * (a + b + 1))
        return pd.DataFrame({"fg3_pct_mean": mean, "fg3_pct_std": np.sqrt(var)}, index=df.index)

    def sample(self, df: pd.DataFrame, n_sims: int, rng) -> np.ndarray:
        a0 = self.prior_strength * self.league_p_
        b0 = self.prior_strength * (1 - self.league_p_)
        made = df["cum_fg3m"].fillna(0).values
        att = df["cum_fg3a"].fillna(0).values
        a, b = made + a0, (att - made).clip(min=0) + b0
        return rng.beta(a[:, None], b[:, None], size=(len(df), n_sims))
