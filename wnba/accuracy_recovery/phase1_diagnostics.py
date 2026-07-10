#!/usr/bin/env python3
"""Phase 1 — WNBA accuracy-decline root-cause diagnostics.

READ-ONLY: consumes graded history + archives, writes reports to
accuracy_recovery/reports/. Never touches production outputs, models, or crons.
"""
import glob
import json
import os
import warnings

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

ROOT = "/home/ubuntu/EdgeRanked/sports/wnba"
OUT = os.path.join(ROOT, "accuracy_recovery/reports")
os.makedirs(OUT, exist_ok=True)

CUTOVER = pd.Timestamp("2026-06-08")  # early(good) vs late(bad) split, from weekly hit-rate inflection

# ---------------------------------------------------------------- load
bets = pd.read_csv(f"{ROOT}/Best_Bets/graded_bets.csv", parse_dates=["bet_date"])
bets = bets[(bets.sportsbook == "prizepicks") & bets.bet_result.isin(["win", "loss"])].copy()
bets = bets[bets.bet_date >= "2026-05-01"]
bets["win"] = (bets.bet_result == "win").astype(int)
bets["p"] = bets.hit_rate.clip(0.01, 0.99)
bets["late"] = bets.bet_date >= CUTOVER

led = pd.read_csv(f"{ROOT}/learning/graded_predictions_ledger.csv", parse_dates=["date"])
led = led[led.result.isin(["win", "loss"])].copy()
led["win"] = (led.result == "win").astype(int)
led["late"] = led.date >= CUTOVER

pg = pd.read_csv(f"{ROOT}/data/raw/wnba_player_games.csv", parse_dates=["game_date"])
tc = pd.read_csv(f"{ROOT}/data/raw/wnba_team_context.csv", parse_dates=["game_date"])

report = {}

def sig_diff(a_wins, b_wins):
    """two-proportion z-test p-value"""
    n1, n2 = len(a_wins), len(b_wins)
    if n1 < 10 or n2 < 10:
        return np.nan
    p1, p2 = a_wins.mean(), b_wins.mean()
    p = (a_wins.sum() + b_wins.sum()) / (n1 + n2)
    se = np.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return np.nan
    return 2 * (1 - stats.norm.cdf(abs(p1 - p2) / se))

# ============================================================ 1. MODEL DRIFT
daily = bets.groupby(bets.bet_date.dt.date).apply(
    lambda g: pd.Series({
        "n": len(g),
        "hit_rate": g.win.mean(),
        "brier": ((g.p - g.win) ** 2).mean(),
        "log_loss": -(g.win * np.log(g.p) + (1 - g.win) * np.log(1 - g.p)).mean(),
        "mean_pred_p": g.p.mean(),
        "overconfidence": g.p.mean() - g.win.mean(),
    })
)
daily.to_csv(f"{OUT}/daily_metrics.csv")

# board-level MAE per stat from archived projections joined to actuals
STATS = {"PTS": "points", "REB": "rebounds", "AST": "assists", "MIN": "minutes",
         "FG3M": "threes_made", "STL": "steals", "BLK": "blocks"}
rows = []
for f in sorted(glob.glob(f"{ROOT}/outputs/archive/projections/wnba_projections_2026*.csv")):
    day = pd.to_datetime(os.path.basename(f)[17:25])
    try:
        pr = pd.read_csv(f)
    except Exception:
        continue
    if "PLAYER_KEY" not in pr.columns:
        continue
    act = pg[pg.game_date == day]
    m = pr.merge(act, left_on="PLAYER_KEY", right_on="player_key", how="inner")
    m = m[m.minutes > 0]
    if len(m) < 5:
        continue
    row = {"date": day, "n": len(m)}
    for k, col in STATS.items():
        pcol = f"{k}_PROJ"
        if pcol in m.columns and col in m.columns:
            e = m[pcol] - m[col]
            row[f"{k}_mae"] = e.abs().mean()
            row[f"{k}_bias"] = e.mean()
            row[f"{k}_rmse"] = np.sqrt((e ** 2).mean())
    rows.append(row)
