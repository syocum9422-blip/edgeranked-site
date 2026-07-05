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
class RollingMinutesMeanModel:
    """Leak-free rolling champion for the minutes mean/p50 anchor.

    This intentionally stays simple: learn convex weights over recent-minute
    baselines, then hard-fallback to the naive mean5 anchor when the row does
    not have enough recent signal for the ensemble to be trustworthy.
    """
    weights: dict = field(default_factory=dict)
    fallback_value: float = 18.0
    feature_medians: dict = field(default_factory=dict)
    baseline_col: str = "min_mean5"
    candidate_cols: tuple = ("min_lag1", "min_mean3", "min_mean5", "min_mean10", "min_ewm")

    def fit(self, train: pd.DataFrame) -> "RollingMinutesMeanModel":
        played = train[train["minutes"] >= 1].sort_values("game_date").copy()
        low_history = self._low_confidence_mask(played)
        low_minutes = played.loc[low_history, "minutes"]
        if len(low_minutes) and low_minutes.notna().any():
            self.fallback_value = float(low_minutes.mean())
        elif self.baseline_col in played and played[self.baseline_col].notna().any():
            self.fallback_value = float(played[self.baseline_col].median())
        else:
            self.fallback_value = 18.0
        self.feature_medians = {
            c: float(played[c].median()) if c in played and played[c].notna().any() else self.fallback_value
            for c in self.candidate_cols
        }

        if len(played) < 200:
            self.weights = {c: float(c == self.baseline_col) for c in self.candidate_cols}
            return self

        split_date = played["game_date"].quantile(0.8)
        valid = played[played["game_date"] > split_date]
        if len(valid) < 50:
            valid = played
        starter_mask = self._starter_proxy(valid)
        naive = self._naive_anchor(valid)
        naive_mae = self._mae(valid["minutes"], naive)
        naive_starter_mae = self._mae(valid.loc[starter_mask, "minutes"], naive[starter_mask])

        best_score = np.inf
        best_weights = None
        grid = np.round(np.arange(0.0, 1.01, 0.1), 1)
        filled = self._filled_candidates(valid)
        for w0 in grid:
            for w1 in grid:
                for w2 in grid:
                    for w3 in grid:
                        w4 = round(1.0 - w0 - w1 - w2 - w3, 10)
                        if w4 < -1e-9 or w4 > 1.0:
                            continue
                        weights = np.array([w0, w1, w2, w3, w4], dtype=float)
                        pred = np.clip(filled.to_numpy() @ weights, 0, 44)
                        pred = self._apply_low_confidence_fallback(valid, pred)
                        mae = self._mae(valid["minutes"], pred)
                        starter_mae = self._mae(valid.loc[starter_mask, "minutes"], pred[starter_mask])
                        if mae <= naive_mae and starter_mae <= naive_starter_mae and mae < best_score:
                            best_score = mae
                            best_weights = weights

        if best_weights is None:
            best_weights = np.array([0.0, 0.0, 1.0, 0.0, 0.0], dtype=float)
        self.weights = {c: float(w) for c, w in zip(self.candidate_cols, best_weights)}
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        filled = self._filled_candidates(df)
        weights = np.array([self.weights.get(c, 0.0) for c in self.candidate_cols], dtype=float)
        if not np.isclose(weights.sum(), 1.0):
            weights = np.array([0.0, 0.0, 1.0, 0.0, 0.0], dtype=float)
        pred = np.clip(filled.to_numpy() @ weights, 0, 44)
        return self._apply_low_confidence_fallback(df, pred)

    def _filled_candidates(self, df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        baseline = self._naive_anchor(df)
        for c in self.candidate_cols:
            if c in df:
                vals = df[c].astype(float).to_numpy()
            else:
                vals = np.full(len(df), np.nan)
            vals = np.where(np.isfinite(vals), vals, baseline)
            vals = np.where(np.isfinite(vals), vals, self.feature_medians.get(c, self.fallback_value))
            out[c] = vals
        return out

    def _naive_anchor(self, df: pd.DataFrame) -> np.ndarray:
        if self.baseline_col in df:
            vals = df[self.baseline_col].astype(float).to_numpy()
        else:
            vals = np.full(len(df), np.nan)
        return np.where(np.isfinite(vals), vals, self.fallback_value)

    def _low_confidence_mask(self, df: pd.DataFrame) -> np.ndarray:
        available = np.zeros(len(df), dtype=int)
        for c in self.candidate_cols:
            if c in df:
                available += df[c].notna().to_numpy(dtype=int)
        low_confidence = available < 2
        if "games_played_season" in df:
            low_confidence |= df["games_played_season"].fillna(0).to_numpy() < 1
        return low_confidence

    def _apply_low_confidence_fallback(self, df: pd.DataFrame, pred: np.ndarray) -> np.ndarray:
        return np.where(self._low_confidence_mask(df), self._naive_anchor(df), pred)

    def _starter_proxy(self, df: pd.DataFrame) -> np.ndarray:
        starter = np.zeros(len(df), dtype=bool)
        if "starter_streak" in df:
            starter |= df["starter_streak"].fillna(0).to_numpy() >= 0.6
        if self.baseline_col in df:
            starter |= df[self.baseline_col].fillna(0).to_numpy() >= 24
        return starter

    @staticmethod
    def _mae(y_true, y_pred) -> float:
        y_arr = np.asarray(y_true, dtype=float)
        p_arr = np.asarray(y_pred, dtype=float)
        if len(y_arr) == 0:
            return 0.0
        return float(np.mean(np.abs(y_arr - p_arr)))


@dataclass
class MinutesModel:
    """Two-stage minutes engine. Stage A gates DNP/garbage; Stage B gives the dist."""
    stage_a: Pipeline | None = None
    stage_b: dict = field(default_factory=dict)   # tau -> Pipeline
    mean_model: RollingMinutesMeanModel | None = None
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
        self.mean_model = RollingMinutesMeanModel().fit(train)
        return self

    # ---- predict ----
    def predict_base_quantiles(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return the unanchored Stage-B quantiles for diagnostics."""
        X = feature_matrix(df)
        preds = {q: np.clip(self.stage_b[q].predict(X), 0, 44) for q in self.quantiles}
        out = pd.DataFrame(preds, index=df.index)
        return pd.DataFrame(np.sort(out.values, axis=1), index=df.index,
                            columns=[f"q{int(q*100)}" for q in self.quantiles])

    def predict_quantiles(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return a frame of minutes quantiles (q10..q90), monotone-sorted, clipped [0,44]."""
        out = self.predict_base_quantiles(df)
        if self.mean_model is not None and "q50" in out:
            champion_p50 = self.mean_model.predict(df)
            shift = champion_p50 - out["q50"].to_numpy()
            for col in out.columns:
                out[col] = np.clip(out[col].to_numpy() + shift, 0, 44)
            out = pd.DataFrame(np.maximum.accumulate(out.values, axis=1), index=df.index, columns=out.columns)
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
