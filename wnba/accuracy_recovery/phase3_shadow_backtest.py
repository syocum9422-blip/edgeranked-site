#!/usr/bin/env python3
"""Phase 3 — shadow replay backtest over the full offered prop pool.

Honest point-in-time replay:
  * board = archived same-day projections (what production actually published)
  * lines = prop_open_close close_line (full PrizePicks universe, Jun 11 - Jul 9)
  * variance-inflation factors fit ONLY on trailing 21 days of board-vs-actual data
  * grading vs player_games actuals; DNP rows voided (PrizePicks void rule)

READ-ONLY vs production. Writes reports to accuracy_recovery/reports/.
"""
import glob
import json
import os

import numpy as np
import pandas as pd
from scipy import stats

ROOT = "/home/ubuntu/EdgeRanked/sports/wnba"
OUT = os.path.join(ROOT, "accuracy_recovery/reports")

MK = {"points": "PTS", "rebounds": "REB", "assists": "AST", "threes_made": "FG3M",
      "steals": "STL", "blocks": "BLK", "pra": "PRA", "pr": "PR", "pa": "PA", "ra": "RA"}
ACT = {"points": "points", "rebounds": "rebounds", "assists": "assists",
       "threes_made": "threes_made", "steals": "steals", "blocks": "blocks"}
COMBO_PARTS = {"pra": ["points", "rebounds", "assists"], "pr": ["points", "rebounds"],
               "pa": ["points", "assists"], "ra": ["rebounds", "assists"]}
MIN_HIT_RATE, MIN_EDGE, TOP_N = 0.56, 0.04, 45  # mirror production gates + typical daily volume

# ---------------------------------------------------------------- load
pg = pd.read_csv(f"{ROOT}/data/raw/wnba_player_games.csv", parse_dates=["game_date"])
for c, parts in COMBO_PARTS.items():
    pg[c] = sum(pg[p] for p in parts)

boards = {}
for f in sorted(glob.glob(f"{ROOT}/outputs/archive/projections/wnba_projections_2026*.csv")):
    day = pd.to_datetime(os.path.basename(f)[17:25])
    try:
        b = pd.read_csv(f)
    except Exception:
        continue
    if "PLAYER_KEY" in b.columns:
        boards[day] = b

lines = pd.read_csv(f"{ROOT}/wnba_v2/data/line_history/prop_open_close.csv", parse_dates=["date"])
lines = lines[lines.stat.isin(MK)].copy()
lines["player_key"] = lines.player_name.str.lower().str.strip()

# point-in-time starter history for the role-change guard
pg_sorted = pg.sort_values("game_date")

# ---------------------------------------------------- trailing variance inflation
def trailing_inflation(day, window=21):
    """per-market std multiplier = std of realized z over trailing window (board vs actual)."""
    lo = day - pd.Timedelta(days=window)
    zs = {m: [] for m in MK}
    for d, b in boards.items():
        if not (lo <= d < day):
            continue
        act = pg[pg.game_date == d]
        m = b.merge(act, left_on="PLAYER_KEY", right_on="player_key")
        m = m[m.minutes > 0]
        for mk, K in MK.items():
            col = mk if mk in COMBO_PARTS else ACT.get(mk)
            pcol, scol = f"{K}_PROJ", f"SIM_{K}_STD"
            if col in m.columns and pcol in m.columns and scol in m.columns:
                z = (m[col] - m[pcol]) / m[scol].clip(lower=0.25)
                zs[mk].extend(z.dropna().tolist())
    return {mk: (np.std(v) if len(v) >= 60 else np.nan) for mk, v in zs.items()}

