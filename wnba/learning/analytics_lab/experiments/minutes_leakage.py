"""Phase 2C — how much of the stat models' accuracy is the actual-minutes feature.

Holds the model, the rows and every other feature identical, and varies only the
`minutes` input:

    A  LEAKED_ACTUAL_MINUTES        the target game's actual minutes (invalid)
    B  PREVIOUS_GAME_MINUTES        previous completed game's actual minutes
    C  LAST3 / LAST5 / LAST10 /     leak-safe rolling estimates
       EWM / STARTER_AWARE
    D  HISTORICAL_PROJECTED_MINUTES the production minutes model, run on as-of
                                    features only

Variant A is a diagnostic benchmark, not a performance claim. It is what the
production training procedure sees, and it cannot be reproduced at prediction
time. The headline number is the gap between it and the best leak-safe variant.

Output: ``data/baselines/model_evaluation.csv`` and
``reports/minutes_leakage_audit.md``.
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

LARGE_MINUTES_CHANGE = 8.0     # |actual - previous| threshold for the volatility cut


def build_minutes_variants(asof: pd.DataFrame) -> dict[str, pd.Series]:
    """Every candidate value for the `minutes` feature, on identical rows."""
    variants: dict[str, pd.Series] = {
        "A_LEAKED_ACTUAL_MINUTES": asof["minutes"],
        "B_PREVIOUS_GAME_MINUTES": asof["prev_game_minutes"],
        "C_LAST3_MINUTES": asof["minutes_last_3"],
        "C_LAST5_MINUTES": asof["minutes_last_5"],
        "C_LAST10_MINUTES": asof["minutes_last_10"],
        "C_EWM_MINUTES": asof["minutes_ewm"],
    }

    # Starter-aware: a player's recent form conditioned on the role they are
    # about to fill. Role is taken from the previous game's start, which is
    # pregame-knowable; announced lineups were never captured historically.
    starter_aware = asof["minutes_last_5"].copy()
    started_recently = asof["starts_last_3"].fillna(0) >= 2
    bench_recently = asof["starts_last_3"].fillna(0) == 0
    # Blend toward the longer window for stable roles, toward the shorter for
    # players whose role is in flux.
    stable = started_recently | bench_recently
    starter_aware = np.where(
        stable,
        0.5 * asof["minutes_last_5"] + 0.5 * asof["minutes_last_10"],
        asof["minutes_last_3"],
    )
    variants["C_STARTER_AWARE_MINUTES"] = pd.Series(starter_aware, index=asof.index)
    return variants


def add_projected_minutes(asof: pd.DataFrame, variants: dict[str, pd.Series]) -> dict[str, pd.Series]:
    """Variant D — the production minutes model on as-of inputs.

    Safe to use historically: its feature list was verified not to contain
    `minutes`, so it consumes only prior-game information. It is still the
    *current* binary scored in-sample.
    """
    bundle = PA.load_minutes_model()
    if bundle is None:
        return variants
    if "minutes" in bundle["feature_list"]:
        print("  WARNING: minutes model consumes `minutes`; variant D omitted as unsafe")
        return variants
    frame = PA.to_production_frame(asof, minutes_column="minutes_last_5")
    predicted = np.clip(PA.predict(bundle, frame), 5, 40)
    variants["D_HISTORICAL_PROJECTED_MINUTES"] = pd.Series(predicted, index=asof.index)
    return variants


def eligible_rows(asof: pd.DataFrame) -> pd.DataFrame:
    """Rows where every variant is defined, so all are scored on identical rows.

    Restricted to games the player actually played: a DNP has no stat line to
    predict, and mixing DNPs in would score availability rather than production.
    """
    frame = asof[(asof["played"] == 1) & (asof["season_type"] == "regular")].copy()
    required = ["minutes", "prev_game_minutes", "minutes_last_3", "minutes_last_5",
                "minutes_last_10", "minutes_ewm"]
    return frame.dropna(subset=required)


def evaluate(asof: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = eligible_rows(asof)
    variants = add_projected_minutes(rows, build_minutes_variants(rows))
    models = PA.load_stat_models()
    if not models:
        raise FileNotFoundError(f"no production stat models found in {C.PROD_STAT_MODEL_DIR}")

    rows = rows.copy()
    rows["minutes_change"] = (rows["minutes"] - rows["prev_game_minutes"]).abs()
    rows["minutes_bucket"] = pd.cut(rows["minutes"], [-0.1, 10, 20, 28, 34, 60],
                                    labels=["0-10", "10-20", "20-28", "28-34", "34+"])
    rows["role"] = np.where(rows["starter"] == 1, "starter", "bench")
    rows["large_minutes_change"] = rows["minutes_change"] >= LARGE_MINUTES_CHANGE

    records: list[dict] = []
    predictions: dict[tuple[str, str], np.ndarray] = {}
    for variant, minutes in variants.items():
        frame = PA.to_production_frame(rows, minutes_column="minutes")
        frame["minutes"] = minutes.to_numpy()
        for stat, bundle in models.items():
            predicted = PA.predict(bundle, frame)
            predictions[(variant, stat)] = predicted
            actual = rows[stat]
            base = {"variant": variant, "stat": stat, "segment": "ALL", "segment_value": "ALL"}
            records.append({**base, **M.point_metrics(actual, pd.Series(predicted, index=rows.index))})

            series = pd.Series(predicted, index=rows.index)
            for segment in ("minutes_bucket", "role", "season", "large_minutes_change"):
                for value, group in rows.groupby(segment, observed=True):
                    records.append({
                        "variant": variant, "stat": stat, "segment": segment,
                        "segment_value": str(value),
                        **M.point_metrics(group[stat], series.loc[group.index]),
                    })

    evaluation = pd.DataFrame(records)
    minutes_frame = pd.DataFrame({k: v for k, v in variants.items()}, index=rows.index)
    minutes_frame["actual_minutes"] = rows["minutes"]
    return evaluation, minutes_frame


def _headline(evaluation: pd.DataFrame) -> pd.DataFrame:
    overall = evaluation[evaluation.segment == "ALL"]
    pivot = overall.pivot_table(index="variant", columns="stat", values="mae")
    pivot["pooled_mae"] = overall.groupby("variant").apply(
        lambda g: float(np.average(g["mae"], weights=g["n"])), include_groups=False
    )
    return pivot.sort_values("pooled_mae")


def write_report(evaluation: pd.DataFrame, minutes_frame: pd.DataFrame) -> Path:
    overall = evaluation[evaluation.segment == "ALL"]
    headline = _headline(evaluation)
    leaked = headline.loc["A_LEAKED_ACTUAL_MINUTES", "pooled_mae"]
    leak_safe = headline.drop(index="A_LEAKED_ACTUAL_MINUTES")
    best_name = leak_safe["pooled_mae"].idxmin()
    best = leak_safe.loc[best_name, "pooled_mae"]
    previous = headline.loc["B_PREVIOUS_GAME_MINUTES", "pooled_mae"]

    lines = [
        "# Phase 2C — Minutes leakage audit",
        "",
        f"**Date:** 2026-07-25  |  **Eligible player-games:** {int(overall.n.max()):,}"
        f"  |  **Stats:** {overall.stat.nunique()}",
        "",
        "## What this measures",
        "",
        "One knob is varied — the `minutes` feature — with the model, the rows and",
        "every other feature held identical. Differences are therefore attributable",
        "to that column alone.",
        "",
        "> **The production stat-model binaries are audit artifacts here.** They were",
        "> trained on data covering this whole window, so absolute MAE below is",
        "> in-sample and is *not* live accuracy. They are also the only binaries that",
        "> exist — the trainer overwrites in place with no versioning — so no",
        "> historical model version is represented.",
        "",
        "## Headline",
        "",
        "```",
        "Accuracy inflation from actual-minutes leakage",
        "  = leak-safe MAE - leaked MAE",
        f"  = {best:.4f} ({best_name})",
        f"  - {leaked:.4f} (A_LEAKED_ACTUAL_MINUTES)",
        f"  = {best - leaked:+.4f} pooled MAE  ({(best - leaked) / leaked:+.1%})",
        "```",
        "",
        f"Variant A is what the production training procedure optimises against. It",
        f"cannot be reproduced at prediction time, so **{best - leaked:+.4f} pooled MAE**",
        f"of the models' apparent accuracy is unavailable in production.",
        "",
        f"The behaviour production actually ships (B, previous-game minutes) is",
        f"**{previous - best:+.4f} pooled MAE** worse than the best leak-safe estimate",
        f"({best_name}) — an improvement available with no model change.",
        "",
        "## Pooled MAE by variant",
        "",
        "| Variant | " + " | ".join(headline.columns[:-1]) + " | pooled MAE |",
        "|---|" + "---|" * len(headline.columns),
    ]
    for variant, row in headline.iterrows():
        cells = " | ".join(f"{row[c]:.3f}" for c in headline.columns[:-1])
        marker = " **(invalid — diagnostic only)**" if variant.startswith("A_") else ""
        lines.append(f"| `{variant}`{marker} | {cells} | **{row['pooled_mae']:.4f}** |")

    lines += ["", "## Full metric set (all stats pooled, overall segment)", "",
              "| Variant | Stat | n | MAE | RMSE | Bias | MedAE | ≤1 | ≤2 | Corr |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for _, row in overall.sort_values(["stat", "mae"]).iterrows():
        lines.append(
            f"| `{row.variant}` | {row.stat} | {int(row.n)} | {row.mae:.3f} | {row.rmse:.3f} | "
            f"{row.bias:+.3f} | {row.median_abs_error:.3f} | {row['within_1']:.1%} | "
            f"{row['within_2']:.1%} | {row.correlation:.3f} |"
        )

    for segment, title in (("minutes_bucket", "Error by actual-minutes bucket"),
                           ("role", "Error by starter / bench"),
                           ("season", "Error by season"),
                           ("large_minutes_change",
                            f"Error where minutes moved ≥{LARGE_MINUTES_CHANGE:g} vs the previous game")):
        block = evaluation[(evaluation.segment == segment) & (evaluation.stat == "points")]
        if block.empty:
            continue
        pivot = block.pivot_table(index="variant", columns="segment_value", values="mae")
        counts = block.groupby("segment_value")["n"].max()
        lines += ["", f"## {title} — points MAE", "",
                  "| Variant | " + " | ".join(f"{c} (n={int(counts[c])})" for c in pivot.columns) + " |",
                  "|---|" + "---|" * len(pivot.columns)]
        for variant, row in pivot.iterrows():
            lines.append(f"| `{variant}` | " + " | ".join(f"{v:.3f}" for v in row) + " |")

    corr = minutes_frame.corr()["actual_minutes"].drop("actual_minutes").sort_values(ascending=False)
    error = (minutes_frame.drop(columns="actual_minutes")
             .sub(minutes_frame["actual_minutes"], axis=0).abs().mean().sort_values())
    lines += ["", "## How well each variant estimates actual minutes", "",
              "| Variant | corr with actual minutes | MAE vs actual minutes |", "|---|---|---|"]
    for variant in error.index:
        lines.append(f"| `{variant}` | {corr[variant]:.3f} | {error[variant]:.2f} |")

    lines += [
        "",
        "## Reading this correctly",
        "",
        "- Variant A is **not** production accuracy and must never be quoted as such.",
        "- All absolute numbers are in-sample; only the *differences between variants*",
        "  are trustworthy, because the model and rows are shared.",
        "- Rows are restricted to games the player actually played. Availability",
        "  prediction is a separate problem and is deliberately excluded.",
        "",
    ]
    target = C.lab_path("minutes_leakage_audit.md", root=C.LAB_REPORTS)
    target.write_text("\n".join(lines) + "\n")
    return target


def main() -> int:
    asof = pd.read_parquet(C.LAB_ROOT / "data" / "features" / "asof_features.parquet")
    evaluation, minutes_frame = evaluate(asof)
    C.write_csv(evaluation, "model_evaluation.csv", root=C.LAB_DATA / "baselines")
    report = write_report(evaluation, minutes_frame)

    headline = _headline(evaluation)
    leaked = headline.loc["A_LEAKED_ACTUAL_MINUTES", "pooled_mae"]
    leak_safe = headline.drop(index="A_LEAKED_ACTUAL_MINUTES")
    best_name = leak_safe["pooled_mae"].idxmin()

    print("PHASE 2C — MINUTES LEAKAGE")
    print(f"  eligible player-games   {int(evaluation[evaluation.segment=='ALL'].n.max()):,}")
    print("\n  pooled MAE by variant (lower is better)")
    for variant, row in headline.iterrows():
        flag = "  <-- INVALID, diagnostic only" if variant.startswith("A_") else ""
        print(f"    {variant:<34} {row['pooled_mae']:.4f}{flag}")
    print(f"\n  accuracy inflation from actual-minutes leakage: "
          f"{leak_safe.loc[best_name,'pooled_mae'] - leaked:+.4f} pooled MAE "
          f"({(leak_safe.loc[best_name,'pooled_mae'] - leaked)/leaked:+.1%})")
    print(f"  best leak-safe variant: {best_name}")
    print(f"  production's shipped behaviour (B) vs best leak-safe: "
          f"{headline.loc['B_PREVIOUS_GAME_MINUTES','pooled_mae'] - leak_safe.loc[best_name,'pooled_mae']:+.4f} MAE")
    print(f"\n  wrote {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
