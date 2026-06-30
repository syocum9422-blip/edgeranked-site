"""Phase 3 — usage engine walk-forward validation.

Two proofs:
  A) Allocated-share accuracy: conserved model vs naive (lag5 renormalized) — does
     learning + conservation beat rolling form on share MAE, OOS?
  B) Injury-redistribution test (the #1 pain point): on games where a rotation
     regular was OUT, does CONSERVED allocation (which redistributes the vacated
     share) predict teammates' actual shares better than a STATIC baseline (each
     player keeps their usual raw share, i.e. no redistribution)?

Run:  .venv/bin/python -m wnba_v2.engines.usage.train
"""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.engines.usage.features import SHARE_COLS, build_usage_features
from wnba_v2.engines.usage.model import ConservedUsageModel

OUT = C.OUTPUTS / "usage"


def _mae(a, b):
    return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))


def _renorm(df, col, valcol):
    d = df.groupby(["game_id", "team"])[valcol].transform("sum").replace(0, np.nan)
    return (df[valcol] / d).fillna(0.0)


def walk_forward(df: pd.DataFrame) -> dict:
    seasons = sorted(df["season"].dropna().unique())
    fold_rows, redis_rows, preds = [], [], []
    for ts in seasons[1:]:
        train = df[df["season"] < ts].dropna(subset=[f"{s}_lag5" for s in SHARE_COLS])
        test = df[df["season"] == ts].copy()
        if len(train) < 500 or len(test) < 200:
            continue
        model = ConservedUsageModel().fit(train)
        alloc = model.allocate(test)

        rec = {"test_season": int(ts), "n_train": len(train), "n_test": len(test)}
        for s in SHARE_COLS:
            naive = _renorm(test.assign(_n=test[f"{s}_lag5"]), s, "_n").values
            rec[f"mae_model_{s}"] = round(_mae(alloc[s].values, test[s].values), 4)
            rec[f"mae_naive_{s}"] = round(_mae(naive, test[s].values), 4)
        fold_rows.append(rec)

        # ---- injury-redistribution test (usage_share) ----
        redis_rows.append(_redistribution_fold(df, test, ts))

        t = test[["date", "game_id", "team", "player_id"] + SHARE_COLS].copy()
        for s in SHARE_COLS:
            t[f"alloc_{s}"] = alloc[s].values
        preds.append(t)

    return {"folds": pd.DataFrame(fold_rows),
            "redis": pd.DataFrame([r for r in redis_rows if r]),
            "preds": pd.concat(preds) if preds else pd.DataFrame()}


def _redistribution_fold(full: pd.DataFrame, test: pd.DataFrame, ts: int) -> dict:
    """On test games missing a rotation regular, compare conserved vs static share
    prediction for the present teammates. Regulars = season usage_share_lag5 top-3."""
    # who are this season's regulars (by their typical role)?
    role = test.groupby("player_id")["usage_share_lag5"].mean()
    regulars = set(role[role >= role.quantile(0.70)].index)

    # full roster (played+DNP) per team-game to detect absences
    pg = pd.read_csv(C.V2_ROOT / "data" / "team_games" / "player_game_logs.csv")
    pg = pg[pg["season"] == ts]
    absent = pg[(pg["played"] == 0) & (pg["player_id"].isin(regulars))]
    affected = set(zip(absent["game_id"], absent["team"]))
    if not affected:
        return {}

    sub = test[test.apply(lambda r: (r["game_id"], r["team"]) in affected, axis=1)].copy()
    if len(sub) < 50:
        return {}
    # static: each present player keeps raw lag5 share (NO redistribution)
    static = sub["usage_share_lag5"].fillna(0).values
    # conserved: renormalize lag5 over the PRESENT roster (redistributes vacated share)
    conserved = _renorm(sub.assign(_n=sub["usage_share_lag5"].fillna(0)), "usage_share", "_n").values
    actual = sub["usage_share"].values
    return {
        "test_season": int(ts),
        "n_affected_games": len(affected),
        "n_teammate_rows": len(sub),
        "mae_static_no_redis": round(_mae(static, actual), 4),
        "mae_conserved_redis": round(_mae(conserved, actual), 4),
        "redis_improvement_pct": round((_mae(static, actual) - _mae(conserved, actual))
                                       / _mae(static, actual) * 100, 2),
    }


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    df = build_usage_features()
    res = walk_forward(df)
    folds, redis, preds = res["folds"], res["redis"], res["preds"]

    summary = {"n_rows": int(len(df)), "n_games": int(df["game_id"].nunique())}
    if not preds.empty:
        pooled = {}
        for s in SHARE_COLS:
            naive = _renorm(df.loc[preds.index].assign(_n=df.loc[preds.index][f"{s}_lag5"]), s, "_n")
            pooled[f"mae_model_{s}"] = round(_mae(preds[f"alloc_{s}"], preds[s]), 4)
        summary["pooled_model_mae"] = pooled
        summary["pooled_model_mae_mean"] = round(np.mean(list(pooled.values())), 4)
    if not redis.empty:
        summary["redistribution_test"] = redis.to_dict("records")
        summary["redistribution_helps"] = bool((redis["redis_improvement_pct"] > 0).all())

    folds.to_csv(OUT / "walkforward_folds.csv", index=False)
    redis.to_csv(OUT / "redistribution_test.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    final = ConservedUsageModel().fit(df.dropna(subset=[f"{s}_lag5" for s in SHARE_COLS]))
    joblib.dump(final, OUT / "usage_model_v2.joblib")
    return {"summary": summary, "folds": folds, "redis": redis}


if __name__ == "__main__":
    r = run()
    print("FOLDS (share MAE, model vs naive):")
    f = r["folds"]
    show = ["test_season"] + [c for c in f.columns if "usage_share" in c or "ast_share" in c]
    print(f[show].to_string(index=False) if not f.empty else "  (none)")
    print("\nREDISTRIBUTION TEST (injury — conserved vs static, usage_share):")
    print(r["redis"].to_string(index=False) if not r["redis"].empty else "  (no affected games)")
    print("\nSUMMARY:")
    print(json.dumps(r["summary"], indent=2, default=str))