# global fallback (median of per-day factors, computed cumulatively; only used when trailing sparse)
def role_flip_players(day, lookback=10, min_games=8):
    """players whose starter status flipped in last `lookback` days, or <8 games with team."""
    hist = pg_sorted[pg_sorted.game_date < day]
    recent = hist[hist.game_date >= day - pd.Timedelta(days=lookback)]
    flagged = set()
    for pk, g in recent.groupby("player_key"):
        if g.starter.nunique() > 1:
            prior = hist[(hist.player_key == pk) & (hist.game_date < g.game_date.min())].tail(5)
            if len(prior) and abs(g.starter.iloc[-1] - prior.starter.mean()) > 0.5:
                flagged.add(pk)
    games_with_team = hist[hist.game_date >= "2026-05-01"].groupby(["player_key", "team"]).size()
    for (pk, tm), n in games_with_team.items():
        pass  # handled below vectorised
    few = hist[hist.game_date >= "2026-05-01"].groupby("player_key").size()
    flagged |= set(few[few < min_games].index)
    return flagged

# ---------------------------------------------------------------- score pool
rows = []
for day in sorted(lines.date.unique()):
    day = pd.Timestamp(day)
    if day not in boards:
        continue
    b = boards[day].copy()
    b["player_key"] = b.PLAYER_KEY.str.lower().str.strip()
    infl = trailing_inflation(day)
    infl_med = np.nanmedian(list(infl.values()))
    guard = role_flip_players(day)
    day_lines = lines[lines.date == day]
    act = pg[pg.game_date == day].set_index("player_key")

    for _, r in day_lines.iterrows():
        K = MK[r.stat]
        row_b = b[b.player_key == r.player_key]
        if row_b.empty:
            continue
        row_b = row_b.iloc[0]
        proj, sd = row_b.get(f"{K}_PROJ"), row_b.get(f"SIM_{K}_STD")
        if pd.isna(proj) or pd.isna(sd) or sd <= 0:
            continue
        line = r.close_line if pd.notna(r.close_line) else r.open_line
        if pd.isna(line):
            continue
        # actual + void handling
        if r.player_key not in act.index:
            continue
        a = act.loc[r.player_key]
        if isinstance(a, pd.DataFrame):
            a = a.iloc[0]
        if a.minutes <= 0 or not bool(a.played):
            continue
        actual = a[r.stat] if r.stat in a.index else np.nan
        if pd.isna(actual) or actual == line:
            continue

        f = infl.get(r.stat)
        if pd.isna(f):
            f = infl_med if not np.isnan(infl_med) else 1.8
        p_over_raw = 1 - stats.norm.cdf((line - proj) / max(sd, 0.25))
        p_over_adj = 1 - stats.norm.cdf((line - proj) / max(sd * f, 0.25))
        rows.append({
            "date": day, "player_key": r.player_key, "stat": r.stat,
            "combo": r.stat in COMBO_PARTS, "line": line, "proj": proj, "sd": sd,
            "infl": f, "p_over_raw": p_over_raw, "p_over_adj": p_over_adj,
            "actual": actual, "over_hits": int(actual > line),
            "role_guard": r.player_key in guard,
            "line_move": r.line_move if pd.notna(r.line_move) else 0.0,
        })

pool = pd.DataFrame(rows)
pool.to_csv(f"{OUT}/replay_pool.csv", index=False)
print(f"pool: {len(pool)} scored props over {pool.date.nunique()} days "
      f"({pool.date.min().date()}..{pool.date.max().date()})")

# ---------------------------------------------------------------- strategies
def select(pool, prob_col, singles_only=False, cap=None, guard=False):
    d = pool.copy()
    d["p_pick"] = np.where(d[prob_col] >= 0.5, d[prob_col], 1 - d[prob_col])
    d["side"] = np.where(d[prob_col] >= 0.5, "over", "under")
    d["win"] = np.where(d.side == "over", d.over_hits, 1 - d.over_hits)
    d = d[(d.p_pick >= MIN_HIT_RATE) & (d.p_pick - 0.5 >= MIN_EDGE)]
    if singles_only:
        d = d[~d.combo]
    if cap is not None:
        d = d[d.p_pick <= cap]
    if guard:
        d = d[~d.role_guard]
    return d.sort_values("p_pick", ascending=False).groupby("date").head(TOP_N)

