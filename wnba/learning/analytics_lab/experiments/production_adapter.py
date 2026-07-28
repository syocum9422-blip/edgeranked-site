"""Map lab as-of features onto the production model's expected feature names.

The production stat-model bundles (`data/models/wnba_*_model.joblib`) expect the
84 columns from `wnba_model_utils.feature_columns()`. This adapter renames and
derives the lab's as-of columns to match, so those binaries can be scored on
honestly reconstructed historical features.

The binaries are used strictly as **audit artifacts**. They were trained on data
covering the entire replay window, so any absolute accuracy they show here is
in-sample and is not an estimate of live performance. What the comparison *is*
valid for is the relative effect of swapping one input — the `minutes` column —
while everything else, including the model, is held identical.

These are also the *current* binaries. They are the only ones that exist: the
production trainer overwrites in place with no versioning, so no historical
model version can be recovered or claimed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from analytics_lab.config import lab_config as C
else:
    from ..config import lab_config as C

STATS = ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]

# production feature name -> lab as-of column name
DIRECT_RENAMES = {
    "is_home": "is_home",
    "rest_days": "rest_days",
    "is_back_to_back": "is_back_to_back",
    "games_played_season": "games_played_season",
    "minutes_trend_3_over_10": "minutes_trend_3_over_10",
    "team_points_last_10": "team_points_last_10",
    "opp_points_allowed_last_10": "points_allowed_last_10",
    "pace_last_10": "pace_last_10",
    "def_rating_last_10": "def_rating_last_10",
    "off_rating_last_10": "off_rating_last_10",
    "position": "position",
}
for _stat in STATS:
    DIRECT_RENAMES[f"opponent_{_stat}_allowed_last_10"] = f"allowed_{_stat}_last_10"
    DIRECT_RENAMES[f"season_avg_{_stat}"] = f"season_avg_{_stat}"
    DIRECT_RENAMES[f"player_{_stat}_std_10"] = f"{_stat}_std_10"
    DIRECT_RENAMES[f"{_stat}_ewm"] = f"{_stat}_ewm"
    for _window in (3, 5, 10):
        DIRECT_RENAMES[f"{_stat}_rolling_mean_{_window}"] = f"{_stat}_last_{_window}"
        DIRECT_RENAMES[f"{_stat}_rolling_std_{_window}"] = f"{_stat}_std_{_window}"
DIRECT_RENAMES["season_avg_minutes"] = "season_avg_minutes"
DIRECT_RENAMES["player_minutes_std_10"] = "minutes_std_10"


def add_usage_proxy(frame: pd.DataFrame) -> pd.DataFrame:
    """Reproduce the production usage proxy as a leak-safe rolling quantity.

    Production computes the proxy from same-game actuals, then rolls it with
    `shift(1)`. Here the same ratio is formed from already-shifted rolling
    components, so the target game never enters.
    """
    out = frame.copy()
    for window in (5, 10):
        numerator = (
            out[f"points_last_{window}"].fillna(0)
            + 1.2 * out[f"assists_last_{window}"].fillna(0)
            + 0.7 * out[f"rebounds_last_{window}"].fillna(0)
            + 0.6 * out[f"threes_made_last_{window}"].fillna(0)
        )
        out[f"usage_proxy_last_{window}"] = (
            numerator / out[f"minutes_last_{window}"].replace(0, np.nan)
        ).replace([np.inf, -np.inf], np.nan)
    return out


def add_rate_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for stat in STATS:
        out[f"rate_{stat}_last_10"] = (
            out[f"{stat}_last_10"] / out["minutes_last_10"].replace(0, np.nan)
        ).replace([np.inf, -np.inf], np.nan)
    return out


def to_production_frame(asof: pd.DataFrame, minutes_column: str) -> pd.DataFrame:
    """Build a production-shaped feature frame with `minutes` taken from
    ``minutes_column``.

    That column is the single experimental knob: every other input is identical
    across variants, so any metric difference is attributable to it.
    """
    frame = add_rate_features(add_usage_proxy(asof))
    out = pd.DataFrame(index=frame.index)
    for production_name, lab_name in DIRECT_RENAMES.items():
        out[production_name] = frame[lab_name] if lab_name in frame.columns else np.nan
    out["usage_proxy_last_5"] = frame["usage_proxy_last_5"]
    out["usage_proxy_last_10"] = frame["usage_proxy_last_10"]
    for stat in STATS:
        out[f"rate_{stat}_last_10"] = frame[f"rate_{stat}_last_10"]
    out["team"] = frame["team_abbrev"]
    out["opponent"] = frame["opponent_abbrev"]
    out["minutes"] = frame[minutes_column]
    return out


def load_stat_models() -> dict[str, dict]:
    models: dict[str, dict] = {}
    for stat in STATS:
        path = C.PROD_STAT_MODEL_DIR / f"wnba_{stat}_model.joblib"
        if path.exists():
            models[stat] = joblib.load(path)
    return models


def load_minutes_model() -> dict | None:
    return joblib.load(C.PROD_MINUTES_MODEL) if C.PROD_MINUTES_MODEL.exists() else None


def predict(bundle: dict, frame: pd.DataFrame) -> np.ndarray:
    """Ridge+tree ensemble mean, clipped at zero — the production convention."""
    features = frame[bundle["feature_list"]].copy()
    for column in features.columns:
        if features[column].dtype == object:
            features[column] = features[column].astype("string").fillna("UNK")
    ridge = np.clip(bundle["ridge_model"].predict(features), 0, None)
    tree = np.clip(bundle["tree_model"].predict(features), 0, None)
    return np.clip((ridge + tree) / 2.0, 0, None)


def coverage_report(asof: pd.DataFrame) -> pd.DataFrame:
    """Which production features the adapter could and could not supply."""
    frame = add_rate_features(add_usage_proxy(asof))
    rows = []
    bundle = load_stat_models().get("points")
    names = bundle["feature_list"] if bundle else list(DIRECT_RENAMES)
    for name in names:
        if name in {"minutes", "team", "opponent"}:
            rows.append({"production_feature": name, "lab_source": "constructed", "available": True})
            continue
        if name.startswith("usage_proxy") or name.startswith("rate_"):
            rows.append({"production_feature": name, "lab_source": "derived", "available": True})
            continue
        lab = DIRECT_RENAMES.get(name)
        rows.append({
            "production_feature": name,
            "lab_source": lab or "(unmapped)",
            "available": bool(lab and lab in frame.columns),
        })
    return pd.DataFrame(rows)
