"""Grade frozen lab projections against actual results.

Takes any long-format projection table (``player_key``, ``stat``,
``projection``, plus a game key) and joins it to actuals from the lab's
normalized history. Works for lab experiments, and for a reconstructed
production baseline, so both are scored by identical code.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from analytics_lab.config import lab_config as C
    from analytics_lab.grading import metrics as M
else:
    from ..config import lab_config as C
    from . import metrics as M

SEGMENTS = ("split", "slate_date_et", "season", "team", "starter", "rest_bucket", "minutes_bucket")


def load_actuals() -> pd.DataFrame:
    """Long-format actuals: one row per (game, player, stat)."""
    path = C.LAB_NORMALIZED / "player_games_indexed.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run replay/build_history.py first")
    frame = pd.read_csv(path, low_memory=False)

    keep = ["game_id", "player_key", "slate_date_et", "start_utc", "team", "opponent", "minutes"]
    for optional in ("season", "starter", "played", "position"):
        if optional in frame.columns:
            keep.append(optional)
    base = frame[keep].copy()

    present = [s for s in C.STAT_TARGETS if s in frame.columns]
    long = frame.melt(
        id_vars=["game_id", "player_key"], value_vars=present,
        var_name="stat", value_name="actual",
    )
    # Combo markets are sums of their components, graded on the same footing.
    for combo, parts in C.COMBO_TARGETS.items():
        if all(p in frame.columns for p in parts):
            summed = frame[["game_id", "player_key"]].copy()
            summed["stat"] = combo
            summed["actual"] = frame[list(parts)].sum(axis=1, min_count=len(parts))
            long = pd.concat([long, summed], ignore_index=True)

    graded = long.merge(base, on=["game_id", "player_key"], how="left")
    graded["game_id"] = graded["game_id"].astype(str)
    return graded


def _bucket(frame: pd.DataFrame) -> pd.DataFrame:
    if "minutes" in frame.columns:
        frame["minutes_bucket"] = pd.cut(
            frame["minutes"], [-0.1, 10, 20, 28, 34, 60],
            labels=["0-10", "10-20", "20-28", "28-34", "34+"],
        )
    if "starter" in frame.columns:
        frame["role"] = frame["starter"].map({1: "starter", 1.0: "starter",
                                              0: "bench", 0.0: "bench"})
    return frame


def grade(projections: pd.DataFrame, label: str = "experiment") -> dict:
    """Join projections to actuals and compute the full metric suite.

    ``projections`` needs ``game_id``, ``player_key``, ``stat``, ``projection``.
    """
    required = {"game_id", "player_key", "stat", "projection"}
    missing = required - set(projections.columns)
    if missing:
        raise ValueError(f"projections missing required columns: {sorted(missing)}")

    projections = projections.copy()
    projections["game_id"] = projections["game_id"].astype(str)
    joined = projections.merge(
        load_actuals(), on=["game_id", "player_key", "stat"], how="left", suffixes=("", "_actual")
    )
    unmatched = int(joined["actual"].isna().sum())
    joined = _bucket(joined)

    report: dict = {
        "label": label,
        "rows_projected": int(len(projections)),
        "rows_graded": int(joined["actual"].notna().sum()),
        "rows_unmatched": unmatched,
        "by_stat": {},
    }
    for stat, group in joined.groupby("stat", observed=True):
        report["by_stat"][stat] = M.point_metrics(group["actual"], group["projection"])

    graded = joined.dropna(subset=["actual"])
    report["segments"] = {}
    for segment in SEGMENTS + ("role",):
        table = M.segment_metrics(graded, segment)
        if not table.empty:
            report["segments"][segment] = json.loads(table.to_json(orient="records"))
    if not graded.empty:
        report["top_n"] = json.loads(M.top_n_metrics(graded).to_json(orient="records"))

    C.write_csv(graded, f"{label}_graded.csv", root=C.LAB_REPORTS)
    target = C.lab_path(f"{label}_grading_report.json", root=C.LAB_REPORTS)
    target.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


def compare(candidate: pd.DataFrame, baseline: pd.DataFrame, label: str = "comparison",
            disagreement_threshold: float = 2.0) -> dict:
    """Score a candidate against a baseline on the identical graded rows."""
    actuals = load_actuals()
    key = ["game_id", "player_key", "stat"]
    for frame in (candidate, baseline):
        frame["game_id"] = frame["game_id"].astype(str)

    merged = (candidate[key + ["projection"]].rename(columns={"projection": "candidate"})
              .merge(baseline[key + ["projection"]].rename(columns={"projection": "baseline"}),
                     on=key, how="inner")
              .merge(actuals, on=key, how="left")
              .dropna(subset=["actual"]))

    report = {"label": label, "rows_compared": int(len(merged)), "by_stat": {}}
    for stat, group in merged.groupby("stat", observed=True):
        report["by_stat"][stat] = {
            "candidate": M.point_metrics(group["actual"], group["candidate"]),
            "baseline": M.point_metrics(group["actual"], group["baseline"]),
            "disagreement": M.disagreement_metrics(
                group, "candidate", "baseline", threshold=disagreement_threshold
            ),
        }
    target = C.lab_path(f"{label}_comparison.json", root=C.LAB_REPORTS)
    target.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report
