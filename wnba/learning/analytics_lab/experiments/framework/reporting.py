"""Research report generation.

These are research documents, not deployment reports. They describe what was
asked, what was measured and what it does and does not license — they never
recommend a production change. Promotion is a separate, human decision made with
the Phase 1 promotion template.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from analytics_lab.config import lab_config as C
from analytics_lab.experiments.framework import significance

VERDICT_PROSE = {
    significance.MEANINGFUL: (
        "**Meaningful.** The change is statistically significant after Holm "
        "correction *and* clears the practical threshold. Worth a dedicated "
        "follow-up study before anyone discusses production."
    ),
    significance.MARGINAL: (
        "**Marginal.** Either statistically detectable but too small to matter, or "
        "large enough to matter but not statistically distinguishable. Not a "
        "finding on its own — check the direction below before reading anything "
        "into it."
    ),
    significance.NOT_SIGNIFICANT: (
        "**Not significant.** No detectable effect at this sample size. A useful "
        "negative result: it rules the idea out at the magnitudes this study can see."
    ),
    significance.REGRESSION: (
        "**Regression.** The variant is significantly worse than the baseline. "
        "Recording it prevents the idea being retried."
    ),
}


def _verdict_bar(table: pd.DataFrame) -> str:
    counts = table["verdict"].value_counts()
    return ", ".join(f"{count} {name}" for name, count in counts.items()) or "none"


def write_research_report(result: dict, experiment) -> Path:
    manifest = result["manifest"]
    pooled = result["pooled"]
    per_stat = result["per_stat"]
    metrics = result["metrics"]
    baseline = result["baseline"]

    lines = [
        f"# {manifest.experiment_id} — {manifest.title}",
        "",
        f"**Run:** {result['run_utc']}  |  **Author:** {manifest.author}  |  "
        f"**Status:** {manifest.status}",
        f"**Baseline:** `{baseline.version}` (`{manifest.baseline_kind}`)  |  "
        f"**Model fingerprint:** `{baseline.model_fingerprint}`",
        "",
        "## Executive summary",
        "",
        f"**Question.** {manifest.question}",
        "",
        f"**Result.** Pooled MAE moves from **{pooled['pooled_baseline_mae']:.4f}** "
        f"(baseline) to **{pooled['pooled_variant_mae']:.4f}** (variant), "
        f"**{pooled['pooled_relative_change']:+.2%}**, across "
        f"{int(per_stat['n'].max()):,} paired player-games and "
        f"{len(per_stat)} stat categories.",
        "",
        VERDICT_PROSE[pooled["verdict"]],
        "",
        f"Direction: the variant is **{pooled['direction']}** than the baseline overall. "
        f"Per-stat verdicts: {_verdict_bar(per_stat)}.",
        "",
        "## Question",
        "",
        manifest.question,
        "",
        f"**Hypothesis.** {manifest.hypothesis}",
        "",
        f"**Expected improvement.** {manifest.expected_improvement}",
        "",
        f"**Feature(s) modified.** " + ", ".join(f"`{c}`" for c in manifest.features_modified),
        "",
        f"**Columns the run verified as changed.** "
        + (", ".join(f"`{c}`" for c in result["changed_columns"]) or "none"),
        "",
        "## Method",
        "",
        f"{baseline.description}",
        "",
        "The variant frame is identical to the baseline frame except in the declared",
        "columns; the runner aborts if any other column moves. Both sides are scored",
        "with the same production model binaries on the same player-games, so every",
        "comparison below is paired.",
        "",
        f"{manifest.description}".strip(),
        "",
        "**Statistics.** Wilcoxon signed-rank on paired absolute errors, Holm-corrected",
        f"across the {len(per_stat)} stats, α = {significance.ALPHA}. Practical threshold",
        f"= {significance.PRACTICAL_THRESHOLD:.0%} relative MAE change. A verdict of",
        "*meaningful* requires both. 95% bootstrap CI on the mean paired difference",
        f"({significance.BOOTSTRAP_SAMPLES:,} resamples, seed {significance.RANDOM_SEED}).",
        "",
        "## Sample",
        "",
        f"- **Player-games:** {baseline.n:,} (identical for baseline and variant)",
        f"- **Seasons:** {', '.join(str(s) for s in sorted(baseline.rows['season'].unique()))}",
        f"- **Date range:** {baseline.rows.slate_date_et.min()} → {baseline.rows.slate_date_et.max()}",
        f"- **Distinct players:** {baseline.rows.player_id.nunique():,}  |  "
        f"**games:** {baseline.rows.game_id.nunique():,}  |  "
        f"**slates:** {baseline.rows.slate_date_et.nunique():,}",
        "",
        "Regular-season games the player actually played, with enough history for both",
        "feature sets to be defined. Preseason and DNPs are excluded.",
        "",
        "## Results",
        "",
        "### Paired comparison by stat",
        "",
        "| Stat | n | baseline MAE | variant MAE | Δ MAE | rel. | 95% CI | Holm p | d | variant wins | verdict |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for _, row in per_stat.iterrows():
        lines.append(
            f"| {row.stat} | {int(row.n):,} | {row.baseline_mae:.4f} | {row.variant_mae:.4f} | "
            f"{row.mae_delta:+.4f} | {row.relative_change:+.2%} | "
            f"[{row.ci_low:+.4f}, {row.ci_high:+.4f}] | {row.holm_p:.2e} | "
            f"{row.cohens_d:+.3f} | {row.variant_win_rate:.1%} | `{row.verdict}` |"
        )
    lines += ["", "Negative Δ favours the variant. A CI spanning zero means the paired",
              "difference is not distinguishable from no change."]

    lines += ["", "### Full metric set", "",
              "| Stat | Side | n | MAE | RMSE | Bias | Median abs err | Correlation |",
              "|---|---|---|---|---|---|---|---|"]
    for _, row in metrics.sort_values(["stat", "side"]).iterrows():
        lines.append(
            f"| {row.stat} | {row.side} | {int(row.n):,} | {row.mae:.4f} | {row.rmse:.4f} | "
            f"{row.bias:+.4f} | {row.median_abs_error:.4f} | {row.correlation:.4f} |"
        )

    top_n = result["top_n"]
    if not top_n.empty:
        lines += ["", "### Top-ranked projections", "",
                  "Each side judged on the rows *it* would have surfaced, so the two row",
                  "sets differ by construction. Reported separately from the paired tests",
                  "for that reason.", "",
                  "| Top-N | Stat | baseline MAE | variant MAE | Δ |", "|---|---|---|---|---|"]
        pivot = top_n.pivot_table(index=["top_n", "stat"], columns="side", values="mae")
        for (n, stat), row in pivot.iterrows():
            lines.append(f"| {n} | {stat} | {row['baseline']:.4f} | {row['variant']:.4f} | "
                         f"{row['variant'] - row['baseline']:+.4f} |")

    segments = result["segments"]
    if not segments.empty:
        for name, title in (("season", "By season"), ("role", "By player role"),
                            ("minutes_bucket", "By expected-minutes bucket"),
                            ("rest_bucket", "By rest status")):
            block = segments[segments.segment == name]
            if block.empty:
                continue
            pooled_block = block.groupby("segment_value", observed=True).apply(
                lambda g: pd.Series({
                    "n": g["n"].sum(),
                    "baseline_mae": np.average(g["baseline_mae"], weights=g["n"]),
                    "variant_mae": np.average(g["variant_mae"], weights=g["n"]),
                }), include_groups=False)
            pooled_block["delta"] = pooled_block["variant_mae"] - pooled_block["baseline_mae"]
            lines += ["", f"### {title} (all stats pooled)", "",
                      "| Segment | n | baseline MAE | variant MAE | Δ |", "|---|---|---|---|---|"]
            for value, row in pooled_block.iterrows():
                lines.append(f"| {value} | {int(row['n']):,} | {row['baseline_mae']:.4f} | "
                             f"{row['variant_mae']:.4f} | {row['delta']:+.4f} |")

    extra = experiment.interpretation(result)
    lines += ["", "## Interpretation", ""]
    lines.append(extra.strip() if extra.strip() else
                 "No experiment-specific interpretation was supplied; the tables above stand alone.")

    lines += ["", "## Limitations", "",
              "Framework-wide, applying to every experiment in this catalog:", "",
              "- **No retraining.** The production binaries are held fixed, so this measures",
              "  how the *deployed* model responds to a different input construction — not",
              "  the value that feature would have in a refit model. A feature the current",
              "  model cannot exploit may still be valuable after retraining.",
              "- **In-sample.** The binaries were trained on data covering this window, so",
              "  absolute MAE is optimistic. Only the paired *difference* is trustworthy.",
              "- **Not the historical production model.** Binaries are unversioned and",
              "  overwritten in place, so no past model version can be recovered. The",
              "  baseline is a reconstruction of production *logic*, not a snapshot.",
              "- **Conditional on playing.** Availability prediction is excluded; rows are",
              "  restricted to games the player actually played.",
              "- **Positions are anachronistic.** ESPN's box-score position is an athlete",
              "  profile attribute, constant across all seasons, scraped in 2026.",
              ]
    for limitation in manifest.limitations:
        lines.append(f"- {limitation}")

    lines += ["", "## Recommendation", "",
              "This is a research finding, not a deployment proposal. No production change",
              "is recommended here and none was made.", ""]
    if pooled["verdict"] == significance.MEANINGFUL:
        lines.append("The effect is large and consistent enough to justify a dedicated "
                     "follow-up study — ideally with retraining, so the ceiling can be "
                     "measured rather than inferred from a fixed model's response.")
    elif pooled["verdict"] == significance.MARGINAL:
        lines.append("Not worth further work on its own. Revisit only if a related change "
                     "lands that could plausibly amplify it.")
    elif pooled["verdict"] == significance.REGRESSION:
        lines.append("Do not pursue. Recorded so the idea is not retried.")
    else:
        lines.append("No effect detectable at this sample size. Recorded as a negative "
                     "result so the question is not reopened without new evidence.")

    lines += ["", "## Future work", ""]
    if manifest.future_work:
        lines += [f"- {item}" for item in manifest.future_work]
    else:
        lines.append("- None recorded.")

    lines += ["", "## Reproduction", "", "```bash",
              f"python3 learning/analytics_lab/experiments/framework/runner.py {manifest.experiment_id}",
              "```", "",
              f"Artifacts: `experiments/runs/{manifest.experiment_id}/`", ""]

    target = C.lab_path(f"{manifest.experiment_id.lower()}_research_report.md",
                        root=C.LAB_REPORTS / "experiments")
    target.write_text("\n".join(lines) + "\n")
    return target