board = pd.DataFrame(rows).set_index("date").sort_index()
board.to_csv(f"{OUT}/board_error_by_day.csv")

wk = board.resample("W").mean()
report["board_weekly_mae"] = wk[[c for c in wk.columns if c.endswith("_mae")]].round(3).to_dict("index")

# early vs late board errors
b_early, b_late = board[board.index < CUTOVER], board[board.index >= CUTOVER]
report["board_early_vs_late"] = {
    k: {"early_mae": round(b_early[f"{k}_mae"].mean(), 3), "late_mae": round(b_late[f"{k}_mae"].mean(), 3),
        "early_bias": round(b_early[f"{k}_bias"].mean(), 3), "late_bias": round(b_late[f"{k}_bias"].mean(), 3)}
    for k in STATS if f"{k}_mae" in board.columns
}

# hit-rate change + significance
e, l = bets[~bets.late], bets[bets.late]
report["headline"] = {
    "early_window": f"2026-05-01..{(CUTOVER - pd.Timedelta(days=1)).date()}",
    "late_window": f"{CUTOVER.date()}..{bets.bet_date.max().date()}",
    "early_hit_rate": round(e.win.mean(), 4), "early_n": len(e),
    "late_hit_rate": round(l.win.mean(), 4), "late_n": len(l),
    "p_value": round(sig_diff(e.win, l.win), 5),
    "early_brier": round(((e.p - e.win) ** 2).mean(), 4),
    "late_brier": round(((l.p - l.win) ** 2).mean(), 4),
    "early_overconf": round(e.p.mean() - e.win.mean(), 4),
    "late_overconf": round(l.p.mean() - l.win.mean(), 4),
}

# ============================================================ 2. FEATURE DRIFT
drift_rows = []
def ks_drift(name, s_early, s_late):
    s_early, s_late = s_early.dropna(), s_late.dropna()
    if len(s_early) < 30 or len(s_late) < 30:
        return
    ks, p = stats.ks_2samp(s_early, s_late)
    drift_rows.append({"feature": name, "early_mean": s_early.mean(), "late_mean": s_late.mean(),
                       "early_std": s_early.std(), "late_std": s_late.std(),
                       "ks": ks, "p_value": p, "n_early": len(s_early), "n_late": len(s_late)})

for col in ["line", "projection_mean", "projected_minutes", "hit_rate", "edge", "STDDEV",
            "line_move", "confidence_score", "bet_quality_score"]:
    if col in bets.columns:
        ks_drift(f"bets.{col}", e[col].astype(float), l[col].astype(float))

le, ll = led[~led.late], led[led.late]
for col in ["projection", "minutes_projected", "minutes_played", "rest_days", "confidence_score", "predicted_hit_rate"]:
    ks_drift(f"ledger.{col}", le[col].astype(float), ll[col].astype(float))

# minutes model error drift (the known Phase-3A weak spot)
led["min_err"] = led.minutes_projected - led.minutes_played
ks_drift("ledger.minutes_error", le.minutes_projected - le.minutes_played,
         ll.minutes_projected - ll.minutes_played)

# league environment drift from actuals
pg26 = pg[pg.game_date >= "2026-05-01"].copy()
pg26["late"] = pg26.game_date >= CUTOVER
pe, pl_ = pg26[~pg26.late], pg26[pg26.late]
for col in ["minutes", "points", "rebounds", "assists", "threes_made", "fga", "fta"]:
    ks_drift(f"actuals.{col}", pe[pe.minutes > 0][col], pl_[pl_.minutes > 0][col])
tc26 = tc[tc.game_date >= "2026-05-01"].copy()
tc26["late"] = tc26.game_date >= CUTOVER
for col in ["pace", "off_rating", "def_rating", "team_points"]:
    ks_drift(f"team_context.{col}", tc26[~tc26.late][col], tc26[tc26.late][col])

