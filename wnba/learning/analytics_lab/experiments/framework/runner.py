"""Generic experiment runner. Knows the framework; knows no experiment.

Sequence per run:

    1. load the shared as-of features
    2. build the production baseline (same rows for every experiment)
    3. resolve the requested experiment through the registry
    4. build its variant frame
    5. verify only the declared columns changed          <- single-variable guard
    6. score the variant with the same model binaries
    7. grade both on identical player-games
    8. paired significance testing with Holm correction
    9. write the manifest, artifacts and research report

The runner never promotes anything and never writes outside the lab.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from analytics_lab.config import lab_config as C
from analytics_lab.experiments import production_adapter as PA
from analytics_lab.experiments.framework import baseline as BL
from analytics_lab.experiments.framework import registry, reporting, significance
from analytics_lab.experiments.framework.base import ExperimentContext, assert_single_variable

RUNS_DIR = C.LAB_EXPERIMENTS / "runs"

SEGMENTS = {
    "season": "season",
    "role": "role",
    "minutes_bucket": "minutes_bucket",
    "rest_bucket": "rest_bucket",
}


def _annotate(rows: pd.DataFrame) -> pd.DataFrame:
    frame = rows.copy()
    frame["role"] = np.where(frame["starter"] == 1, "starter", "bench")
    frame["minutes_bucket"] = pd.cut(frame["minutes"], [-0.1, 10, 20, 28, 34, 60],
                                     labels=["0-10", "10-20", "20-28", "28-34", "34+"])
    frame["rest_bucket"] = pd.cut(frame["rest_hours"], [-0.1, 36, 72, 120, 10_000],
                                  labels=["b2b", "2-3d", "4-5d", "6d+"])
    return frame


def _segment_table(rows: pd.DataFrame, actual: pd.DataFrame, base: pd.DataFrame,
                   variant: pd.DataFrame, stats_list: list[str]) -> pd.DataFrame:
    """MAE by segment for both sides, on identical rows within each segment."""
    records = []
    for name, column in SEGMENTS.items():
        if column not in rows.columns:
            continue
        for value, group in rows.groupby(column, observed=True):
            index = group.index
            for stat in stats_list:
                a = actual.loc[index, stat]
                b = (base.loc[index, stat] - a).abs()
                v = (variant.loc[index, stat] - a).abs()
                valid = a.notna()
                if valid.sum() < 25:
                    continue
                records.append({
                    "segment": name, "segment_value": str(value), "stat": stat,
                    "n": int(valid.sum()),
                    "baseline_mae": float(b[valid].mean()),
                    "variant_mae": float(v[valid].mean()),
                    "mae_delta": float(v[valid].mean() - b[valid].mean()),
                })
    return pd.DataFrame(records)


def _top_n_table(rows: pd.DataFrame, actual: pd.DataFrame, base: pd.DataFrame,
                 variant: pd.DataFrame, stats_list: list[str],
                 n_values: tuple[int, ...] = (10, 20)) -> pd.DataFrame:
    """Accuracy among each side's own highest projections, per slate.

    Each side is judged on the rows *it* would have surfaced — that is what a
    reader would actually see — so the row sets differ by construction. This is
    the one table where the samples are intentionally not identical, and it is
    reported separately from the paired tests for that reason.
    """
    records = []
    for n in n_values:
        for stat in stats_list:
            frame = pd.DataFrame({
                "slate": rows["slate_date_et"], "actual": actual[stat],
                "baseline": base[stat], "variant": variant[stat],
            }).dropna()
            for side in ("baseline", "variant"):
                picked = frame.sort_values(side, ascending=False).groupby("slate").head(n)
                error = (picked[side] - picked["actual"]).abs()
                records.append({
                    "top_n": n, "stat": stat, "side": side,
                    "n": int(len(picked)), "mae": float(error.mean()),
                    "mean_actual": float(picked["actual"].mean()),
                    "mean_projected": float(picked[side].mean()),
                })
    return pd.DataFrame(records)


def run(experiment_id: str, seasons: list[int] | None = None,
        shared: tuple[pd.DataFrame, BL.Baseline] | None = None) -> dict:
    asof, base = shared if shared else (BL.load_asof(), None)
    if base is None:
        base = BL.build_baseline(asof, seasons=seasons)

    experiment = registry.get(experiment_id)
    manifest = experiment.manifest
    context = ExperimentContext(asof=asof, baseline=base)

    variant_frame = experiment.build_variant(context)
    changed = assert_single_variable(base.frame, variant_frame, manifest.features_modified)

    models = PA.load_stat_models()
    variant_predictions = pd.DataFrame(
        {stat: PA.predict(bundle, variant_frame) for stat, bundle in models.items()},
        index=base.rows.index,
    )

    rows = _annotate(base.rows)
    actual = rows[manifest.stats]
    per_stat = significance.compare_all(actual, base.predictions, variant_predictions,
                                        manifest.stats)
    pooled = significance.pooled_verdict(per_stat)

    extra_metrics = []
    for stat in manifest.stats:
        a = actual[stat]
        for side, predicted in (("baseline", base.predictions[stat]),
                                ("variant", variant_predictions[stat])):
            error = predicted - a
            valid = a.notna()
            extra_metrics.append({
                "stat": stat, "side": side, "n": int(valid.sum()),
                "mae": float(error[valid].abs().mean()),
                "rmse": float(np.sqrt((error[valid] ** 2).mean())),
                "bias": float(error[valid].mean()),
                "median_abs_error": float(error[valid].abs().median()),
                "correlation": float(a[valid].corr(predicted[valid])),
            })

    result = {
        "manifest": manifest,
        "changed_columns": changed,
        "per_stat": per_stat,
        "pooled": pooled,
        "metrics": pd.DataFrame(extra_metrics),
        "segments": _segment_table(rows, actual, base.predictions, variant_predictions,
                                   manifest.stats),
        "top_n": _top_n_table(rows, actual, base.predictions, variant_predictions,
                              manifest.stats),
        "baseline": base,
        "variant_predictions": variant_predictions,
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _persist(result)
    result["report_path"] = reporting.write_research_report(result, experiment)
    return result


def _persist(result: dict) -> None:
    manifest = result["manifest"]
    experiment_id = manifest.experiment_id
    manifest.status = "complete"
    manifest.result = result["pooled"]["verdict"]

    root = ("runs", experiment_id)
    manifest.write(C.lab_path(*root, "manifest.json", root=C.LAB_EXPERIMENTS))
    for name, frame in (("per_stat.csv", result["per_stat"]),
                        ("metrics.csv", result["metrics"]),
                        ("segments.csv", result["segments"]),
                        ("top_n.csv", result["top_n"])):
        C.write_csv(frame, *root, name, root=C.LAB_EXPERIMENTS)

    summary = {
        "experiment_id": experiment_id,
        "run_utc": result["run_utc"],
        "baseline_version": result["baseline"].version,
        "model_fingerprint": result["baseline"].model_fingerprint,
        "n_player_games": int(result["baseline"].n),
        "changed_columns": result["changed_columns"],
        **result["pooled"],
    }
    path = C.lab_path(*root, "summary.json", root=C.LAB_EXPERIMENTS)
    path.write_text(json.dumps(summary, indent=2, default=str) + "\n")


def run_all(seasons: list[int] | None = None) -> list[dict]:
    """Run the whole catalog against one shared baseline build."""
    asof = BL.load_asof()
    base = BL.build_baseline(asof, seasons=seasons)
    results = []
    for experiment_id in registry.discover():
        print(f"\n=== {experiment_id} ===")
        result = run(experiment_id, shared=(asof, base))
        pooled = result["pooled"]
        print(f"  {result['manifest'].title}")
        print(f"  changed: {result['changed_columns']}")
        print(f"  pooled MAE  baseline {pooled['pooled_baseline_mae']:.4f} -> "
              f"variant {pooled['pooled_variant_mae']:.4f} "
              f"({pooled['pooled_relative_change']:+.2%})")
        print(f"  verdict: {pooled['verdict'].upper()}")
        results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment_id", nargs="?", help="e.g. EXP001; omit to run all")
    parser.add_argument("--list", action="store_true", help="list registered experiments")
    parser.add_argument("--seasons", type=int, nargs="*", default=None)
    arguments = parser.parse_args()

    if arguments.list:
        for experiment_id, experiment in registry.discover().items():
            print(f"{experiment_id}  {experiment.manifest.title}")
            print(f"          {experiment.manifest.question}")
        return 0

    if arguments.experiment_id:
        result = run(arguments.experiment_id, seasons=arguments.seasons)
        pooled = result["pooled"]
        print(f"{arguments.experiment_id}: {pooled['verdict'].upper()}  "
              f"pooled MAE {pooled['pooled_baseline_mae']:.4f} -> "
              f"{pooled['pooled_variant_mae']:.4f} "
              f"({pooled['pooled_relative_change']:+.2%})")
        print(f"report: {result['report_path']}")
    else:
        run_all(seasons=arguments.seasons)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
