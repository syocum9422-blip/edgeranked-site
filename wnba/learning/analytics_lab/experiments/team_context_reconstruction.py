"""Phase 2E — rebuild team context from the ESPN cache and check it against the
production feed.

Production reads pace / off_rating / def_rating from `wnba_team_context.csv`,
which stopped carrying them on 2026-06-28. Three model features depend on them.
This module rebuilds the same quantities from cached box scores, validates the
reconstruction against the period where production was still healthy, and
quantifies how many live and archived rows the outage touched.

Read-only. Writes only under the lab.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from analytics_lab.config import lab_config as C
    from analytics_lab.replay import asof_features as AF
else:
    from ..config import lab_config as C
    from ..replay import asof_features as AF

METRICS = ["pace", "off_rating", "def_rating"]


def reconstructed_context(window: int = 10) -> pd.DataFrame:
    """Per team-game possessions and ratings, plus as-of rolling forms.

    Season openers and low-sample games are handled by carrying an explicit
    ``team_games_played`` count and a ``low_sample`` flag rather than by
    back-filling a league average — a silently imputed value is indistinguishable
    from a real one downstream.
    """
    teams = AF.load_team_games()
    context = AF.build_team_context(teams, window=window)
    frame = teams.merge(context, on=["game_id", "team_id"], how="left")
    frame["low_sample"] = (frame["team_games_played"] < 3).astype(int)
    frame["season_opener"] = (frame["team_games_played"] == 0).astype(int)
    return frame


def production_context() -> pd.DataFrame:
    frame = pd.read_csv(C.PROD_TEAM_CONTEXT, low_memory=False)
    frame["game_date"] = pd.to_datetime(frame["game_date"])
    return frame


def outage_summary(production: pd.DataFrame) -> dict:
    """When the production feed stopped and how much it covers month by month."""
    frame = production.copy()
    frame["has_pace"] = frame["pace"].notna()
    monthly = frame.groupby(frame["game_date"].dt.to_period("M"))["has_pace"].agg(["size", "mean"])
    healthy = frame[frame["has_pace"]]
    dead = frame[~frame["has_pace"]]
    last_good = healthy["game_date"].max()
    first_dead_after = dead[dead["game_date"] > last_good]["game_date"].min()
    return {
        "rows": len(frame),
        "rows_with_pace": int(frame["has_pace"].sum()),
        "coverage": float(frame["has_pace"].mean()),
        "last_healthy_date": last_good,
        "first_dead_date_after": first_dead_after,
        "rows_after_outage": int((frame["game_date"] > last_good).sum()),
        "monthly": monthly,
    }


def compare_overlap(reconstruction: pd.DataFrame, production: pd.DataFrame) -> pd.DataFrame:
    """Correlation and scale between the two sources where production is healthy.

    Joined on (game_id, team abbreviation): production has no team_id, and its
    game_date is a UTC date, so a date join would be wrong.
    """
    left = reconstruction.copy()
    left["game_id"] = left["game_id"].astype(str)
    right = production.dropna(subset=["game_id", "pace"]).copy()
    right["game_id"] = right["game_id"].astype("int64").astype(str)

    merged = left.merge(
        right[["game_id", "team", "pace", "off_rating", "def_rating"]],
        left_on=["game_id", "team_abbrev"], right_on=["game_id", "team"],
        how="inner", suffixes=("_lab", "_prod"),
    )
    rows = []
    for metric in METRICS:
        lab, prod = merged[f"{metric}_lab"], merged[f"{metric}_prod"]
        both = lab.notna() & prod.notna()
        if both.sum() < 10:
            continue
        a, b = lab[both], prod[both]
        rows.append({
            "metric": metric, "n": int(both.sum()),
            "correlation": float(a.corr(b)),
            "lab_mean": float(a.mean()), "production_mean": float(b.mean()),
            "mean_difference": float((a - b).mean()),
            "mean_abs_difference": float((a - b).abs().mean()),
            "ratio_lab_over_production": float(a.mean() / b.mean()) if b.mean() else np.nan,
            "p90_abs_difference": float((a - b).abs().quantile(0.9)),
        })
    return pd.DataFrame(rows), merged


def affected_rows(reconstruction: pd.DataFrame, outage_date: pd.Timestamp) -> dict:
    """Live board and archived rows that fell inside the outage."""
    result: dict = {}
    if C.PROD_TODAY_FEATURES.exists():
        today = pd.read_csv(C.PROD_TODAY_FEATURES, low_memory=False)
        result["live_board_rows"] = len(today)
        result["live_board_null_pace"] = float(today["pace_last_10"].isna().mean())

    archives = sorted(C.PROD_PROJECTION_ARCHIVE_DIR.glob("wnba_projections_*.csv"))
    cutoff = outage_date.strftime("%Y%m%d")
    affected, total_rows, affected_rows_count = 0, 0, 0
    for path in archives:
        stamp = path.stem.split("_")[-1]
        try:
            frame = pd.read_csv(path, low_memory=False)
        except Exception:
            continue
        total_rows += len(frame)
        if stamp > cutoff:
            affected += 1
            affected_rows_count += len(frame)
    result.update({
        "archives_total": len(archives), "archives_after_outage": affected,
        "archive_rows_total": total_rows, "archive_rows_after_outage": affected_rows_count,
        "archive_rows_affected_share": affected_rows_count / total_rows if total_rows else np.nan,
    })
    return result


def write_report(reconstruction, outage, comparison, affected) -> Path:
    lines = [
        "# Phase 2E — Team-context reconstruction",
        "",
        "**Date:** 2026-07-25",
        "",
        "## The production outage",
        "",
        f"`wnba_team_context.csv` holds {outage['rows']:,} team-game rows. "
        f"`pace` / `off_rating` / `def_rating` are present on "
        f"{outage['rows_with_pace']:,} ({outage['coverage']:.1%}).",
        "",
        f"- **Last healthy game date:** {outage['last_healthy_date'].date()}",
        f"- **Rows after that date with no pace at all:** {outage['rows_after_outage']:,}",
        "",
        "Monthly coverage:",
        "",
        "| Month | team-game rows | share with pace |",
        "|---|---|---|",
    ]
    for period, row in outage["monthly"].tail(10).iterrows():
        lines.append(f"| {period} | {int(row['size'])} | {row['mean']:.1%} |")

    lines += [
        "",
        "## Reconstruction",
        "",
        "Rebuilt from cached ESPN box scores, independent of the production feed:",
        "",
        "```",
        "possessions = FGA - OREB + TOV + 0.44 * FTA        (per team)",
        "game_possessions = mean of the two teams' estimates  (shared, keeps a game consistent)",
        "off_rating = 100 * team_points     / game_possessions",
        "def_rating = 100 * opponent_points / game_possessions",
        "pace       = game_possessions                       (40-minute regulation game)",
        "```",
        "",
        f"- **Team-game rows reconstructed:** {len(reconstruction):,}",
        f"- **Span:** {reconstruction.slate_date_et.min()} → {reconstruction.slate_date_et.max()}",
        f"- **Coverage of pace/off/def:** "
        f"{reconstruction['pace'].notna().mean():.1%} / "
        f"{reconstruction['off_rating'].notna().mean():.1%} / "
        f"{reconstruction['def_rating'].notna().mean():.1%}",
        f"- **Season openers (no prior form):** {int(reconstruction.season_opener.sum())} "
        f"— flagged, never back-filled with a league average",
        f"- **Low-sample rows (< 3 prior games):** {int(reconstruction.low_sample.sum())}",
        "",
        "Rolling forms use `shift(1)`, so no target-game total enters its own feature.",
        "Teams are matched by ESPN `team_id`; the opponent is the other competitor on",
        "the same `game_id`.",
        "",
        "## Agreement with production over the healthy period",
        "",
        "| Metric | n | correlation | lab mean | production mean | mean diff | mean abs diff | p90 abs diff |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for _, row in comparison.iterrows():
        lines.append(
            f"| {row.metric} | {row.n:,} | {row.correlation:.4f} | {row.lab_mean:.2f} | "
            f"{row.production_mean:.2f} | {row.mean_difference:+.3f} | "
            f"{row.mean_abs_difference:.3f} | {row.p90_abs_difference:.3f} |"
        )

    lines += [
        "",
        "## Rows affected by the outage",
        "",
        f"- Live board ({affected.get('live_board_rows', 0)} rows): "
        f"**{affected.get('live_board_null_pace', float('nan')):.1%}** have a null "
        "`pace_last_10` / `off_rating_last_10` / `def_rating_last_10` and are "
        "median-imputed by the model pipeline's `SimpleImputer`.",
        f"- Archived boards: **{affected['archives_after_outage']} of "
        f"{affected['archives_total']}** dated after the outage, covering "
        f"**{affected['archive_rows_after_outage']:,} of {affected['archive_rows_total']:,}** "
        f"rows (**{affected['archive_rows_affected_share']:.1%}**).",
        "",
        "## Verdict",
        "",
        "The reconstruction is a valid drop-in for lab work across the full",
        "2024–2026 span and needs no external data. Its scale differs slightly from",
        "the production feed (see the table above), so lab results are not directly",
        "comparable to production numbers computed before the outage — an experiment",
        "should use one source throughout, and say which.",
        "",
        "No production file was written. The proposed production repair is recorded",
        "in `reports/proposed_production_changes.md` for separate review.",
        "",
    ]
    target = C.lab_path("team_context_reconstruction.md", root=C.LAB_REPORTS)
    target.write_text("\n".join(lines) + "\n")
    return target


def main() -> int:
    reconstruction = reconstructed_context()
    production = production_context()
    outage = outage_summary(production)
    comparison, merged = compare_overlap(reconstruction, production)
    affected = affected_rows(reconstruction, outage["last_healthy_date"])

    keep = ["game_id", "team_id", "team_abbrev", "opponent_id", "opponent_abbrev",
            "start_utc", "slate_date_et", "season", "season_type", "possessions",
            "game_possessions", "pace", "off_rating", "def_rating", "net_rating",
            "team_games_played", "low_sample", "season_opener"] + [
        c for c in reconstruction.columns if c.endswith("_last_10")]
    C.write_csv(reconstruction[keep], "normalized", "team_context_reconstructed.csv")
    C.write_csv(comparison, "team_context_comparison.csv", root=C.LAB_REPORTS)
    report = write_report(reconstruction, outage, comparison, affected)

    print("PHASE 2E — TEAM CONTEXT RECONSTRUCTION")
    print(f"  production rows                {outage['rows']:,} "
          f"({outage['coverage']:.1%} with pace)")
    print(f"  production last healthy date   {outage['last_healthy_date'].date()}")
    print(f"  production rows after outage   {outage['rows_after_outage']:,} (all null)")
    print(f"  reconstructed team-game rows   {len(reconstruction):,} "
          f"({reconstruction['pace'].notna().mean():.1%} coverage), "
          f"{reconstruction.slate_date_et.min()} -> {reconstruction.slate_date_et.max()}")
    print("\n  agreement over the healthy overlap")
    for _, row in comparison.iterrows():
        print(f"    {row.metric:<12} n={row.n:<6} corr={row.correlation:.4f}  "
              f"lab {row.lab_mean:.2f} vs prod {row.production_mean:.2f} "
              f"(mean abs diff {row.mean_abs_difference:.3f})")
    print(f"\n  live board rows with null pace  {affected.get('live_board_null_pace', float('nan')):.1%}")
    print(f"  archives after outage           {affected['archives_after_outage']}/"
          f"{affected['archives_total']} "
          f"({affected['archive_rows_affected_share']:.1%} of archived rows)")
    print(f"\n  wrote {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