drift = pd.DataFrame(drift_rows).sort_values("p_value")
drift.to_csv(f"{OUT}/feature_drift.csv", index=False)
report["feature_drift_flagged"] = drift[drift.p_value < 0.01].round(4).to_dict("records")

# ============================================================ 3. ERROR BREAKDOWN
def seg_table(df, key):
    t = df.groupby(key).apply(lambda g: pd.Series({
        "n": len(g), "hit": g.win.mean(),
        "early_hit": g.loc[~g.late, "win"].mean(), "early_n": (~g.late).sum(),
        "late_hit": g.loc[g.late, "win"].mean(), "late_n": g.late.sum(),
    }))
    t["delta"] = t.late_hit - t.early_hit
    t["p_value"] = [sig_diff(df[(df[key] == i) & ~df.late].win, df[(df[key] == i) & df.late].win)
                    if not isinstance(key, list) else np.nan for i in t.index]
    return t.sort_values("delta")

bets["min_bucket"] = pd.cut(bets.projected_minutes, [0, 15, 22, 28, 32, 45],
                            labels=["<15", "15-22", "22-28", "28-32", "32+"])
bets["proj_bucket"] = pd.cut(bets.projection_mean, [0, 2, 5, 10, 15, 20, 60],
                             labels=["0-2", "2-5", "5-10", "10-15", "15-20", "20+"])
bets["dow"] = bets.bet_date.dt.day_name()
bets["month"] = bets.bet_date.dt.month

# starter + home/away joins
pgs = pg[["game_date", "player_key", "starter", "is_home", "position"]].copy()
bets["player_key"] = bets.player_name.str.lower().str.strip()
bets = bets.merge(pgs, left_on=["bet_date", "player_key"], right_on=["game_date", "player_key"], how="left")

segments = {}
for key in ["stat", "side", "min_bucket", "proj_bucket", "month", "dow", "team", "opponent",
            "starter", "is_home", "position", "confidence"]:
    if key in bets.columns:
        segments[key] = seg_table(bets, key)
for k, t in segments.items():
    t.round(4).to_csv(f"{OUT}/seg_{k}.csv")

report["worst_deteriorating_segments"] = {
    k: t[(t.early_n >= 30) & (t.late_n >= 30)].nsmallest(3, "delta")[["early_hit", "late_hit", "delta", "p_value", "late_n"]].round(3).to_dict("index")
    for k, t in segments.items() if k in ["stat", "side", "min_bucket", "proj_bucket", "team", "opponent"]
}

# ============================================================ 4. CALIBRATION
buckets = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.75), (0.75, 1.01)]
cal_rows = []
for w, d in [("early", e), ("late", l), ("all", bets)]:
    for lo, hi in buckets:
        m = d[(d.p >= lo) & (d.p < hi)]
        if len(m) == 0:
            continue
        cal_rows.append({"window": w, "bucket": f"{int(lo*100)}-{int(hi*100) if hi<1 else '100'}%",
                         "n": len(m), "mean_pred": round(m.p.mean(), 4),
                         "actual": round(m.win.mean(), 4),
                         "cal_error": round(m.p.mean() - m.win.mean(), 4)})
cal = pd.DataFrame(cal_rows)
cal.to_csv(f"{OUT}/calibration.csv", index=False)
report["calibration"] = cal.to_dict("records")
# below-50 bucket sanity (bets should all be >=50 predicted, verify)
report["preds_below_50pct"] = int((bets.p < 0.50).sum())

# ============================================================ 5. RESIDUAL ANALYSIS
led2 = led.dropna(subset=["minutes_projected", "minutes_played"]).copy()
led2["min_err"] = led2.minutes_projected - led2.minutes_played
led2["abs_min_err"] = led2.min_err.abs()

res = {}
# minutes error -> outcome
led2["min_err_bucket"] = pd.cut(led2.min_err, [-40, -8, -4, -1, 1, 4, 8, 40],
                                labels=["<-8", "-8..-4", "-4..-1", "-1..1", "1..4", "4..8", ">8"])
