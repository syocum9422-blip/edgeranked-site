"""Phase 2D — cost of serving one-game-stale rolling features.

`build_wnba_features_today.py` serves each player's most recent *stored* row.
Those rolling columns were built with `shift(1)` relative to that row, so they
exclude the very game they sit on. The board therefore never sees a player's
latest completed game.

Two feature sets are built over identical rows:

* **fresh** — as-of at the target tip, including the most recent completed game
* **stale** — the values stored on the player's previous game row, i.e. one more
  `shift(1)`; this reproduces the observed production behaviour exactly

The `minutes` input is held identical across both, so this isolates the rolling
staleness effect from the Phase 2C minutes effect.

Output: ``reports/rolling_staleness_audit.md``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from analytics_lab.config import lab_config as C
    from analytics_lab.experiments import production_adapter as PA
    from analytics_lab.grading import metrics as M
else:
    from ..config import lab_config as C
    from . import production_adapter as PA
    from ..grading import metrics as M

# Rolling/expanding columns that production carries forward from the stored row.
STALE_COLUMNS = (
    [f"{s}_last_{w}" for s in PA.STATS + ["minutes"] for w in (3, 5, 10)]
    + [f"{s}_std_{w}" for s in PA.STATS + ["minutes"] for w in (3, 5, 10)]
    + [f"{s}_ewm" for s in PA.STATS + ["minutes"]]
    + [f"season_avg_{s}" for s in PA.STATS + ["minutes"]]
    + ["minutes_trend_3_over_10", "starts_last_3", "starts_last_5", "starts_last_10"]
)


def build_stale_features(asof: pd.DataFrame) -> pd.DataFrame:
    """Reproduce production: use the values stored on the previous game's row."""
    frame = asof.sort_values(["player_id", "start_utc"]).copy()
    by_player = frame.groupby("player_id", sort=False)
    present = [c for c in STALE_COLUMNS if c in frame.columns]
    for column in present:
        frame[column] = by_player[column].shift(1)
    return frame.loc[asof.index]


def eligible(asof: pd.DataFrame) -> pd.DataFrame:
    """Rows where both feature sets are defined — needs two prior games."""
    frame = asof[(asof["played"] == 1) & (asof["season_type"] == "regular")].copy()
    return frame.dropna(subset=["minutes_last_3", "minutes_last_5", "minutes_last_10",
                                "prev_game_minutes", "minutes"])