strategies = {
    "BASELINE (raw sim probs, production-like)": select(pool, "p_over_raw"),
    "C1 variance-honesty": select(pool, "p_over_adj"),
    "C2 singles-only (raw)": select(pool, "p_over_raw", singles_only=True),
    "C3 tail-cap 0.70 (raw)": select(pool, "p_over_raw", cap=0.70),
    "C6 role-guard (raw)": select(pool, "p_over_raw", guard=True),
    "C1+C3": select(pool, "p_over_adj", cap=0.70),
    "C1+C2": select(pool, "p_over_adj", singles_only=True),
    "C1+C2+C6": select(pool, "p_over_adj", singles_only=True, guard=True),
    "C1+C3+C6": select(pool, "p_over_adj", cap=0.70, guard=True),
}

base = strategies["BASELINE (raw sim probs, production-like)"]

def daily_paired_test(a, b):
    da = a.groupby("date").win.mean()
    db = b.groupby("date").win.mean()
    common = da.index.intersection(db.index)
    if len(common) < 8:
        return np.nan
    try:
        return stats.wilcoxon(db[common] - da[common]).pvalue
    except ValueError:
        return np.nan

results = []
for name, s in strategies.items():
    if len(s) == 0:
        continue
    hr = s.win.mean()
    brier = ((s.p_pick - s.win) ** 2).mean()
    ece = abs(s.p_pick.mean() - hr)
    binom_p = stats.binomtest(int(s.win.sum()), len(s), 0.5).pvalue
    n1, n2 = len(base), len(s)
    pp = (base.win.sum() + s.win.sum()) / (n1 + n2)
    se = np.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2))
    z_vs_base = (hr - base.win.mean()) / se if se > 0 else np.nan
    results.append({
        "strategy": name, "n": len(s), "picks/day": round(len(s) / s.date.nunique(), 1),
        "hit_rate": round(hr, 4), "brier": round(brier, 4), "ece": round(ece, 4),
        "combo_share": round(s.combo.mean(), 3),
        "p_binom_vs_coinflip": round(binom_p, 5),
        "z_vs_baseline": round(z_vs_base, 2) if not np.isnan(z_vs_base) else np.nan,
        "p_paired_daily_vs_baseline": round(daily_paired_test(base, s), 5)
        if not np.isnan(daily_paired_test(base, s)) else np.nan,
    })
res = pd.DataFrame(results)
res.to_csv(f"{OUT}/phase3_strategy_comparison.csv", index=False)
print(res.to_string(index=False))

# per-market hit rate per strategy
per_mkt = {}
for name, s in strategies.items():
    if len(s):
        per_mkt[name] = s.groupby("stat").win.agg(["mean", "count"]).round(3)
with open(f"{OUT}/phase3_per_market.txt", "w") as fh:
    for name, t in per_mkt.items():
        fh.write(f"\n=== {name} ===\n{t.to_string()}\n")

# calibration of adjusted probs (C1)
c1 = strategies["C1 variance-honesty"]
cal = c1.groupby(pd.cut(c1.p_pick, [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 1.0])).win.agg(["mean", "count"])
cal.to_csv(f"{OUT}/phase3_c1_calibration.csv")
print("\nC1 calibration (pred bucket -> actual):")
print(cal.round(3).to_string())

# validation: does baseline replay reproduce production's live results?
gb = pd.read_csv(f"{ROOT}/Best_Bets/graded_bets.csv", parse_dates=["bet_date"])
gb = gb[(gb.sportsbook == "prizepicks") & gb.bet_result.isin(["win", "loss"])]
gb = gb[(gb.bet_date >= pool.date.min()) & (gb.bet_date <= pool.date.max())]
print(f"\nvalidation: production live hit rate same window = "
      f"{(gb.bet_result == 'win').mean():.4f} (n={len(gb)}) "
      f"vs baseline replay = {base.win.mean():.4f} (n={len(base)})")
