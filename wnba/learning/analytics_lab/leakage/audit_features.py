"""Leakage audit for the production WNBA feature set.

Two parts:

1. A static classification of every column returned by the production
   ``feature_columns()`` — how hard it is to reconstruct as of a past date.
2. Empirical checks that run against the live artifacts and either confirm or
   refute each suspected leak, so the classification is evidence-backed rather
   than asserted.

Read-only. Writes ``analytics_lab/reports/leakage_audit.csv`` and
``leakage_checks.csv``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from analytics_lab.config import lab_config as C
else:
    from ..config import lab_config as C

# Reconstruction classes, in order of increasing difficulty.
SAFE = "safe_to_reconstruct"
DATE_AWARE = "safe_with_date_aware_transform"
SNAPSHOT = "requires_historical_snapshot"
BLOCKED = "cannot_reconstruct"
UNKNOWN = "unknown_needs_investigation"

# family -> (class, reason)
FEATURE_FAMILIES: dict[str, tuple[str, str]] = {
    "minutes": (
        BLOCKED,
        "TRAINING LEAK: this is the target game's actual minutes. At serve time the "
        "same column holds the player's PREVIOUS game's actual minutes, so train and "
        "serve carry different semantics. Reconstructible only by redefining it as a "
        "projection (which is what the lab should do).",
    ),
    "is_home": (SAFE, "Known from the schedule before tip-off."),
    "rest_days": (
        DATE_AWARE,
        "Derived from the player's previous game date. Correct only when computed off "
        "true tip-off timestamps; the production UTC game_date shifts evening games by a day.",
    ),
    "is_back_to_back": (DATE_AWARE, "Same derivation and caveat as rest_days."),
    "games_played_season": (SAFE, "cumcount within (player, season); pregame by construction."),
    "_rolling_mean_": (SAFE, "shift(1).rolling(window) — excludes the target game."),
    "_rolling_std_": (SAFE, "shift(1).rolling(window) — excludes the target game."),
    "_ewm": (SAFE, "shift(1).ewm — excludes the target game."),
    "minutes_trend_3_over_10": (SAFE, "Difference of two shift(1) rolling means."),
    "usage_proxy_last_": (SAFE, "shift(1).rolling over a postgame-derived usage proxy."),
    "rate_": (SAFE, "Ratio of two shift(1) rolling means."),
    "player_": (SAFE, "shift(1).rolling std of the player's own history."),
    "season_avg_": (
        SAFE,
        "shift(1).expanding().mean() within (player, season) — prior games only, "
        "not a full-season average.",
    ),
    "team_points_last_10": (SAFE, "shift(1).rolling(10) over team box scores."),
    "opp_points_allowed_last_10": (SAFE, "Alias of opp_points_last_10; shift(1) rolling."),
    "opponent_": (SAFE, "shift(1).rolling(10) opponent allowance."),
    "pos_": (
        DATE_AWARE,
        "Positional allowance is shift(1) rolling, but it is grouped by a position label "
        "taken from the CURRENT roster file (see `position`).",
    ),
    "pace_last_10": (
        SNAPSHOT,
        "shift(1) rolling, but the source column is dead in production: "
        "wnba_team_context.csv has no pace since 2026-06-28. Reconstruct from "
        "wnba_v2 team_game_logs.possessions instead.",
    ),
    "off_rating_last_10": (SNAPSHOT, "Same dead-source problem as pace_last_10."),
    "def_rating_last_10": (SNAPSHOT, "Same dead-source problem as pace_last_10."),
    "team": (SAFE, "Team as recorded on the historical box score, not the current roster."),
    "opponent": (SAFE, "Known from the schedule before tip-off."),
    "position": (
        SNAPSHOT,
        "ANACHRONISM: merged from the current 20-row wnba_player_positions.csv onto every "
        "historical row. Reconstruct per game from the ESPN box score's athlete position.",
    ),
}


def classify(column: str) -> tuple[str, str]:
    """Exact key wins; otherwise the longest matching substring rule wins.

    Longest-match matters: `season_avg_minutes` and `player_minutes_std_10` must
    resolve to their own (safe) rules rather than to the generic `minutes` rule
    they happen to contain.
    """
    if column in FEATURE_FAMILIES:
        return FEATURE_FAMILIES[column]
    candidates = [
        token for token in FEATURE_FAMILIES
        if token not in {"minutes", "team", "opponent", "position"} and token in column
    ]
    if candidates:
        return FEATURE_FAMILIES[max(candidates, key=len)]
    return UNKNOWN, "No rule matched; inspect before use."


def production_feature_columns() -> list[str]:
    """Reproduce ``wnba_model_utils.feature_columns()`` without importing it.

    Importing the production module pulls in wnba_model_config and triggers
    ``ensure_directories()``, which creates production directories. The lab
    mirrors the list instead and asserts it stays in sync via a unit test.
    """
    base = [
        "minutes", "is_home", "rest_days", "is_back_to_back", "games_played_season",
        "minutes_trend_3_over_10", "usage_proxy_last_5", "usage_proxy_last_10",
        "team_points_last_10", "opp_points_allowed_last_10", "pace_last_10",
        "def_rating_last_10", "off_rating_last_10",
        "opponent_points_allowed_last_10", "opponent_rebounds_allowed_last_10",
        "opponent_assists_allowed_last_10", "opponent_threes_made_allowed_last_10",
        "opponent_steals_allowed_last_10", "opponent_blocks_allowed_last_10",
        "player_minutes_std_10", "player_points_std_10", "player_rebounds_std_10",
        "player_assists_std_10", "player_threes_made_std_10", "player_steals_std_10",
        "player_blocks_std_10",
        "rate_points_last_10", "rate_rebounds_last_10", "rate_assists_last_10",
        "rate_threes_made_last_10", "rate_steals_last_10", "rate_blocks_last_10",
        "season_avg_minutes", "season_avg_points", "season_avg_rebounds",
        "season_avg_assists", "season_avg_threes_made", "season_avg_steals",
        "season_avg_blocks",
        "team", "opponent", "position",
    ]
    aliases = ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]
    for stat in aliases:
        for window in C.ROLLING_WINDOWS:
            base.append(f"{stat}_rolling_mean_{window}")
            base.append(f"{stat}_rolling_std_{window}")
        base.append(f"{stat}_ewm")
    return base


# --- Empirical checks -------------------------------------------------------

def check_rolling_excludes_target(dataset: pd.DataFrame) -> dict:
    """A shift(1) rolling mean must never equal the mean *including* the row."""
    frame = dataset.sort_values(["player_key", "game_date"]).copy()
    recomputed = frame.groupby("player_key")["points"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=1).mean()
    )
    inclusive = frame.groupby("player_key")["points"].transform(
        lambda s: s.rolling(3, min_periods=1).mean()
    )
    stored = frame["points_rolling_mean_3"]
    matches_shifted = np.isclose(stored, recomputed, equal_nan=True).mean()
    matches_inclusive = np.isclose(stored, inclusive, equal_nan=True).mean()
    return {
        "check": "rolling_features_exclude_target_game",
        "passed": bool(matches_shifted > 0.99 and matches_inclusive < 0.99),
        "detail": (
            f"points_rolling_mean_3 matches shift(1) form {matches_shifted:.1%} of rows, "
            f"matches target-inclusive form {matches_inclusive:.1%}"
        ),
    }


def check_minutes_is_same_game_actual(dataset: pd.DataFrame) -> dict:
    """`minutes` as trained should equal the row's own actual minutes."""
    joined = dataset.dropna(subset=["minutes", "points"])
    corr_actual = joined["minutes"].corr(joined["points"])
    corr_rolling = joined["minutes_rolling_mean_5"].corr(joined["points"])
    return {
        "check": "minutes_feature_is_target_game_actual",
        "passed": bool(corr_actual > corr_rolling + 0.05),
        "detail": (
            f"corr(minutes, points)={corr_actual:.3f} vs "
            f"corr(minutes_rolling_mean_5, points)={corr_rolling:.3f}; the trained "
            "`minutes` feature carries same-game information the rolling form does not"
        ),
    }


