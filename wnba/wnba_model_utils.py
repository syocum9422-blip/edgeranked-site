from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from scipy.stats import truncnorm
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, RobustScaler

from wnba_model_config import (
    ARCHIVE_DIR,
    BEST_BETS_DIR,
    BEST_BETS_ARCHIVE_DIR_DATED,
    CANONICAL_PLAYER_GAMES_PATH,
    CANONICAL_PLAYER_POSITIONS_PATH,
    CANONICAL_PLAYER_STATUS_PATH,
    CANONICAL_SCHEDULE_TODAY_PATH,
    CANONICAL_SPORTSBOOK_LINES_PATH,
    CANONICAL_TEAM_CONTEXT_PATH,
    LOGS_DIR,
    MODELS_DIR,
    PROJECTIONS_ARCHIVE_DIR,
    RANDOM_SEED,
    ROLLING_WINDOWS,
    STAT_ALIASES,
    STAT_MODEL_TEMPLATE,
    TODAY_OVERRIDE,
)


LOGGER_NAME = "wnba_model"


def setup_logging(script_name: str) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = logging.FileHandler(LOGS_DIR / f"{script_name}.log")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def ensure_directories() -> None:
    for path in [LOGS_DIR, MODELS_DIR, BEST_BETS_DIR, ARCHIVE_DIR, PROJECTIONS_ARCHIVE_DIR, BEST_BETS_ARCHIVE_DIR_DATED]:
        path.mkdir(parents=True, exist_ok=True)


def today_timestamp() -> pd.Timestamp:
    return pd.Timestamp(TODAY_OVERRIDE).normalize() if TODAY_OVERRIDE else pd.Timestamp.today().normalize()


def safe_read_csv(path: Path, required: bool = False, logger: Optional[logging.Logger] = None) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    if required:
        message = f"Required file not found: {path}"
        if logger:
            logger.error(message)
        raise FileNotFoundError(message)
    if logger:
        logger.warning("Optional file missing: %s", path)
    return pd.DataFrame()


def canonicalize_name(value: object) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value).replace(".", " ").replace(",", " ").lower().split())


def standardize_team_abbrev(value: object) -> str:
    if pd.isna(value):
        return ""
    mapping = {
        "las": "LVA",
        "lv": "LVA",
        "veg": "LVA",
        "pho": "PHX",
        "phx": "PHX",
        "ny": "NYL",
        "nyl": "NYL",
        "conn": "CON",
        "ct": "CON",
        "wash": "WAS",
        "gs": "GSV",
        "gsv": "GSV",
        "la": "LAS",
        "chi": "CHI",
        "dal": "DAL",
        "ind": "IND",
        "min": "MIN",
        "sea": "SEA",
        "atl": "ATL",
    }
    token = str(value).upper().strip()
    return mapping.get(token.lower(), token)


