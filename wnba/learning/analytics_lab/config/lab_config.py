"""WNBA Analytics Lab — paths, isolation contract, and write guards.

The lab is READ-ONLY with respect to every production artifact. It reads the
live pipeline's canonical inputs and archived outputs, and writes *only* under
``analytics_lab/``. ``lab_path()`` is the single sanctioned way to build an
output path; it raises if the target escapes the lab.

Nothing in this package may import a production module that performs work at
import time (``simulate_wnba_today``, ``build_wnba_features_today``,
``fetch_wnba_data``, ``build_wnba_best_bets``). Those modules read/write
production CSVs and hit the network. Reimplement the logic here instead.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Roots ------------------------------------------------------------------
LAB_ROOT = Path(__file__).resolve().parents[1]
LEARNING_ROOT = LAB_ROOT.parent
WNBA_ROOT = LEARNING_ROOT.parent
V2_ROOT = WNBA_ROOT / "wnba_v2"

# --- Lab-owned output areas (the ONLY writable locations) -------------------
LAB_DATA = LAB_ROOT / "data"
LAB_RAW = LAB_DATA / "raw"
LAB_NORMALIZED = LAB_DATA / "normalized"
LAB_FEATURES = LAB_DATA / "features"
LAB_ACTUALS = LAB_DATA / "actuals"
LAB_BASELINES = LAB_DATA / "baselines"
LAB_REPORTS = LAB_ROOT / "reports"
LAB_EXPERIMENTS = LAB_ROOT / "experiments"
LAB_PROMOTION = LAB_ROOT / "promotion"

WRITABLE_ROOTS = (LAB_DATA, LAB_REPORTS, LAB_EXPERIMENTS, LAB_PROMOTION)

# --- Production sources (READ-ONLY) -----------------------------------------
# Canonical live-pipeline inputs.
PROD_PLAYER_GAMES = WNBA_ROOT / "data" / "raw" / "wnba_player_games.csv"
PROD_TEAM_CONTEXT = WNBA_ROOT / "data" / "raw" / "wnba_team_context.csv"
PROD_PLAYER_STATUS = WNBA_ROOT / "data" / "raw" / "wnba_player_status.csv"
PROD_PLAYER_POSITIONS = WNBA_ROOT / "data" / "raw" / "wnba_player_positions.csv"
PROD_SPORTSBOOK_LINES = WNBA_ROOT / "data" / "raw" / "wnba_sportsbook_lines.csv"
PROD_LINE_SNAPSHOT_DIR = WNBA_ROOT / "data" / "raw" / "line_snapshots"

# Live-pipeline derived artifacts.
PROD_TRAINING_DATASET = WNBA_ROOT / "data" / "processed" / "wnba_training_dataset.csv"
PROD_TODAY_FEATURES = WNBA_ROOT / "data" / "processed" / "wnba_today_features.csv"
PROD_STAT_MODEL_DIR = WNBA_ROOT / "data" / "models"
PROD_MINUTES_MODEL = WNBA_ROOT / "models" / "wnba_minutes_model.joblib"

# Frozen historical production output (the exact-snapshot baseline candidate).
PROD_PROJECTION_ARCHIVE_DIR = WNBA_ROOT / "outputs" / "archive" / "projections"
PROD_BEST_BETS_ARCHIVE_DIR = WNBA_ROOT / "outputs" / "archive" / "best_bets"
PROD_GRADED_LEDGER = LEARNING_ROOT / "graded_predictions_ledger.csv"

# Engine V2 data assets (read-only; richer than the production canonical files).
V2_PLAYER_BOXSCORES = V2_ROOT / "data" / "team_games" / "player_boxscores.csv"
V2_TEAM_GAME_LOGS = V2_ROOT / "data" / "team_games" / "team_game_logs.csv"
V2_ESPN_CACHE_DIR = V2_ROOT / "data" / "team_games" / "_cache"
V2_PROP_OPEN_CLOSE = V2_ROOT / "data" / "line_history" / "prop_open_close.csv"
V2_GAME_OPEN_CLOSE = V2_ROOT / "data" / "line_history" / "game_open_close.csv"

# Any path under these roots is production and must never be written by the lab.
FORBIDDEN_WRITE_ROOTS = (
    WNBA_ROOT / "data",
    WNBA_ROOT / "models",
    WNBA_ROOT / "outputs",
    WNBA_ROOT / "Best_Bets",
    WNBA_ROOT / "logs",
    V2_ROOT,
    Path("/home/ubuntu/edgeranked-sportsai"),
    Path("/home/ubuntu/EdgeRanked/site"),
    Path("/srv"),
)

# --- Replay / analysis conventions ------------------------------------------
# The live pipeline stores ``game_date`` as the game's **UTC** date (verified:
# 0.00% mismatch vs UTC date, 46.63% vs America/New_York date). The lab keys
# every chronological operation off the exact tip-off timestamp instead.
SLATE_TIMEZONE = "America/New_York"
GAME_DATE_CONVENTION = "utc_date"

# The production board archived under ``wnba_projections_YYYYMMDD.csv`` is
# written by the 22:30 UTC pipeline run (18:30 America/New_York).
ARCHIVE_FREEZE_UTC_HOUR = 22
ARCHIVE_FREEZE_UTC_MINUTE = 30

STAT_TARGETS = ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]
COMBO_TARGETS = {"pra": ("points", "rebounds", "assists"),
                 "pr": ("points", "rebounds"),
                 "pa": ("points", "assists"),
                 "ra": ("rebounds", "assists")}
ROLLING_WINDOWS = (3, 5, 10)
RANDOM_SEED = 42


class LabPathViolation(RuntimeError):
    """Raised when the lab is asked to write outside its own directory."""


def _resolve(path: os.PathLike[str] | str) -> Path:
    return Path(path).expanduser().resolve()


def is_lab_path(path: os.PathLike[str] | str) -> bool:
    """True only if ``path`` lives under a lab-owned writable root."""
    candidate = _resolve(path)
    for root in WRITABLE_ROOTS:
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            continue
        return True
    return False


def assert_lab_path(path: os.PathLike[str] | str) -> Path:
    """Return ``path`` if it is a legal lab output, else raise.

    Checked before every write in the lab. Rejects production paths even when
    they are reached through ``..`` traversal or a symlink, because the check
    runs on the fully resolved path.
    """
    candidate = _resolve(path)
    for root in FORBIDDEN_WRITE_ROOTS:
        try:
            candidate.relative_to(_resolve(root))
        except ValueError:
            continue
        raise LabPathViolation(
            f"refusing to write to production path {candidate} (under {root})"
        )
    if not is_lab_path(candidate):
        raise LabPathViolation(
            f"{candidate} is outside the analytics lab; lab writes must live under {LAB_ROOT}"
        )
    return candidate


def lab_path(*parts: str, root: Path = LAB_DATA) -> Path:
    """Build a guarded lab output path and create its parent directory."""
    target = assert_lab_path(root.joinpath(*parts))
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def write_csv(frame, *parts: str, root: Path = LAB_DATA, **kwargs) -> Path:
    """``DataFrame.to_csv`` that cannot escape the lab."""
    target = lab_path(*parts, root=root)
    kwargs.setdefault("index", False)
    frame.to_csv(target, **kwargs)
    return target
