#!/usr/bin/env python3
"""True WNBA projection grading — archived published projections vs final box scores.

Grades ONLY archived production boards (outputs/archive/projections/wnba_projections_*.csv),
which were published before game time, against official actuals
(data/raw/wnba_player_games.csv). It never regenerates a projection and never touches best-bet
artifacts (graded_bets.csv / bet_result / sportsbook lines / over-under sides).

Outputs (projection_accuracy/reports/):
  projection_accuracy_report.json   — per-category metrics, 30d + season, trend, extremes
  projection_accuracy_graded.csv    — every graded player-stat row
  projection_accuracy_reconcile.csv — published / graded / skipped / excluded + reason

Read-only w.r.t. production. Safe to run any time (idempotent).
"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(HERE, "reports")
os.makedirs(REPORTS, exist_ok=True)

ARCHIVE_GLOB = os.path.join(ROOT, "outputs/archive/projections/wnba_projections_*.csv")
ACTUALS_PATH = os.path.join(ROOT, "data/raw/wnba_player_games.csv")

# category -> (archive projection column candidates, actual-value builder)
SINGLE = {
    "points": (["PTS_PROJ", "pts_proj"], "points"),
    "rebounds": (["REB_PROJ", "reb_proj"], "rebounds"),
    "assists": (["AST_PROJ", "ast_proj"], "assists"),
    "threes_made": (["FG3M_PROJ", "fg3m_proj"], "threes_made"),
    "steals": (["STL_PROJ", "stl_proj"], "steals"),
    "blocks": (["BLK_PROJ", "blk_proj"], "blocks"),
    "minutes": (["MIN_PROJ", "PRED_MIN", "projected_minutes"], "minutes"),
}
COMBO = {
    "pra": (["PRA_PROJ"], ["points", "rebounds", "assists"]),
    "pr": (["PR_PROJ"], ["points", "rebounds"]),
    "pa": (["PA_PROJ"], ["points", "assists"]),
    "ra": (["RA_PROJ"], ["rebounds", "assists"]),
}
# Turnovers deliberately excluded: the projection engine publishes no TO_PROJ column.
NOT_PROJECTED = ["turnovers"]

# scale used for the normalized-MAE headline (season actual averages by counting stat)
NORMALIZE_OVER = ["points", "rebounds", "assists", "threes_made", "steals", "blocks"]
TOLERANCE = 2.0  # "% within expected tolerance" band for the headline card


def _first_col(row_cols, candidates):
    for c in candidates:
        if c in row_cols:
            return c
    return None


def load_actuals() -> pd.DataFrame:
    pg = pd.read_csv(ACTUALS_PATH, parse_dates=["game_date"])
    pg["player_key"] = pg["player_key"].astype(str).str.lower().str.strip()
    for combo, parts in {"pra": ["points", "rebounds", "assists"], "pr": ["points", "rebounds"],
                         "pa": ["points", "assists"], "ra": ["rebounds", "assists"]}.items():
        pg[combo] = sum(pg[p] for p in parts)
    return pg


def grade():
    actuals = load_actuals()
    # one row per player_key+date (dedup; keep the row with most minutes if duplicated)
    act = (actuals.sort_values("minutes", ascending=False)
           .drop_duplicates(["player_key", "game_date"]))
    act_idx = act.set_index(["player_key", "game_date"])
    played_dates = set(actuals["game_date"].unique())  # slates with any completed box score

    graded_rows = []
    recon = []  # reconciliation ledger
    files = sorted(glob.glob(ARCHIVE_GLOB))
    for f in files:
        base = os.path.basename(f)
        try:
            slate = pd.to_datetime(base.replace("wnba_projections_", "").replace(".csv", ""))
        except ValueError:
            continue
        try:
            board = pd.read_csv(f)
        except Exception:
            continue
        if "PLAYER_KEY" not in board.columns:
            continue
        board["player_key"] = board["PLAYER_KEY"].astype(str).str.lower().str.strip()
        gdate = pd.to_datetime(board["GAME_DATE"]).iloc[0] if "GAME_DATE" in board.columns else slate
        cols = set(board.columns)

        for _, prow in board.iterrows():
            pk = prow["player_key"]
            key = (pk, gdate)
            published_any = False
            # locate actual
            if key not in act_idx.index:
                reason = ("slate_not_yet_played" if gdate not in played_dates
                          else "player_absent_from_boxscore")
                recon.append({"slate_date": slate.date(), "player_key": pk,
                              "status": "excluded", "reason": reason})
                continue
            arow = act_idx.loc[key]
            if isinstance(arow, pd.DataFrame):
                arow = arow.iloc[0]
            played = bool(arow.get("played", True)) and float(arow.get("minutes", 0)) > 0
            if not played:
                recon.append({"slate_date": slate.date(), "player_key": pk,
                              "status": "excluded", "reason": "dnp_zero_minutes"})
                continue

            for cat, (cands, actual_col) in SINGLE.items():
                pc = _first_col(cols, cands)
                if pc is None:
                    continue
                proj = pd.to_numeric(prow.get(pc), errors="coerce")
                actual = pd.to_numeric(arow.get(actual_col), errors="coerce")
                if pd.isna(proj) or pd.isna(actual):
                    recon.append({"slate_date": slate.date(), "player_key": pk,
                                  "status": "skipped", "reason": f"missing_value_{cat}"})
                    continue
                published_any = True
                err = float(proj - actual)
                graded_rows.append({"slate_date": slate.date(), "game_date": gdate.date(),
                                    "player_key": pk, "player_name": prow.get("PLAYER_NAME"),
                                    "team": prow.get("TEAM_ABBREVIATION"), "category": cat,
                                    "projected": float(proj), "actual": float(actual),
                                    "error": err, "abs_error": abs(err), "sq_error": err * err})
            for cat, (cands, parts) in COMBO.items():
                pc = _first_col(cols, cands)
                if pc is None:
                    continue
                proj = pd.to_numeric(prow.get(pc), errors="coerce")
                actual = pd.to_numeric(arow.get(cat), errors="coerce")
                if pd.isna(proj) or pd.isna(actual):
                    continue
                published_any = True
                err = float(proj - actual)
                graded_rows.append({"slate_date": slate.date(), "game_date": gdate.date(),
                                    "player_key": pk, "player_name": prow.get("PLAYER_NAME"),
                                    "team": prow.get("TEAM_ABBREVIATION"), "category": cat,
                                    "projected": float(proj), "actual": float(actual),
                                    "error": err, "abs_error": abs(err), "sq_error": err * err})
            if published_any:
                recon.append({"slate_date": slate.date(), "player_key": pk,
                              "status": "graded", "reason": ""})

    graded = pd.DataFrame(graded_rows)
    recon_df = pd.DataFrame(recon)
    graded.to_csv(os.path.join(REPORTS, "projection_accuracy_graded.csv"), index=False)
    recon_df.to_csv(os.path.join(REPORTS, "projection_accuracy_reconcile.csv"), index=False)
    return graded, recon_df


def _cat_metrics(df: pd.DataFrame) -> dict:
    e = df["error"].to_numpy()
    ae = df["abs_error"].to_numpy()
    return {
        "graded": int(len(df)),
        "mae": round(float(ae.mean()), 4),
        "rmse": round(float(np.sqrt((e ** 2).mean())), 4),
        "bias": round(float(e.mean()), 4),
        "median_abs_error": round(float(np.median(ae)), 4),
        "pct_within_1": round(float((ae <= 1).mean()), 4),
        "pct_within_2": round(float((ae <= 2).mean()), 4),
        "pct_within_3": round(float((ae <= 3).mean()), 4),
        "projected_avg": round(float(df["projected"].mean()), 4),
        "actual_avg": round(float(df["actual"].mean()), 4),
        "last_graded_date": str(df["slate_date"].max()),
    }


def build_report(graded: pd.DataFrame, recon: pd.DataFrame) -> dict:
    graded["slate_date"] = pd.to_datetime(graded["slate_date"])
    max_date = graded["slate_date"].max()
    win_start = max_date - timedelta(days=30)

    def window_block(df):
        cats = {}
        for cat in list(SINGLE) + list(COMBO):
            sub = df[df["category"] == cat]
            if len(sub):
                cats[cat] = _cat_metrics(sub)
        singles = df[df["category"].isin(NORMALIZE_OVER)]
        # overall normalized MAE = mean over counting stats of (MAE / actual_avg)
        norm_terms = []
        for cat in NORMALIZE_OVER:
            sub = df[df["category"] == cat]
            if len(sub) and sub["actual"].mean() > 0:
                norm_terms.append(sub["abs_error"].mean() / sub["actual"].mean())
        overall = {
            "projections_graded": int(len(df)),
            "singles_graded": int(len(singles)),
            "overall_normalized_mae": round(float(np.mean(norm_terms)), 4) if norm_terms else None,
            "pooled_singles_mae": round(float(singles["abs_error"].mean()), 4) if len(singles) else None,
            "pooled_singles_rmse": round(float(np.sqrt((singles["error"] ** 2).mean())), 4) if len(singles) else None,
            "pooled_singles_bias": round(float(singles["error"].mean()), 4) if len(singles) else None,
            "pct_within_tolerance": round(float((singles["abs_error"] <= TOLERANCE).mean()), 4) if len(singles) else None,
            "tolerance_band": TOLERANCE,
            "last_graded_date": str(df["slate_date"].max().date()),
            "first_graded_date": str(df["slate_date"].min().date()),
        }
        return {"overall": overall, "by_category": cats}

    last30 = graded[graded["slate_date"] >= win_start]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "grading_basis": "archived published projections vs official box scores; no lookahead; "
                         "best-bet artifacts not used",
        "categories_graded": list(SINGLE) + list(COMBO),
        "categories_excluded": {c: "not_projected_by_engine" for c in NOT_PROJECTED},
        "last_30_days": window_block(last30),
        "season": window_block(graded),
    }

    # rolling 30-day overall-normalized-MAE trend (per slate date, singles pooled MAE)
    trend = []
    singles = graded[graded["category"].isin(NORMALIZE_OVER)]
    daily = singles.groupby(singles["slate_date"].dt.date).agg(
        mae=("abs_error", "mean"), n=("abs_error", "size"))
    roll = daily["mae"].rolling(min_periods=1, window=30).mean()
    for d, m, n, r in zip(daily.index, daily["mae"], daily["n"], roll):
        trend.append({"date": str(d), "daily_mae": round(float(m), 4),
                      "rolling30_mae": round(float(r), 4), "n": int(n)})
    report["rolling_mae_trend"] = trend

    # largest over/under projections (season, singles+combos), player-stat rows
    ex = graded.copy()
    ex["disp"] = ex["player_name"].astype(str) + " " + ex["category"] + " " + ex["slate_date"].dt.strftime("%Y-%m-%d")
    over = ex.nlargest(25, "error")[["disp", "player_name", "category", "slate_date", "projected", "actual", "error"]]
    under = ex.nsmallest(25, "error")[["disp", "player_name", "category", "slate_date", "projected", "actual", "error"]]
    over["slate_date"] = over["slate_date"].dt.strftime("%Y-%m-%d")
    under["slate_date"] = under["slate_date"].dt.strftime("%Y-%m-%d")
    report["largest_over_projections"] = over.round(2).to_dict("records")
    report["largest_under_projections"] = under.round(2).to_dict("records")

    # residual distribution (singles, standardized per category) + actual-vs-projected bins
    resid_hist = {}
    for cat in NORMALIZE_OVER:
        sub = graded[graded["category"] == cat]
        if len(sub):
            counts, edges = np.histogram(sub["error"], bins=np.arange(-15, 15.5, 1.0))
            resid_hist[cat] = {"edges": edges.round(1).tolist(), "counts": counts.tolist()}
    report["residual_histogram"] = resid_hist

    # reconciliation summary
    rc = recon["status"].value_counts().to_dict() if len(recon) else {}
    reasons = (recon[recon["status"] != "graded"].groupby(["status", "reason"]).size()
               .reset_index(name="n").to_dict("records")) if len(recon) else []
    report["reconciliation"] = {
        "player_slate_rows_published": int(len(recon)),
        "counts_by_status": {k: int(v) for k, v in rc.items()},
        "exclusion_reasons": reasons,
        "archived_slates": int(graded["slate_date"].nunique()),
    }
    return report


def main():
    graded, recon = grade()
    if graded.empty:
        print("no graded rows")
        return
    report = build_report(graded, recon)
    out = os.path.join(REPORTS, "projection_accuracy_report.json")
    with open(out, "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    s = report["season"]["overall"]
    l30 = report["last_30_days"]["overall"]
    print(f"wrote {out}")
    print(f"season: {s['projections_graded']} graded, normalized MAE {s['overall_normalized_mae']}, "
          f"pooled singles MAE {s['pooled_singles_mae']}, bias {s['pooled_singles_bias']}")
    print(f"30d:    {l30['projections_graded']} graded, normalized MAE {l30['overall_normalized_mae']}, "
          f"within±{TOLERANCE}: {l30['pct_within_tolerance']}")
    print("reconciliation:", report["reconciliation"]["counts_by_status"])


if __name__ == "__main__":
    main()
