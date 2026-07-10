#!/usr/bin/env python3
"""Grade accuracy-recovery shadow boards vs actuals and vs the live production book.

Run any time (idempotent). Appends nothing to production; writes
accuracy_recovery/reports/shadow_ledger.csv and prints a promotion verdict.

Promotion gate (all must hold before flipping WNBA_ACCURACY_RECOVERY=on):
  * >= 15 graded shadow slates
  * shadow hit rate > production hit rate on the same dates
  * one-sided two-proportion test p < 0.10 OR day-paired Wilcoxon p < 0.10
  * no stat category with n>=30 below 45%
"""
import glob
import os

import numpy as np
import pandas as pd
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

boards = []
for f in sorted(glob.glob(f"{HERE}/shadow_boards/recovery_board_*.csv")):
    day = pd.to_datetime(os.path.basename(f)[15:23])
    try:
        b = pd.read_csv(f)
    except Exception:
        continue
    if b.empty:
        continue
    b["date"] = day
    boards.append(b)

if not boards:
    print("no shadow boards yet")
    raise SystemExit(0)

sb = pd.concat(boards, ignore_index=True)
pg = pd.read_csv(f"{ROOT}/data/raw/wnba_player_games.csv", parse_dates=["game_date"])
for c, parts in {"pra": ["points", "rebounds", "assists"], "pr": ["points", "rebounds"],
                 "pa": ["points", "assists"], "ra": ["rebounds", "assists"]}.items():
    pg[c] = sum(pg[p] for p in parts)
pg["pk"] = pg.player_key

sb["pk"] = sb.player_name.str.lower().str.strip()
m = sb.merge(pg, left_on=["date", "pk"], right_on=["game_date", "pk"], how="left",
             suffixes=("", "_act"))
m = m[(m.minutes > 0) & m.played.fillna(False).astype(bool)]
m["actual"] = [r[str(r.stat).lower()] if str(r.stat).lower() in r.index else np.nan
               for _, r in m.iterrows()]
m = m.dropna(subset=["actual"])
m = m[m.actual != m.line]  # void pushes
m["win"] = np.where(m.side.str.lower() == "over", m.actual > m.line, m.actual < m.line).astype(int)

ledger = m[["date", "player_name", "stat", "side", "line", "projection_mean",
            "hit_rate", "actual", "win"]]
ledger.to_csv(f"{HERE}/reports/shadow_ledger.csv", index=False)

gb = pd.read_csv(f"{ROOT}/Best_Bets/graded_bets.csv", parse_dates=["bet_date"])
gb = gb[(gb.sportsbook == "prizepicks") & gb.bet_result.isin(["win", "loss"])]
gb = gb[gb.bet_date.isin(ledger.date.unique())]
gb["win"] = (gb.bet_result == "win").astype(int)

n_days = ledger.date.nunique()
sh, sn = ledger.win.mean(), len(ledger)
ph, pn = gb.win.mean(), len(gb)
print(f"shadow:     {sh:.4f} over {sn} picks / {n_days} slates")
print(f"production: {ph:.4f} over {pn} picks (same dates)")

verdict = "NOT_READY"
if n_days >= 15 and sn >= 100 and pn >= 100:
    p_pool = (ledger.win.sum() + gb.win.sum()) / (sn + pn)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / sn + 1 / pn))
    z = (sh - ph) / se if se > 0 else 0.0
    p_z = 1 - stats.norm.cdf(z)
    ds = ledger.groupby("date").win.mean()
    dp = gb.groupby(gb.bet_date.dt.normalize()).win.mean()
    common = ds.index.intersection(dp.index)
    p_w = stats.wilcoxon(ds[common] - dp[common]).pvalue / 2 if len(common) >= 8 else 1.0
    worst = ledger.groupby("stat").win.agg(["mean", "count"])
    worst_bad = worst[(worst["count"] >= 30) & (worst["mean"] < 0.45)]
    print(f"z={z:.2f} p_onesided={p_z:.4f} | paired p={p_w:.4f} | bad stats: {list(worst_bad.index)}")
    if sh > ph and (p_z < 0.10 or p_w < 0.10) and worst_bad.empty:
        verdict = "READY_TO_PROMOTE"
else:
    print(f"need >=15 slates (have {n_days}) and >=100 picks each side")
print(f"VERDICT: {verdict}")
