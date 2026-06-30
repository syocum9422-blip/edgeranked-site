"""Phase 3.5 — walk-forward validation + promotion gate vs Phase 3.

Compares the redistribution model against the Phase 3 conserved model on the
slates that matter: injury games and games with an important player (starter/star)
out. Promotes ONLY if Phase 3.5 beats Phase 3 on those slates — especially on
assist share, which drives the PA/PRA/assist markets.

Run:  .venv/bin/python -m wnba_v2.engines.usage.train_redistribution
"""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.engines.usage.features import SHARE_COLS
from wnba_v2.engines.usage.model import ConservedUsageModel
from wnba_v2.engines.usage.redistribution_model import RedistributionUsageModel
from wnba_v2.engines.usage.roles import REDIS_FEATURES, build_redistribution_frame

OUT = C.OUTPUTS / "usage"


def _mae(a, b):
    return float(np.mean(np.abs(np.asarray(a, float) - np.asarray(b, float))))


def _slate_metrics(test, alloc_p3, alloc_p35, mask, label):
    if mask.sum() < 40:
        return None
    rec = {"slate": label, "n_rows": int(mask.sum()),
           "n_games": int(test.loc[mask, "game_id"].nunique())}
    for s in ["usage_share", "ast_share", "reb_share"]:
        rec[f"p3_mae_{s}"] = round(_mae(alloc_p3.loc[mask, s], test.loc[mask, s]), 4)
        rec[f"p35_mae_{s}"] = round(_mae(alloc_p35.loc[mask, s], test.loc[mask, s]), 4)
        base = rec[f"p3_mae_{s}"]
        rec[f"impr_{s}_pct"] = round((base - rec[f"p35_mae_{s}"]) / base * 100, 2) if base else 0.0
    return rec


def walk_forward(df: pd.DataFrame) -> pd.DataFrame:
    seasons = sorted(df["season"].dropna().unique())
    rows = []
    for ts in seasons[1:]:
        tr = df[df["season"] < ts].dropna(subset=REDIS_FEATURES)
        te = df[df["season"] == ts].dropna(subset=REDIS_FEATURES).copy()
        if len(tr) < 500 or len(te) < 200:
            continue
        p3 = ConservedUsageModel().fit(tr)
        p35 = RedistributionUsageModel().fit(tr)
        a3 = p3.allocate(te).set_index(te.index)
        a35 = p35.allocate(te).set_index(te.index)

        slates = {
            "all": pd.Series(True, index=te.index),
            "injury (>=1 regular out)": te["n_regulars_out"] >= 1,
            "starter/star out": te["star_out"] == 1,
            "lead guard out": te["lead_guard_out"] == 1,
            "frontcourt out": te["frontcourt_out"] == 1,
        }
        for label, mask in slates.items():
            r = _slate_metrics(te, a3, a35, mask, label)
            if r:
                r["test_season"] = int(ts)
                rows.append(r)
    return pd.DataFrame(rows)


def _gate(pooled: pd.DataFrame) -> dict:
    """Promote only if Phase 3.5 beats Phase 3 on injury AND starter/star-out slates,
    with no regression on assist share there."""
    def impr(slate, stat):
        sub = pooled[pooled["slate"] == slate]
        return float(sub[f"impr_{stat}_pct"].mean()) if not sub.empty else np.nan

    inj_usage = impr("injury (>=1 regular out)", "usage_share")
    inj_ast = impr("injury (>=1 regular out)", "ast_share")
    star_usage = impr("starter/star out", "usage_share")
    star_ast = impr("starter/star out", "ast_share")
    lg_ast = impr("lead guard out", "ast_share")
    promote = bool(
        (inj_usage > 0) and (star_usage > 0)
        and (inj_ast >= -0.5) and (star_ast >= -0.5)   # no meaningful assist regression
    )
    return {
        "injury_usage_impr_pct": round(inj_usage, 2),
        "injury_ast_impr_pct": round(inj_ast, 2),
        "starOut_usage_impr_pct": round(star_usage, 2),
        "starOut_ast_impr_pct": round(star_ast, 2),
        "leadGuardOut_ast_impr_pct": round(lg_ast, 2),
        "DECISION": "PROMOTE" if promote else "HOLD",
        "rule": "promote iff usage MAE improves on injury AND star-out slates with no assist regression",
    }


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    df = build_redistribution_frame()
    folds = walk_forward(df)
    pooled = folds.groupby("slate", as_index=False).mean(numeric_only=True) if not folds.empty else folds
    gate = _gate(folds) if not folds.empty else {"DECISION": "HOLD", "rule": "no folds"}

    folds.to_csv(OUT / "redistribution_walkforward.csv", index=False)
    (OUT / "redistribution_gate.json").write_text(json.dumps(gate, indent=2, default=str))

    if gate["DECISION"] == "PROMOTE":
        final = RedistributionUsageModel().fit(df.dropna(subset=REDIS_FEATURES))
        joblib.dump(final, OUT / "redistribution_model_v2.joblib")
    return {"pooled": pooled, "gate": gate, "folds": folds}


if __name__ == "__main__":
    r = run()
    cols = ["slate", "n_rows", "p3_mae_usage_share", "p35_mae_usage_share", "impr_usage_share_pct",
            "p3_mae_ast_share", "p35_mae_ast_share", "impr_ast_share_pct"]
    print("POOLED (Phase 3 vs Phase 3.5):")
    print(r["pooled"][[c for c in cols if c in r["pooled"].columns]].to_string(index=False)
          if not r["pooled"].empty else "  (no folds)")
    print("\nPROMOTION GATE:")
    print(json.dumps(r["gate"], indent=2, default=str))