def _find_first_column(columns: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    lowered = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def _rename_if_present(df: pd.DataFrame, mapping: Dict[str, List[str]]) -> pd.DataFrame:
    rename_map: Dict[str, str] = {}
    for canonical_name, candidates in mapping.items():
        source = _find_first_column(df.columns, candidates)
        if source and source != canonical_name:
            rename_map[source] = canonical_name
    return df.rename(columns=rename_map)


def normalize_player_games(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    mapping = {
        "game_date": ["game_date", "date", "gameDate", "GAME_DATE"],
        "season": ["season", "year", "SEASON"],
        "player_name": ["player_name", "player", "PLAYER_NAME", "name"],
        "team": ["team", "team_abbrev", "TEAM_ABBREVIATION", "TEAM"],
        "opponent": ["opponent", "opp", "OPPONENT", "OPP"],
        "home_away": ["home_away", "venue", "HOME_AWAY"],
        "minutes": ["minutes", "min", "MIN"],
        "points": ["points", "pts", "PTS"],
        "rebounds": ["rebounds", "reb", "REB"],
        "assists": ["assists", "ast", "AST"],
        "threes_made": ["threes_made", "fg3m", "FG3M", "3pm", "3PM"],
        "steals": ["steals", "stl", "STL"],
        "blocks": ["blocks", "blk", "BLK"],
        "turnovers": ["turnovers", "tov", "TOV"],
        "fga": ["fga", "FGA"],
        "fgm": ["fgm", "FGM"],
        "fta": ["fta", "FTA"],
        "ftm": ["ftm", "FTM"],
        "offensive_rebounds": ["offensive_rebounds", "oreb", "OREB"],
        "defensive_rebounds": ["defensive_rebounds", "dreb", "DREB"],
        "plus_minus": ["plus_minus", "PLUS_MINUS"],
    }
    df = _rename_if_present(df, mapping)

    required = ["game_date", "player_name", "team", "opponent", "minutes"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Player game logs missing columns: {missing}")

    for column in ["points", "rebounds", "assists", "threes_made", "steals", "blocks", "turnovers", "fga", "fgm", "fta", "ftm", "offensive_rebounds", "defensive_rebounds", "plus_minus"]:
        if column not in df.columns:
            df[column] = np.nan

    df["game_date"] = pd.to_datetime(df["game_date"]).dt.normalize()
    df["player_name"] = df["player_name"].astype(str).str.strip()
    df["player_key"] = df["player_name"].map(canonicalize_name)
    df["team"] = df["team"].map(standardize_team_abbrev)
    df["opponent"] = df["opponent"].map(standardize_team_abbrev)
    df["home_away"] = df.get("home_away", "A").astype(str).str.upper().str[0]
    df["is_home"] = (df["home_away"] == "H").astype(int)

    numeric_cols = [
        "minutes",
        "points",
        "rebounds",
        "assists",
        "threes_made",
        "steals",
        "blocks",
        "turnovers",
        "fga",
        "fgm",
        "fta",
        "ftm",
        "offensive_rebounds",
        "defensive_rebounds",
        "plus_minus",
    ]
    for column in numeric_cols:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if "season" not in df.columns:
        df["season"] = df["game_date"].dt.year

    df = df.sort_values(["player_key", "game_date"]).reset_index(drop=True)
    return df


def normalize_team_context(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    mapping = {
        "game_date": ["game_date", "date", "GAME_DATE"],
        "team": ["team", "team_abbrev", "TEAM"],
        "opponent": ["opponent", "opp", "OPPONENT"],
        "pace": ["pace", "PACE"],
        "off_rating": ["off_rating", "ortg", "OFF_RATING"],
        "def_rating": ["def_rating", "drtg", "DEF_RATING"],
        "team_points": ["team_points", "pts", "TEAM_POINTS"],
        "opp_points": ["opp_points", "opp_pts", "OPP_POINTS"],
        "team_rebounds": ["team_rebounds", "reb", "TEAM_REBOUNDS"],
        "team_assists": ["team_assists", "ast", "TEAM_ASSISTS"],
        "team_threes_made": ["team_threes_made", "fg3m", "TEAM_THREES_MADE"],
    }
    df = _rename_if_present(df, mapping)
    if "game_date" not in df.columns or "team" not in df.columns:
        raise ValueError("Team context file must include game_date and team columns.")

    df["game_date"] = pd.to_datetime(df["game_date"]).dt.normalize()
    df["team"] = df["team"].map(standardize_team_abbrev)
    if "opponent" in df.columns:
        df["opponent"] = df["opponent"].map(standardize_team_abbrev)
    for column in ["pace", "off_rating", "def_rating", "team_points", "opp_points", "team_rebounds", "team_assists", "team_threes_made"]:
        if column not in df.columns:
            df[column] = np.nan
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.sort_values(["team", "game_date"]).reset_index(drop=True)


def normalize_schedule(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    mapping = {
        "game_date": ["game_date", "date", "GAME_DATE"],
        "home_team": ["home_team", "home", "HOME_TEAM"],
        "away_team": ["away_team", "away", "AWAY_TEAM"],
        "game_id": ["game_id", "GAME_ID"],
        "start_time": ["start_time", "tipoff", "START_TIME"],
    }
    df = _rename_if_present(df, mapping)
    required = ["game_date", "home_team", "away_team"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Today schedule missing columns: {missing}")

    df["game_date"] = pd.to_datetime(df["game_date"]).dt.normalize()
    df["home_team"] = df["home_team"].map(standardize_team_abbrev)
    df["away_team"] = df["away_team"].map(standardize_team_abbrev)
    if "game_id" not in df.columns:
        df["game_id"] = (
            df["game_date"].dt.strftime("%Y%m%d")
            + "_"
            + df["away_team"].astype(str)
            + "_"
            + df["home_team"].astype(str)
        )
    return (
        df.drop_duplicates(subset=["game_date", "away_team", "home_team", "game_id"])
        .sort_values(["game_date", "away_team", "home_team"])
        .reset_index(drop=True)
    )


def normalize_positions(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mapping = {
        "player_name": ["player_name", "player", "PLAYER_NAME", "name"],
        "position": ["position", "pos", "POSITION"],
        "team": ["team", "team_abbrev", "TEAM"],
    }
    df = _rename_if_present(df, mapping)
    if "player_name" not in df.columns:
        raise ValueError("Player positions file must include player_name.")
    df["player_name"] = df["player_name"].astype(str).str.strip()
    df["player_key"] = df["player_name"].map(canonicalize_name)
    df["position"] = df.get("position", "UNK").fillna("UNK").astype(str).str.upper()
    if "team" in df.columns:
        df["team"] = df["team"].map(standardize_team_abbrev)
    return df.drop_duplicates("player_key").reset_index(drop=True)


def normalize_player_status(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mapping = {
        "player_name": ["player_name", "player", "PLAYER_NAME"],
        "status": ["status", "injury_status", "STATUS"],
        "team": ["team", "team_abbrev", "TEAM"],
    }
    df = _rename_if_present(df, mapping)
    if "player_name" not in df.columns:
        raise ValueError("Player status file must include player_name.")
    df["player_name"] = df["player_name"].astype(str).str.strip()
    df["player_key"] = df["player_name"].map(canonicalize_name)
    df["status"] = df.get("status", "available").fillna("available").astype(str).str.lower()
    if "team" in df.columns:
        df["team"] = df["team"].map(standardize_team_abbrev)
    return df.drop_duplicates("player_key").reset_index(drop=True)


def normalize_sportsbook_lines(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mapping = {
        "player_name": ["player_name", "player", "PLAYER_NAME"],
        "team": ["team", "team_abbrev", "TEAM"],
        "opponent": ["opponent", "opp", "OPPONENT"],
        "stat": ["stat", "market", "STAT"],
        "line": ["line", "prop_line", "LINE"],
        "over_odds": ["over_odds", "over_price", "OVER_ODDS"],
        "under_odds": ["under_odds", "under_price", "UNDER_ODDS"],
        "sportsbook": ["sportsbook", "book", "SPORTSBOOK"],
    }
    df = _rename_if_present(df, mapping)
    required = ["player_name", "stat", "line"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Sportsbook lines missing columns: {missing}")
    df["player_name"] = df["player_name"].astype(str).str.strip()
    df["player_key"] = df["player_name"].map(canonicalize_name)
    if "team" in df.columns:
        df["team"] = df["team"].map(standardize_team_abbrev)
    if "opponent" in df.columns:
        df["opponent"] = df["opponent"].map(standardize_team_abbrev)
    df["stat"] = (
        df["stat"]
        .astype(str)
        .str.strip()
        .str.lower()
        .replace(
            {
                "pts": "points",
                "reb": "rebounds",
                "ast": "assists",
                "3pm": "threes_made",
                "fg3m": "threes_made",
                "stl": "steals",
                "blk": "blocks",
            }
        )
    )
    df["line"] = pd.to_numeric(df["line"], errors="coerce")
    for column in ["over_odds", "under_odds"]:
        if column not in df.columns:
            df[column] = np.nan
        df[column] = pd.to_numeric(df[column], errors="coerce")
    if "sportsbook" not in df.columns:
        df["sportsbook"] = "unknown"
    return df.dropna(subset=["line"]).reset_index(drop=True)


def load_canonical_inputs(logger: Optional[logging.Logger] = None) -> Dict[str, pd.DataFrame]:
    return {
        "player_games": safe_read_csv(CANONICAL_PLAYER_GAMES_PATH, required=True, logger=logger),
        "team_context": safe_read_csv(CANONICAL_TEAM_CONTEXT_PATH, required=False, logger=logger),
        "schedule_today": safe_read_csv(CANONICAL_SCHEDULE_TODAY_PATH, required=False, logger=logger),
        "sportsbook_lines": safe_read_csv(CANONICAL_SPORTSBOOK_LINES_PATH, required=False, logger=logger),
        "player_positions": safe_read_csv(CANONICAL_PLAYER_POSITIONS_PATH, required=False, logger=logger),
        "player_status": safe_read_csv(CANONICAL_PLAYER_STATUS_PATH, required=False, logger=logger),
    }


def feature_columns() -> List[str]:
    base = [
        "minutes",
        "is_home",
        "rest_days",
        "is_back_to_back",
        "games_played_season",
        "minutes_trend_3_over_10",
        "usage_proxy_last_5",
        "usage_proxy_last_10",
        "team_points_last_10",
        "opp_points_allowed_last_10",
        "pace_last_10",
        "def_rating_last_10",
        "off_rating_last_10",
        "opponent_points_allowed_last_10",
        "opponent_rebounds_allowed_last_10",
        "opponent_assists_allowed_last_10",
        "opponent_threes_made_allowed_last_10",
        "opponent_steals_allowed_last_10",
        "opponent_blocks_allowed_last_10",
        "player_minutes_std_10",
        "player_points_std_10",
        "player_rebounds_std_10",
        "player_assists_std_10",
        "player_threes_made_std_10",
        "player_steals_std_10",
        "player_blocks_std_10",
        "rate_points_last_10",
        "rate_rebounds_last_10",
        "rate_assists_last_10",
        "rate_threes_made_last_10",
        "rate_steals_last_10",
        "rate_blocks_last_10",
        "season_avg_minutes",
        "season_avg_points",
        "season_avg_rebounds",
        "season_avg_assists",
        "season_avg_threes_made",
        "season_avg_steals",
        "season_avg_blocks",
        "team",
        "opponent",
        "position",
    ]
    for stat in STAT_ALIASES:
        for window in ROLLING_WINDOWS:
            base.append(f"{stat}_rolling_mean_{window}")
            base.append(f"{stat}_rolling_std_{window}")
        base.append(f"{stat}_ewm")
    return base


def build_regression_pipeline(feature_frame: pd.DataFrame) -> Tuple[Pipeline, Pipeline, List[str], List[str]]:
    categorical = [column for column in feature_frame.columns if not pd.api.types.is_numeric_dtype(feature_frame[column])]
    numeric = [column for column in feature_frame.columns if column not in categorical]

    linear_preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", RobustScaler())]), numeric),
            ("categorical", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("encoder", OneHotEncoder(handle_unknown="ignore"))]), categorical),
        ]
    )
    tree_preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", SimpleImputer(strategy="median"), numeric),
            ("categorical", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("encoder", OneHotEncoder(handle_unknown="ignore"))]), categorical),
        ]
    )

    ridge_model = Pipeline(
        steps=[
            ("preprocessor", linear_preprocessor),
            ("model", Ridge(alpha=10.0, solver="lsqr")),
        ]
    )
    tree_model = Pipeline(
        steps=[
            ("preprocessor", tree_preprocessor),
            ("model", HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=250, random_state=RANDOM_SEED)),
        ]
    )
    return ridge_model, tree_model, numeric, categorical


def clean_feature_frame(frame: pd.DataFrame, feature_list: List[str]) -> pd.DataFrame:
    cleaned = frame[feature_list].copy()
    for column in cleaned.columns:
        if pd.api.types.is_numeric_dtype(cleaned[column]):
            cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")
            cleaned[column] = cleaned[column].replace([np.inf, -np.inf], np.nan)
            cleaned[column] = cleaned[column].clip(lower=-1e6, upper=1e6)
        else:
            cleaned[column] = cleaned[column].astype(str).replace({"nan": np.nan})
    return cleaned


def train_ensemble_models(
    data: pd.DataFrame,
    target: str,
    feature_list: List[str],
    logger: logging.Logger,
) -> Dict[str, object]:
    model_data = data.dropna(subset=[target]).copy()
    if model_data.empty:
        raise ValueError(f"No training rows available for target: {target}")

    split_date = model_data["game_date"].quantile(0.8)
    train_df = model_data[model_data["game_date"] <= split_date].copy()
    valid_df = model_data[model_data["game_date"] > split_date].copy()
    if valid_df.empty:
        valid_df = train_df.tail(max(1, len(train_df) // 5)).copy()
        train_df = train_df.iloc[:-len(valid_df)].copy()
    if train_df.empty or valid_df.empty:
        raise ValueError(f"Unable to create train/validation split for {target}.")

    X_train = clean_feature_frame(train_df, feature_list)
    y_train = train_df[target]
    X_valid = clean_feature_frame(valid_df, feature_list)
    y_valid = valid_df[target]

    ridge_model, tree_model, _, _ = build_regression_pipeline(X_train)
    ridge_model.fit(X_train, y_train)
    tree_model.fit(X_train, y_train)

    ridge_pred = np.clip(ridge_model.predict(X_valid), 0, None)
    tree_pred = np.clip(tree_model.predict(X_valid), 0, None)
    ensemble_pred = np.clip((ridge_pred + tree_pred) / 2.0, 0, None)

    metrics = {
        "target": target,
        "train_rows": int(len(train_df)),
        "valid_rows": int(len(valid_df)),
        "mae": float(mean_absolute_error(y_valid, ensemble_pred)),
        "rmse": float(math.sqrt(mean_squared_error(y_valid, ensemble_pred))),
        "r2": float(r2_score(y_valid, ensemble_pred)),
        "ridge_mae": float(mean_absolute_error(y_valid, ridge_pred)),
        "tree_mae": float(mean_absolute_error(y_valid, tree_pred)),
    }
    logger.info(
        "Trained %s models | train_rows=%s | valid_rows=%s | mae=%.3f | rmse=%.3f",
        target,
        metrics["train_rows"],
        metrics["valid_rows"],
        metrics["mae"],
        metrics["rmse"],
    )
    return {
        "ridge_model": ridge_model,
        "tree_model": tree_model,
        "feature_list": feature_list,
        "metrics": metrics,
    }


def save_model_bundle(bundle: Dict[str, object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, output_path)


def load_model_bundle(path: Path) -> Dict[str, object]:
    return joblib.load(path)


def archive_dataframe(df: pd.DataFrame, output_dir: Path, stem: str, date_value: Optional[pd.Timestamp] = None) -> Path:
    ensure_directories()
    archive_date = (date_value or today_timestamp()).strftime("%Y%m%d")
    archive_path = output_dir / f"{stem}_{archive_date}.csv"
    df.to_csv(archive_path, index=False)
    return archive_path


def confidence_to_score(value: str) -> int:
    mapping = {"high": 3, "medium": 2, "low": 1}
    return mapping.get(str(value).lower(), 0)


def model_output_path(stat: str) -> Path:
    return path_from_template(STAT_MODEL_TEMPLATE.format(stat=stat))


def path_from_template(filename: str) -> Path:
    from wnba_model_config import MODELS_DIR

    return MODELS_DIR / filename


def american_odds_to_implied_probability(odds: float) -> float:
    if pd.isna(odds):
        return np.nan
    odds = float(odds)
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def compute_confidence_label(row: pd.Series) -> str:
    stability = row.get("minutes_stability_score", 0.0)
    volatility = row.get("composite_volatility", 0.0)
    agreement = row.get("model_agreement_score", 0.0)
    score = 0.45 * stability + 0.35 * agreement + 0.20 * max(0.0, 1.0 - volatility)
    if score >= 0.70:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def compute_minutes_distribution(projected_minutes: float, minutes_std: float, size: int, rng: np.random.Generator) -> np.ndarray:
    projected_minutes = max(float(projected_minutes), 1.0)
    minutes_std = max(float(minutes_std), 2.0)
    low = (0 - projected_minutes) / minutes_std
    high = (40 - projected_minutes) / minutes_std
    return truncnorm.rvs(low, high, loc=projected_minutes, scale=minutes_std, size=size, random_state=rng)


def gamma_sample(mean: float, std: float, size: int, rng: np.random.Generator) -> np.ndarray:
    mean = max(float(mean), 0.01)
    std = max(float(std), 0.05)
    variance = std ** 2
    shape = max((mean ** 2) / variance, 1e-3)
    scale = max(variance / mean, 1e-3)
    return rng.gamma(shape=shape, scale=scale, size=size)


def safe_last(series: pd.Series, default: float = 0.0) -> float:
    series = series.dropna()
    if series.empty:
        return default
    return float(series.iloc[-1])


def add_group_rolling_features(df: pd.DataFrame, group_col: str, value_cols: List[str]) -> pd.DataFrame:
    frame = df.sort_values([group_col, "game_date"]).copy()
    for value_col in value_cols:
        for window in ROLLING_WINDOWS:
            frame[f"{value_col}_rolling_mean_{window}"] = (
                frame.groupby(group_col)[value_col].transform(lambda s: s.shift(1).rolling(window, min_periods=1).mean())
            )
            frame[f"{value_col}_rolling_std_{window}"] = (
                frame.groupby(group_col)[value_col].transform(lambda s: s.shift(1).rolling(window, min_periods=2).std())
            )
        frame[f"{value_col}_ewm"] = (
            frame.groupby(group_col)[value_col].transform(lambda s: s.shift(1).ewm(alpha=0.35, adjust=False).mean())
        )
    return frame


def load_inputs_for_pipeline(logger: logging.Logger) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    games = normalize_player_games(safe_read_csv(CANONICAL_PLAYER_GAMES_PATH, required=True, logger=logger))
    team_context = normalize_team_context(safe_read_csv(CANONICAL_TEAM_CONTEXT_PATH, required=False, logger=logger))
    schedule_today = normalize_schedule(safe_read_csv(CANONICAL_SCHEDULE_TODAY_PATH, required=False, logger=logger))
    sportsbook_lines = normalize_sportsbook_lines(safe_read_csv(CANONICAL_SPORTSBOOK_LINES_PATH, required=False, logger=logger))
    positions = normalize_positions(safe_read_csv(CANONICAL_PLAYER_POSITIONS_PATH, required=False, logger=logger))
    status = normalize_player_status(safe_read_csv(CANONICAL_PLAYER_STATUS_PATH, required=False, logger=logger))
    return games, team_context, schedule_today, sportsbook_lines, positions, status