res["win_by_minutes_error"] = led2.groupby("min_err_bucket").agg(
    n=("win", "size"), hit=("win", "mean")).round(3).to_dict("index")
# correlation of |minutes error| with loss
r, p = stats.pointbiserialr(led2.win, led2.abs_min_err)
res["abs_min_err_vs_win"] = {"r": round(r, 4), "p": round(p, 6)}

# rest / b2b
if led2.rest_days.notna().sum() > 100:
    led2["b2b"] = led2.rest_days <= 1
    res["win_by_b2b"] = led2.groupby("b2b").agg(n=("win", "size"), hit=("win", "mean")).round(3).to_dict("index")

# blowouts: final margin from team context
marg = tc[["game_date", "team", "team_points", "opp_points"]].copy()
marg["margin"] = (marg.team_points - marg.opp_points).abs()
led3 = led2.merge(marg[["game_date", "team", "margin"]], left_on=["date", "team"],
                  right_on=["game_date", "team"], how="left")
led3["blowout"] = led3.margin >= 18
if led3.blowout.notna().sum() > 100:
    res["win_by_blowout"] = led3.groupby("blowout").agg(n=("win", "size"), hit=("win", "mean")).round(3).to_dict("index")
    res["min_err_by_blowout"] = led3.groupby("blowout").min_err.agg(["mean", "count"]).round(3).to_dict("index")

# rookies / new players (first appearance in 2026)
first_seen = pg.groupby("player_key").game_date.min()
new26 = set(first_seen[first_seen >= "2026-05-01"].index)
led2["new_player"] = led2.player_key.isin(new26)
res["win_by_new_player"] = led2.groupby("new_player").agg(n=("win", "size"), hit=("win", "mean")).round(3).to_dict("index")

# new starters: started late window but mostly bench early
st = pg26.groupby(["player_key", "late"]).starter.mean().unstack()
if st.shape[1] == 2:
    new_starters = set(st[(st[False] < 0.3) & (st[True] > 0.7)].dropna().index)
    led2["new_starter"] = led2.player_key.isin(new_starters)
    res["win_by_new_starter"] = led2.groupby("new_starter").agg(n=("win", "size"), hit=("win", "mean")).round(3).to_dict("index")
    res["new_starters"] = sorted(new_starters)

report["residuals"] = res
json.dump(res, open(f"{OUT}/residuals.json", "w"), indent=2, default=str)

# ============================================================ 6. PLAYER ANALYSIS
led_pts = led[led.market == "points"].dropna(subset=["projection_error"])
pl_err = led.groupby("player").agg(
    n=("win", "size"), hit=("win", "mean"),
    mean_signed_err=("projection_error", "mean"),
    mae=("absolute_error", "mean")).query("n >= 8")
pl_err.sort_values("mean_signed_err", ascending=False).head(25).round(3).to_csv(f"{OUT}/top25_overestimated.csv")
pl_err.sort_values("mean_signed_err").head(25).round(3).to_csv(f"{OUT}/top25_underestimated.csv")
report["top10_overestimated"] = pl_err.sort_values("mean_signed_err", ascending=False).head(10).round(2).to_dict("index")
report["top10_underestimated"] = pl_err.sort_values("mean_signed_err").head(10).round(2).to_dict("index")

team_bias = led.groupby("team").agg(n=("win", "size"), hit=("win", "mean"),
                                    signed_err=("projection_error", "mean")).query("n >= 30")
team_bias.round(3).to_csv(f"{OUT}/team_bias.csv")
report["team_bias"] = team_bias.round(3).to_dict("index")

def _keyfix(o):
    if isinstance(o, dict):
        return {str(k): _keyfix(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_keyfix(v) for v in o]
    return o

json.dump(_keyfix(report), open(f"{OUT}/phase1_report.json", "w"), indent=2, default=str)
print("PHASE 1 COMPLETE")
print(json.dumps(report["headline"], indent=2))
