"""Research leaderboard and experiment catalog.

Reads the persisted run artifacts, so both documents always reflect what was
actually run rather than what someone remembered running. Sorted by validated
improvement, with unvalidated results ranked below validated ones regardless of
how large their raw MAE change looks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from analytics_lab.config import lab_config as C
from analytics_lab.experiments.framework import registry, significance
from analytics_lab.experiments.framework.manifest import ExperimentManifest

RUNS_DIR = C.LAB_EXPERIMENTS / "runs"

# Validated improvement ranks above anything unvalidated, however large.
VERDICT_ORDER = {
    significance.MEANINGFUL: 0,
    significance.MARGINAL: 1,
    significance.NOT_SIGNIFICANT: 2,
    significance.REGRESSION: 3,
}


def collect() -> pd.DataFrame:
    rows = []
    catalog = registry.discover()
    for experiment_id, experiment in catalog.items():
        manifest = experiment.manifest
        run_dir = RUNS_DIR / experiment_id
        summary_path = run_dir / "summary.json"
        record = {
            "experiment_id": experiment_id,
            "title": manifest.title,
            "question": manifest.question,
            "features_modified": len(manifest.features_modified),
            "status": "not_run",
            "verdict": "pending",
        }
        if summary_path.exists():
            summary = json.loads(summary_path.read_text())
            per_stat = pd.read_csv(run_dir / "per_stat.csv")
            metrics = pd.read_csv(run_dir / "metrics.csv")
            pivot = metrics.pivot_table(index="stat", columns="side", values="rmse")
            weights = metrics[metrics.side == "baseline"].set_index("stat")["n"]
            rmse_baseline = float(np.average(pivot["baseline"], weights=weights[pivot.index]))
            rmse_variant = float(np.average(pivot["variant"], weights=weights[pivot.index]))
            record.update({
                "status": "complete",
                "verdict": summary["verdict"],
                "direction": summary.get("direction", ""),
                "run_utc": summary["run_utc"],
                "n": summary["n_player_games"],
                "baseline_mae": summary["pooled_baseline_mae"],
                "variant_mae": summary["pooled_variant_mae"],
                "mae_change": summary["pooled_variant_mae"] - summary["pooled_baseline_mae"],
                "mae_change_pct": summary["pooled_relative_change"],
                "rmse_change": rmse_variant - rmse_baseline,
                "rmse_change_pct": (rmse_variant - rmse_baseline) / rmse_baseline,
                "stats_meaningful": summary.get("stats_meaningful", 0),
                "stats_regressed": summary.get("stats_regressed", 0),
                "min_holm_p": float(per_stat["holm_p"].min()),
                "model_fingerprint": summary["model_fingerprint"],
            })
        rows.append(record)

    frame = pd.DataFrame(rows)
    frame["_rank"] = frame["verdict"].map(VERDICT_ORDER).fillna(4)
    return (frame.sort_values(["_rank", "mae_change_pct"], na_position="last")
                 .drop(columns="_rank").reset_index(drop=True))


def _note(row: pd.Series) -> str:
    if row["status"] != "complete":
        return "Registered, not yet run."
    if row["verdict"] == significance.MEANINGFUL:
        return (f"Significant and material across {int(row['stats_meaningful'])} stats. "
                "Warrants a dedicated follow-up study.")
    if row["verdict"] == significance.REGRESSION:
        return "Significantly and materially worse. Recorded so it is not retried."
    if row["verdict"] == significance.MARGINAL:
        return (f"Detectable but immaterial ({row['mae_change_pct']:+.2%}); "
                f"directionally {row.get('direction', 'unchanged')}.")
    return "No detectable effect at this sample size."


def write_leaderboard(frame: pd.DataFrame) -> Path:
    complete = frame[frame.status == "complete"]
    lines = [
        "# WNBA Analytics Lab — Research leaderboard",
        "",
        f"**Generated:** {pd.Timestamp.now('UTC').isoformat(timespec='seconds')}  |  "
        f"**Experiments:** {len(frame)} registered, {len(complete)} run",
        "",
        "Sorted by best validated improvement. A validated result outranks an "
        "unvalidated one regardless of raw MAE movement — an unverified 3% is worth "
        "less than a verified 1%.",
        "",
        "All experiments share one baseline (`reconstructed_production_logic_v1`) and "
        "one fixed set of player-games, so the MAE column is directly comparable "
        "across rows.",
        "",
        "| Experiment | Question | Result | MAE Δ | MAE Δ % | RMSE Δ | Status | Notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for _, row in frame.iterrows():
        if row["status"] != "complete":
            lines.append(f"| **{row.experiment_id}** | {row.question} | pending | — | — | — | "
                         f"`not_run` | {_note(row)} |")
            continue
        lines.append(
            f"| **{row.experiment_id}** | {row.question} | `{row.verdict}` | "
            f"{row.mae_change:+.4f} | {row.mae_change_pct:+.2%} | "
            f"{row.rmse_change:+.4f} | `{row.status}` | {_note(row)} |"
        )

    if not complete.empty:
        best = complete.iloc[0]
        lines += [
            "", "## Standing", "",
            f"**Best validated result: {best.experiment_id} — {best.title}** "
            f"({best.mae_change_pct:+.2%} pooled MAE, verdict `{best.verdict}`).",
            "",
            f"Sample: {int(best.n):,} paired player-games, identical across every row "
            "above. Model fingerprint "
            f"`{best.model_fingerprint}` — results are invalidated if the production "
            "binaries are retrained, because the baseline would no longer be the same "
            "model.",
            "",
            "## Verdict counts", "",
            "| Verdict | Experiments |", "|---|---|",
        ]
        for verdict, count in complete["verdict"].value_counts().items():
            lines.append(f"| `{verdict}` | {count} |")

    lines += [
        "", "## How to read this", "",
        "- **Negative MAE Δ favours the variant.**",
        "- `meaningful` requires statistical significance (Wilcoxon signed-rank, "
        f"Holm-corrected, α = {significance.ALPHA}) **and** a relative MAE change of at "
        f"least {significance.PRACTICAL_THRESHOLD:.0%}. `regression` requires the same two "
        "conditions in the opposite direction.",
        "- `marginal` means exactly one of those two bars was cleared. At ~14k paired "
        "rows almost any change is statistically significant, so `marginal` is the "
        "common landing place and is not a finding.",
        "- **Nothing here is a deployment recommendation.** Promotion is a separate "
        "human decision made with `promotion/PROMOTION_REPORT_TEMPLATE.md`.",
        "",
    ]
    target = C.lab_path("research_leaderboard.md", root=C.LAB_REPORTS)
    target.write_text("\n".join(lines) + "\n")
    return target


def write_catalog(frame: pd.DataFrame) -> Path:
    catalog = registry.discover()
    lines = [
        "# WNBA Analytics Lab — Experiment catalog",
        "",
        f"**Generated:** {pd.Timestamp.now('UTC').isoformat(timespec='seconds')}  |  "
        f"**Registered experiments:** {len(catalog)}",
        "",
        "Every experiment is a plug-in module under `experiments/catalog/` exposing a "
        "module-level `EXPERIMENT`. The runner discovers them; it imports none of them "
        "by name. Adding a research question means adding one file.",
        "",
    ]
    lookup = frame.set_index("experiment_id")
    for experiment_id, experiment in catalog.items():
        manifest: ExperimentManifest = experiment.manifest
        row = lookup.loc[experiment_id]
        lines += [
            f"## {experiment_id} — {manifest.title}",
            "",
            f"**Question.** {manifest.question}",
            "",
            f"**Hypothesis.** {manifest.hypothesis}",
            "",
            f"**Expected improvement.** {manifest.expected_improvement}",
            "",
            f"**Features modified** ({len(manifest.features_modified)}): "
            + ", ".join(f"`{c}`" for c in manifest.features_modified[:6])
            + (" …" if len(manifest.features_modified) > 6 else ""),
            "",
            f"**Seasons.** {', '.join(str(s) for s in manifest.seasons)}  |  "
            f"**Stats.** {', '.join(manifest.stats)}",
            "",
        ]
        if row["status"] == "complete":
            lines += [
                f"**Sample.** {int(row['n']):,} paired player-games",
                "",
                f"**Result.** pooled MAE {row['baseline_mae']:.4f} → "
                f"{row['variant_mae']:.4f} ({row['mae_change_pct']:+.2%}), "
                f"RMSE {row['rmse_change_pct']:+.2%}, min Holm p = {row['min_holm_p']:.2e}",
                "",
                f"**Verdict.** `{row['verdict']}` — {_note(row)}",
                "",
                f"**Report.** [`experiments/{experiment_id.lower()}_research_report.md`]"
                f"(experiments/{experiment_id.lower()}_research_report.md)",
                "",
            ]
        else:
            lines += ["**Status.** Registered, not yet run.", ""]
        if manifest.limitations:
            lines += ["**Known limitations.**", ""]
            lines += [f"- {item}" for item in manifest.limitations]
            lines.append("")
        lines.append("---")
        lines.append("")
    target = C.lab_path("experiment_catalog.md", root=C.LAB_REPORTS)
    target.write_text("\n".join(lines) + "\n")
    return target


def main() -> int:
    frame = collect()
    C.write_csv(frame, "leaderboard.csv", root=C.LAB_DATA / "baselines")
    leaderboard = write_leaderboard(frame)
    catalog = write_catalog(frame)

    print("ANALYTICS LAB LEADERBOARD")
    for _, row in frame.iterrows():
        if row["status"] != "complete":
            print(f"  {row.experiment_id}  {'not run':<16}")
            continue
        print(f"  {row.experiment_id}  {row.verdict:<16} "
              f"MAE {row.mae_change:+.4f} ({row.mae_change_pct:+.2%})  "
              f"RMSE {row.rmse_change:+.4f}  {row.title}")
    print(f"\nwrote {leaderboard}")
    print(f"wrote {catalog}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