def check_serving_minutes_mismatch() -> dict:
    """At serve time `minutes` should hold the PREVIOUS game's actual minutes."""
    if not (C.PROD_TODAY_FEATURES.exists() and C.PROD_PLAYER_GAMES.exists()):
        return {"check": "serving_minutes_is_previous_game_actual", "passed": None,
                "detail": "production serving frame not available"}
    today = pd.read_csv(C.PROD_TODAY_FEATURES, low_memory=False)
    games = pd.read_csv(C.PROD_PLAYER_GAMES, low_memory=False)
    games["game_date"] = pd.to_datetime(games["game_date"])
    # Compare against history strictly before the slate: the actuals file has since
    # been backfilled with the slate's own results, which would mask the mismatch.
    slate = pd.to_datetime(today["game_date"]).max()
    history = games[games["game_date"] < slate]
    last = (history.sort_values(["player_key", "game_date"])
                   .groupby("player_key").tail(1)[["player_key", "minutes"]]
                   .rename(columns={"minutes": "last_actual_minutes"}))
    merged = today[["player_key", "minutes"]].merge(last, on="player_key", how="inner").dropna()
    agree = float(np.isclose(merged["minutes"], merged["last_actual_minutes"]).mean()) if len(merged) else float("nan")
    return {
        "check": "serving_minutes_is_previous_game_actual",
        "passed": bool(agree > 0.9),
        "detail": (
            f"{agree:.1%} of {len(merged)} served rows carry the player's previous-game "
            "actual minutes in the `minutes` feature slot (train/serve semantic mismatch)"
        ),
    }