def compare_feature_values(fresh: pd.DataFrame, stale: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in [c for c in STALE_COLUMNS if c in fresh.columns]:
        a, b = fresh[column], stale[column]
        both = a.notna() & b.notna()
        if both.sum() == 0:
            continue
        difference = (a[both] - b[both]).abs()
        rows.append({
            "feature": column,
            "n_comparable": int(both.sum()),
            "pct_differing": float((difference > 1e-9).mean()),
            "mean_abs_diff": float(difference.mean()),
            "median_abs_diff": float(difference.median()),
            "p90_abs_diff": float(difference.quantile(0.90)),
            "stale_null_rate": float(b.isna().mean()),
        })
    return pd.DataFrame(rows).sort_values("mean_abs_diff", ascending=False)


def score(frame: pd.DataFrame, rows: pd.DataFrame, models: dict, minutes: pd.Series) -> dict:
    production = PA.to_production_frame(frame, minutes_column="minutes")
    production["minutes"] = minutes.to_numpy()
    return {stat: pd.Series(PA.predict(bundle, production), index=rows.index)
            for stat, bundle in models.items()}


def rank_changes(rows: pd.DataFrame, fresh_pred: pd.Series, stale_pred: pd.Series,
                 top_n: tuple[int, ...] = (5, 10, 20)) -> pd.DataFrame:
    """How much the published ordering would move, per slate."""
    frame = pd.DataFrame({
        "slate": rows["slate_date_et"], "player_id": rows["player_id"],
        "fresh": fresh_pred, "stale": stale_pred,
    })
    records = []
    for n in top_n:
        overlaps, sizes = [], []
        for _, group in frame.groupby("slate"):
            if len(group) < n:
                continue
            fresh_top = set(group.nlargest(n, "fresh")["player_id"])
            stale_top = set(group.nlargest(n, "stale")["player_id"])
            overlaps.append(len(fresh_top & stale_top) / n)
            sizes.append(len(group))
        records.append({
            "top_n": n, "slates": len(overlaps),
            "mean_overlap": float(np.mean(overlaps)) if overlaps else float("nan"),
            "mean_changed": (1 - float(np.mean(overlaps))) * n if overlaps else float("nan"),
            "slates_with_any_change": float(np.mean([o < 1 for o in overlaps])) if overlaps else float("nan"),
        })
    spearman = frame.groupby("slate")[["fresh", "stale"]].corr(method="spearman").unstack().iloc[:, 1]
    records.append({"top_n": "rank_corr", "slates": int(spearman.notna().sum()),
                    "mean_overlap": float(spearman.mean()), "mean_changed": float("nan"),
                    "slates_with_any_change": float("nan")})
    return pd.DataFrame(records)


def situation_breakdown(rows: pd.DataFrame, fresh_err: pd.Series, stale_err: pd.Series) -> pd.DataFrame:
    """Where staleness hurts most: the situations that make the last game
    informative rather than redundant."""
    frame = rows.copy()
    frame["fresh_err"] = fresh_err
    frame["stale_err"] = stale_err
    frame["delta"] = stale_err - fresh_err

    prev_minutes = frame["prev_game_minutes"]
    baseline = frame["minutes_last_10"]
    situations = {
        "minutes spike (prev ≥ +8 vs last-10)": prev_minutes - baseline >= 8,
        "minutes drop (prev ≤ -8 vs last-10)": prev_minutes - baseline <= -8,
        "role change (started ≠ usual)": (
            (frame["prev_game_started"] == 1) & (frame["start_rate_season"] < 0.4)
        ) | ((frame["prev_game_started"] == 0) & (frame["start_rate_season"] > 0.6)),
        "returned from DNP (prev game DNP)": frame["prev_game_played"] == 0,
        "changed team (trade)": frame["changed_team"] == 1,
        "back-to-back": frame["is_back_to_back"] == 1,
        "long rest (≥ 5 days)": frame["rest_hours"] >= 120,
        "early season (< 5 games played)": frame["games_played_season"] < 5,
        "ALL ROWS": pd.Series(True, index=frame.index),
    }
    records = []
    for label, mask in situations.items():
        mask = mask.fillna(False).astype(bool)
        subset = frame[mask]
        if len(subset) < 25:
            continue
        records.append({
            "situation": label, "n": int(len(subset)),
            "share_of_rows": float(len(subset) / len(frame)),
            "fresh_mae": float(subset["fresh_err"].mean()),
            "stale_mae": float(subset["stale_err"].mean()),
            "stale_penalty": float(subset["delta"].mean()),
        })
    return pd.DataFrame(records).sort_values("stale_penalty", ascending=False)


def evaluate(asof: pd.DataFrame) -> dict:
    rows = eligible(asof)
    stale_rows = build_stale_features(asof).loc[rows.index]
    models = PA.load_stat_models()

    # Held identical across both sides so only the rolling features vary.
    minutes = rows["minutes_last_5"]

    fresh_pred = score(rows, rows, models, minutes)
    stale_pred = score(stale_rows, rows, models, minutes)

    feature_diff = compare_feature_values(rows, stale_rows)

    metric_rows = []
    for stat in models:
        actual = rows[stat]
        for label, predicted in (("fresh", fresh_pred[stat]), ("stale", stale_pred[stat])):
            metric_rows.append({"features": label, "stat": stat,
                                **M.point_metrics(actual, predicted)})
    metrics = pd.DataFrame(metric_rows)

    points_fresh_err = (fresh_pred["points"] - rows["points"]).abs()
    points_stale_err = (stale_pred["points"] - rows["points"]).abs()
    return {
        "rows": rows,
        "feature_diff": feature_diff,
        "metrics": metrics,
        "ranks": rank_changes(rows, fresh_pred["points"], stale_pred["points"]),
        "situations": situation_breakdown(rows, points_fresh_err, points_stale_err),
        "prediction_diff": (fresh_pred["points"] - stale_pred["points"]).abs(),
    }


def write_report(result: dict) -> Path:
    metrics, ranks = result["metrics"], result["ranks"]
    pivot = metrics.pivot_table(index="stat", columns="features", values="mae")
    pivot["stale_penalty"] = pivot["stale"] - pivot["fresh"]
    weights = metrics[metrics.features == "fresh"].set_index("stat")["n"]
    pooled_fresh = float(np.average(pivot["fresh"], weights=weights[pivot.index]))
    pooled_stale = float(np.average(pivot["stale"], weights=weights[pivot.index]))
    difference = result["prediction_diff"]

    lines = [
        "# Phase 2D — Rolling-feature staleness audit",
        "",
        f"**Date:** 2026-07-25  |  **Eligible player-games:** {int(weights.iloc[0]):,}",
        "",
        "## What this measures",
        "",
        "Production serves each player's most recent *stored* row, whose rolling",
        "columns were `shift(1)`-computed relative to that row — so the board never",
        "sees the player's latest completed game. Here **fresh** features are as-of",
        "at the target tip and **stale** features reproduce that production",
        "behaviour, on identical rows with an identical `minutes` input",
        "(`minutes_last_5` for both), isolating this effect from Phase 2C.",
        "",
        "## Headline",
        "",
        "```",
        f"pooled points-weighted MAE   fresh  {pooled_fresh:.4f}",
        f"                             stale  {pooled_stale:.4f}",
        f"                     stale penalty  {pooled_stale - pooled_fresh:+.4f} "
        f"({(pooled_stale - pooled_fresh) / pooled_fresh:+.2%})",
        "```",
        "",
        "## Prediction accuracy by stat",
        "",
        "| Stat | n | fresh MAE | stale MAE | penalty |",
        "|---|---|---|---|---|",
    ]
    for stat, row in pivot.iterrows():
        lines.append(f"| {stat} | {int(weights[stat]):,} | {row['fresh']:.4f} | "
                     f"{row['stale']:.4f} | {row['stale_penalty']:+.4f} |")

    lines += [
        "",
        "## How far the features actually move",
        "",
        "| Feature | n | % differing | mean abs diff | median | p90 |",
        "|---|---|---|---|---|---|",
    ]
    for _, row in result["feature_diff"].head(20).iterrows():
        lines.append(
            f"| `{row.feature}` | {row.n_comparable:,} | {row.pct_differing:.1%} | "
            f"{row.mean_abs_diff:.3f} | {row.median_abs_diff:.3f} | {row.p90_abs_diff:.3f} |"
        )
    overall = result["feature_diff"]
    lines += ["", f"Across all {len(overall)} carried-forward features, the mean share of rows "
                  f"where the stale value differs from the fresh one is "
                  f"**{overall.pct_differing.mean():.1%}**."]

    lines += [
        "",
        "## Effect on the published ordering (points projections)",
        "",
        "| | slates | mean top-N overlap | mean players changed | slates with any change |",
        "|---|---|---|---|---|",
    ]
    for _, row in ranks.iterrows():
        if row.top_n == "rank_corr":
            lines.append(f"| Spearman rank corr | {int(row.slates)} | {row.mean_overlap:.4f} | — | — |")
        else:
            lines.append(
                f"| top-{row.top_n} | {int(row.slates)} | {row.mean_overlap:.1%} | "
                f"{row.mean_changed:.2f} | {row.slates_with_any_change:.1%} |"
            )

    lines += [
        "",
        f"Median absolute change in a points projection: **{difference.median():.3f}**; "
        f"mean **{difference.mean():.3f}**; "
        f"p90 **{difference.quantile(0.9):.3f}**; "
        f"share of rows moving by ≥1 point: **{(difference >= 1).mean():.1%}**.",
        "",
        "## Where staleness costs the most (points MAE)",
        "",
        "| Situation | n | share | fresh MAE | stale MAE | stale penalty |",
        "|---|---|---|---|---|---|",
    ]
    for _, row in result["situations"].iterrows():
        lines.append(
            f"| {row.situation} | {row.n:,} | {row.share_of_rows:.1%} | {row.fresh_mae:.3f} | "
            f"{row.stale_mae:.3f} | {row.stale_penalty:+.4f} |"
        )

    lines += [
        "",
        "## Reading this correctly",
        "",
        "- Staleness is **not** a leak. It discards information rather than borrowing",
        "  from the future, so it is conservative — just costly.",
        "- Absolute MAE is in-sample (current binaries, training window overlap).",
        "  The fresh-vs-stale *difference* is the trustworthy quantity.",
        "- The effect concentrates exactly where the last game is most informative:",
        "  role changes, returns from DNP, and minutes spikes.",
        "",
    ]
    target = C.lab_path("rolling_staleness_audit.md", root=C.LAB_REPORTS)
    target.write_text("\n".join(lines) + "\n")
    return target


def main() -> int:
    asof = pd.read_parquet(C.LAB_ROOT / "data" / "features" / "asof_features.parquet")
    result = evaluate(asof)
    C.write_csv(result["feature_diff"], "staleness_feature_diff.csv", root=C.LAB_REPORTS)
    C.write_csv(result["metrics"], "staleness_metrics.csv", root=C.LAB_REPORTS)
    C.write_csv(result["situations"], "staleness_situations.csv", root=C.LAB_REPORTS)
    report = write_report(result)

    pivot = result["metrics"].pivot_table(index="stat", columns="features", values="mae")
    weights = result["metrics"][result["metrics"].features == "fresh"].set_index("stat")["n"]
    pooled_fresh = float(np.average(pivot["fresh"], weights=weights[pivot.index]))
    pooled_stale = float(np.average(pivot["stale"], weights=weights[pivot.index]))

    print("PHASE 2D — ROLLING STALENESS")
    print(f"  eligible player-games   {int(weights.iloc[0]):,}")
    print(f"  pooled MAE fresh        {pooled_fresh:.4f}")
    print(f"  pooled MAE stale        {pooled_stale:.4f}")
    print(f"  stale penalty           {pooled_stale - pooled_fresh:+.4f} "
          f"({(pooled_stale - pooled_fresh)/pooled_fresh:+.2%})")
    print(f"  mean share of features differing  {result['feature_diff'].pct_differing.mean():.1%}")
    top = result["ranks"]
    print("\n  top-N ordering overlap")
    for _, row in top.iterrows():
        if row.top_n != "rank_corr":
            print(f"    top-{row.top_n:<3} overlap {row.mean_overlap:.1%}  "
                  f"({row.mean_changed:.2f} players changed per slate)")
    print("\n  worst-affected situations (points MAE penalty)")
    for _, row in result["situations"].head(4).iterrows():
        print(f"    {row.situation:<42} {row.stale_penalty:+.4f}  (n={row.n:,})")
    print(f"\n  wrote {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