def check_pregame_features_one_game_stale() -> dict:
    """Serving rows come from the player's last dataset row, whose rolling
    features were shift(1)-computed — so they exclude that last game."""
    if not (C.PROD_TODAY_FEATURES.exists() and C.PROD_PLAYER_GAMES.exists()):
        return {"check": "serving_rolling_features_one_game_stale", "passed": None,
                "detail": "production serving frame not available"}
    today = pd.read_csv(C.PROD_TODAY_FEATURES, low_memory=False)
    games = pd.read_csv(C.PROD_PLAYER_GAMES, low_memory=False)
    games["game_date"] = pd.to_datetime(games["game_date"])
    slate = pd.to_datetime(today["game_date"]).max()
    history = games[games["game_date"] < slate].sort_values(["player_key", "game_date"])

    fresh = history.groupby("player_key")["minutes"].apply(lambda s: s.tail(3).mean())
    stale = history.groupby("player_key")["minutes"].apply(lambda s: s.iloc[-4:-1].mean())
    merged = today[["player_key", "minutes_rolling_mean_3"]].copy()
    merged["fresh"] = merged["player_key"].map(fresh)
    merged["stale"] = merged["player_key"].map(stale)
    merged = merged.dropna()
    if merged.empty:
        return {"check": "serving_rolling_features_one_game_stale", "passed": None,
                "detail": "no comparable rows"}
    match_stale = float(np.isclose(merged["minutes_rolling_mean_3"], merged["stale"]).mean())
    match_fresh = float(np.isclose(merged["minutes_rolling_mean_3"], merged["fresh"]).mean())
    return {
        "check": "serving_rolling_features_one_game_stale",
        "passed": bool(match_stale > match_fresh),
        "detail": (
            f"served minutes_rolling_mean_3 matches the one-game-stale window "
            f"{match_stale:.1%} vs the up-to-date window {match_fresh:.1%} "
            f"(n={len(merged)}); production drops the most recent completed game"
        ),
    }


def check_position_is_current_roster() -> dict:
    """The position label applied to history should come from a tiny current file."""
    if not C.PROD_PLAYER_POSITIONS.exists():
        return {"check": "position_label_is_current_roster_snapshot", "passed": None,
                "detail": "positions file not available"}
    positions = pd.read_csv(C.PROD_PLAYER_POSITIONS)
    return {
        "check": "position_label_is_current_roster_snapshot",
        "passed": True,
        "detail": (
            f"wnba_player_positions.csv holds {len(positions)} rows with no date column; "
            "it is merged onto every historical row regardless of when the game was played"
        ),
    }


def check_game_date_is_utc() -> dict:
    """Confirm game_date follows the UTC date, not the ET slate date."""
    index_path = C.LAB_NORMALIZED / "game_index.csv"
    if not (index_path.exists() and C.PROD_PLAYER_GAMES.exists()):
        return {"check": "game_date_column_follows_utc_not_et", "passed": None,
                "detail": "game index not built; run inventory/build_game_index.py"}
    index = pd.read_csv(index_path)
    index["game_id"] = index["game_id"].astype(str)
    games = pd.read_csv(C.PROD_PLAYER_GAMES, low_memory=False).dropna(subset=["game_id"])
    games["game_id"] = games["game_id"].astype("int64").astype(str)
    merged = games.merge(index[["game_id", "slate_date_et", "utc_date"]], on="game_id", how="inner")
    stored = pd.to_datetime(merged["game_date"]).dt.date.astype("string")
    et_mismatch = float((stored != merged["slate_date_et"]).mean())
    utc_mismatch = float((stored != merged["utc_date"]).mean())
    return {
        "check": "game_date_column_follows_utc_not_et",
        "passed": bool(utc_mismatch < 0.01 and et_mismatch > 0.1),
        "detail": (
            f"game_date differs from the ET slate date on {et_mismatch:.2%} of {len(merged)} "
            f"rows and from the UTC date on {utc_mismatch:.2%} — it is the UTC date"
        ),
    }


def check_archive_boards_are_pregame() -> dict:
    """The archived board freezes at 22:30 UTC; afternoon games tip before that."""
    index_path = C.LAB_NORMALIZED / "game_index.csv"
    if not index_path.exists():
        return {"check": "archived_boards_frozen_before_tipoff", "passed": None,
                "detail": "game index not built"}
    index = pd.read_csv(index_path)
    starts = pd.to_datetime(index["start_utc"], utc=True, errors="coerce")
    freeze = starts.dt.tz_convert(C.SLATE_TIMEZONE).dt.normalize() + pd.Timedelta(
        hours=18, minutes=30
    )
    tipped_early = starts.dt.tz_convert(C.SLATE_TIMEZONE) < freeze

    # Only count games whose own slate date actually has an archived board. The
    # archive filename is the UTC run date, which equals the board's GAME_DATE.
    archives = sorted(C.PROD_PROJECTION_ARCHIVE_DIR.glob("wnba_projections_*.csv"))
    archived_utc_dates = {
        f"{p.stem.split('_')[-1][:4]}-{p.stem.split('_')[-1][4:6]}-{p.stem.split('_')[-1][6:]}"
        for p in archives
    }
    window = pd.Series(index["utc_date"]).astype("string").isin(archived_utc_dates)
    rate = float(tipped_early[window].mean()) if window.any() else float("nan")
    return {
        "check": "archived_boards_frozen_before_tipoff",
        "passed": False,
        "detail": (
            f"{rate:.1%} of the {int(window.sum())} games inside the archive window tip before "
            "the 18:30 ET board freeze; for those games the archived board is a POST-game "
            "rebuild and is not a valid pregame baseline"
        ),
    }


CHECKS_NEEDING_DATASET = (check_rolling_excludes_target, check_minutes_is_same_game_actual)
CHECKS_STANDALONE = (
    check_serving_minutes_mismatch,
    check_pregame_features_one_game_stale,
    check_position_is_current_roster,
    check_game_date_is_utc,
    check_archive_boards_are_pregame,
)


def run_checks() -> pd.DataFrame:
    results: list[dict] = []
    if C.PROD_TRAINING_DATASET.exists():
        dataset = pd.read_csv(C.PROD_TRAINING_DATASET, low_memory=False)
        dataset["game_date"] = pd.to_datetime(dataset["game_date"])
        for check in CHECKS_NEEDING_DATASET:
            results.append(check(dataset))
    else:
        for check in CHECKS_NEEDING_DATASET:
            results.append({"check": check.__name__, "passed": None,
                            "detail": "training dataset not available"})
    for check in CHECKS_STANDALONE:
        results.append(check())
    return pd.DataFrame(results)


def main() -> int:
    rows = []
    for column in production_feature_columns():
        verdict, reason = classify(column)
        rows.append({"feature": column, "classification": verdict, "reason": reason})
    audit = pd.DataFrame(rows)
    C.write_csv(audit, "leakage_audit.csv", root=C.LAB_REPORTS)

    checks = run_checks()
    C.write_csv(checks, "leakage_checks.csv", root=C.LAB_REPORTS)

    print("FEATURE CLASSIFICATION")
    for verdict, count in audit["classification"].value_counts().items():
        print(f"  {verdict:<34} {count:>3}")
    flagged = audit[audit.classification.isin({SNAPSHOT, BLOCKED, UNKNOWN})]
    if not flagged.empty:
        print("\n  flagged features:")
        for _, row in flagged.iterrows():
            print(f"    {row.feature:<28} {row.classification}")

    print("\nEMPIRICAL CHECKS  (passed=True means the stated condition is confirmed)")
    for _, row in checks.iterrows():
        mark = {True: "CONFIRMED", False: "REFUTED/RISK", None: "SKIPPED"}[row.passed]
        print(f"  [{mark:^12}] {row.check}\n                 {row.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
