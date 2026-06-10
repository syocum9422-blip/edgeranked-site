"""Internal MLB Learning Dashboard V2 — single source of truth for MLB model
performance. Admin-only (gated in app.py); never linked, never in sitemap.

Design rules:
  * Graded tracking/archive files only — outcomes are never invented and
    missing data is reported as missing, not estimated.
  * Shadow comparisons use captured side-by-side columns when present; until
    they accumulate, projections (not outcomes) are recomputed through the
    same frozen calibration formulas and clearly labeled as such.
  * All computation cached for CACHE_TTL_S; page renders from cache.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")
MLB = Path("/home/ubuntu/mlb_model")
HITTER_TRACKING = MLB / "mlb" / "outputs" / "hitter_tracking.csv"
PITCHER_TRACKING = MLB / "mlb" / "outputs" / "pitcher_tracking.csv"
HR_GRADES = MLB / "hr_threat" / "graded" / "hr_threat_board_grades.csv"
HR_SUMMARY = MLB / "hr_threat" / "graded" / "hr_threat_board_summary.json"

CACHE_TTL_S = 600
_CACHE: dict = {}

# ---- traffic-light thresholds (configurable) --------------------------------
TH = {
    "tracking_today_min_share": 0.3,     # of slate; below -> RED
    "graded_7d_green": 1500, "graded_7d_yellow": 700,
    "hit_cal_gap_green": 0.02, "hit_cal_gap_yellow": 0.04,  # top-bucket |pred-obs|
    "trend_eps_auc": 0.005, "trend_eps_mae": 0.05, "trend_eps_brier": 0.001,
    "blend_promote_auc_gain": 0.015, "blend_min_rows": 4000,
    "k_cal_8plus_bias_halved": 0.5,
}

# Frozen shadow formulas (mirror mlb_model/calibration/*; duplicated here so a
# webapp restart never imports model-side code).
def _pk_cal(x):
    if x is None or (isinstance(x, float) and x != x):
        return None
    v = float(x)
    if v <= 6.0:
        return v
    if v <= 7.0:
        return 6.0 + (v - 6.0) * 0.85
    if v <= 8.0:
        return 6.85 + (v - 7.0) * 0.55
    return 7.40 + (v - 8.0) * 0.30


def _blend_z(p_pct, xba):
    try:
        p = min(max(float(p_pct) / 100.0, 0.001), 0.999)
        xb = min(max(float(xba), 0.05), 0.45)
    except (TypeError, ValueError):
        return None
    if p != p or xb != xb:
        return None
    p_x = 1.0 - (1.0 - xb) ** 3.9
    return 0.6 * math.log(p / (1 - p)) + 0.4 * math.log(p_x / (1 - p_x))


def _blend_pct(p_pct, xba):
    z = _blend_z(p_pct, xba)
    return None if z is None else 100.0 / (1.0 + math.exp(-z))


def _cal_blend_pct(p_pct, xba):
    z = _blend_z(p_pct, xba)
    if z is None:
        return None
    return min(100.0 / (1.0 + math.exp(-(-0.2701 + 1.0548 * z))), 65.0)


# ------------------------------------------------------------------ metrics --

def _auc(y, p):
    y = np.asarray(y); p = np.asarray(p)
    n1 = int(y.sum()); n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return None
    r = pd.Series(p).rank(method="average").values
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def _brier(y, p):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2)) if len(y) else None


def _windows(df, date_col="date"):
    today = datetime.now(ET).date()
    d = pd.to_datetime(df[date_col]).dt.date
    return {
        "yesterday": df[d == today - timedelta(days=1)],
        "7d": df[d >= today - timedelta(days=7)],
        "prior_7d": df[(d >= today - timedelta(days=14)) & (d < today - timedelta(days=7))],
        "30d": df[d >= today - timedelta(days=30)],
        "season": df,
    }


def _trend(new, old, eps, lower_better=False):
    if new is None or old is None:
        return "→"
    delta = new - old
    if abs(delta) < eps:
        return "→"
    improving = delta < 0 if lower_better else delta > 0
    return "↑" if improving else "↓"


def _light(value, green, yellow, lower_better=False):
    if value is None:
        return "RED"
    if lower_better:
        return "GREEN" if value <= green else ("YELLOW" if value <= yellow else "RED")
    return "GREEN" if value >= green else ("YELLOW" if value >= yellow else "RED")


# ------------------------------------------------------------------ compute --

def _load():
    out = {"missing": []}
    try:
        h = pd.read_csv(HITTER_TRACKING)
        h["date"] = h["date"].astype(str).str.slice(0, 10)
        out["hit_all"] = h
        out["hit"] = h[h["actual_hits"].notna()].copy()
    except Exception as exc:
        out["hit_all"] = out["hit"] = pd.DataFrame()
        out["missing"].append(f"hitter_tracking unreadable: {exc}")
    try:
        p = pd.read_csv(PITCHER_TRACKING)
        p["date"] = p["date"].astype(str).str.slice(0, 10)
        out["pit_all"] = p
        out["pit"] = p[p["actual_strikeouts"].notna() & p["predicted_strikeouts"].notna()].copy()
    except Exception as exc:
        out["pit_all"] = out["pit"] = pd.DataFrame()
        out["missing"].append(f"pitcher_tracking unreadable: {exc}")
    try:
        g = pd.read_csv(HR_GRADES)
        out["hr_grades"] = g
    except Exception as exc:
        out["hr_grades"] = pd.DataFrame()
        out["missing"].append(f"hr_threat_board_grades unreadable: {exc}")
    out["hr_summary"] = None
    try:
        out["hr_summary"] = json.loads(HR_SUMMARY.read_text())
    except Exception:
        out["missing"].append("hr_threat_board_summary.json missing")
    return out


def _hit_metrics(df):
    if df.empty:
        return None
    y = (df["actual_hits"] > 0).astype(int).values
    p = (df["hit_prob"] / 100.0).clip(0.01, 0.99).values
    return {"n": len(df), "hit_rate": round(float(y.mean()), 4), "mean_p": round(float(p.mean()), 4),
            "brier": round(_brier(y, p), 5), "auc": (round(_auc(y, p), 4) if _auc(y, p) is not None else None)}


def _cal_table(df, pcol, ycond, bins):
    if df.empty:
        return []
    p = (df[pcol] / 100.0).values
    y = ycond(df).astype(int).values
    rows = []
    for lo, hi in bins:
        m = (p > lo) & (p <= hi)
        if m.sum() < 10:
            continue
        rows.append({"bucket": f"{int(lo*100)}–{int(hi*100)}%", "n": int(m.sum()),
                     "pred": round(float(p[m].mean()) * 100, 1), "obs": round(float(y[m].mean()) * 100, 1)})
    return rows


def _pitcher_metrics(df):
    if df.empty:
        return None
    e = df["predicted_strikeouts"] - df["actual_strikeouts"]
    corr = df["predicted_strikeouts"].corr(df["actual_strikeouts"]) if len(df) > 5 else None
    return {"n": len(df), "mae": round(float(e.abs().mean()), 3), "bias": round(float(e.mean()), 3),
            "corr": (round(float(corr), 3) if corr is not None and corr == corr else None)}


def _board_stats(g, board, window_df_dates):
    sub = g[(g["board_type"] == board) & (g["graded"] == True) & (g["slate_date"].isin(window_df_dates))]  # noqa: E712
    if sub.empty:
        return {"graded": 0, "hr": 0, "rate": None, "bands": {}}
    bands = {}
    for k in (5, 10, 15, 25):
        b = sub[sub["rank"] <= k]
        bands[f"top_{k}"] = {"n": int(len(b)), "rate": (round(float((b["actual_hr"] > 0).mean()), 3) if len(b) else None)}
    return {"graded": int(len(sub)), "hr": int((sub["actual_hr"] > 0).sum()),
            "rate": round(float((sub["actual_hr"] > 0).mean()), 3), "bands": bands}


def compute_payload():
    src = _load()
    hit, pit, g = src["hit"], src["pit"], src["hr_grades"]
    today = datetime.now(ET).date()
    pay = {"generated_at": datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"), "missing": src["missing"]}

    # --- S1 executive summary
    hw, pw = _windows(hit) if not hit.empty else {}, _windows(pit) if not pit.empty else {}
    hit_today_appended = 0
    if not src["hit_all"].empty:
        hit_today_appended = int((src["hit_all"]["date"] == today.isoformat()).sum())
    graded_today = (len(hw.get("yesterday", [])) if hw else 0)  # grading lags one day by design
    g7 = (len(hw.get("7d", [])) if hw else 0) + (len(pw.get("7d", [])) if pw else 0)
    season_graded = len(hit) + len(pit)
    slate = max(hit_today_appended, 1)
    tracking_ok = hit_today_appended >= max(30, int(slate * TH["tracking_today_min_share"]))
    pay["s1"] = {
        "last_updated": {
            "hitter_tracking": datetime.fromtimestamp(HITTER_TRACKING.stat().st_mtime, ET).strftime("%m-%d %H:%M") if HITTER_TRACKING.exists() else "missing",
            "pitcher_tracking": datetime.fromtimestamp(PITCHER_TRACKING.stat().st_mtime, ET).strftime("%m-%d %H:%M") if PITCHER_TRACKING.exists() else "missing",
            "hr_grades": datetime.fromtimestamp(HR_GRADES.stat().st_mtime, ET).strftime("%m-%d %H:%M") if HR_GRADES.exists() else "missing",
        },
        "graded_yesterday": graded_today, "graded_7d": g7, "graded_season": season_graded,
        "tracking_light": "GREEN" if tracking_ok else "RED",
        "graded_light": _light(g7, TH["graded_7d_green"], TH["graded_7d_yellow"]),
    }

    # --- S2 hit probability
    s2 = {}
    if not hit.empty:
        for w in ("7d", "30d", "season"):
            s2[w] = _hit_metrics(hw[w])
        prior = _hit_metrics(hw["prior_7d"])
        cur = s2["7d"]
        s2["trend_auc"] = _trend(cur and cur["auc"], prior and prior["auc"], TH["trend_eps_auc"])
        s2["trend_brier"] = _trend(cur and cur["brier"], prior and prior["brier"], TH["trend_eps_brier"], lower_better=True)
        s2["cal"] = _cal_table(hw["30d"], "hit_prob", lambda d: d["actual_hits"] > 0,
                               [(0, .45), (.45, .50), (.50, .55), (.55, .60), (.60, .65), (.65, 1)])
        top_gap = next((abs(r["pred"] - r["obs"]) / 100 for r in reversed(s2["cal"]) if r["n"] >= 50), None)
        pay["s1"]["calibration_light"] = _light(top_gap, TH["hit_cal_gap_green"], TH["hit_cal_gap_yellow"], lower_better=True)
        pay["s1"]["calibration_gap"] = top_gap
    pay["s2"] = s2

    # --- S3 total bases (probability product; no TB point projection exists)
    s3 = {}
    if not hit.empty:
        for w in ("7d", "30d", "season"):
            d = hw[w]
            if d.empty:
                s3[w] = None
                continue
            y = (d["actual_tb"] >= 2).astype(int).values
            p = (d["tb2_prob"] / 100.0).clip(0.01, 0.99).values
            corr = pd.Series(p).corr(pd.Series(d["actual_tb"].values))
            s3[w] = {"n": len(d), "brier": round(_brier(y, p), 5), "auc": (lambda a: round(a, 4) if a else None)(_auc(y, p)),
                     "obs_2plus": round(float(y.mean()), 4), "corr_prob_vs_tb": round(float(corr), 3) if corr == corr else None}
        per_day = hit.groupby("date").apply(
            lambda d: _brier((d["actual_tb"] >= 2).astype(int).values, (d["tb2_prob"] / 100.0).values), include_groups=False).dropna()
        if len(per_day) >= 5:
            s3["best_day"] = (per_day.idxmin(), round(float(per_day.min()), 4))
            s3["worst_day"] = (per_day.idxmax(), round(float(per_day.max()), 4))
    pay["s3"] = s3

    # --- S4 HR probability
    s4 = {}
    if not hit.empty:
        for w in ("7d", "30d", "season"):
            d = hw[w]
            if d.empty:
                s4[w] = None
                continue
            y = (d["actual_hr"] > 0).astype(int).values
            p = (d["hr_prob"] / 100.0).clip(0.001, 0.99).values
            dec = pd.Series(p).rank(pct=True).values > 0.9
            s4[w] = {"n": len(d), "brier": round(_brier(y, p), 5), "mean_p": round(float(p.mean()), 4),
                     "obs": round(float(y.mean()), 4), "top_decile_rate": round(float(y[dec].mean()), 4) if dec.sum() else None}
        sea = s4.get("season")
        if sea:
            ratio = sea["mean_p"] / sea["obs"] if sea["obs"] else None
            s4["verdict"] = ("well-calibrated" if ratio and 0.85 <= ratio <= 1.15 else
                             "underconfident" if ratio and ratio < 0.85 else "overconfident")
        s4["cal"] = _cal_table(hw["30d"], "hr_prob", lambda d: d["actual_hr"] > 0,
                               [(0, .02), (.02, .05), (.05, .08), (.08, .12), (.12, .20), (.20, 1)])
    pay["s4"] = s4

    # --- S5 pitcher strikeouts
    s5 = {}
    if not pit.empty:
        for w in ("7d", "30d", "season"):
            s5[w] = _pitcher_metrics(pw[w])
        prior = _pitcher_metrics(pw["prior_7d"])
        s5["trend_mae"] = _trend(s5["7d"] and s5["7d"]["mae"], prior and prior["mae"], TH["trend_eps_mae"], lower_better=True)
        s5["buckets"] = {}
        d30 = pw["30d"]
        for label, lo, hi in (("low (<5)", 0, 5), ("mid (5–7)", 5, 7), ("high (7+)", 7, 99)):
            b = d30[(d30["predicted_strikeouts"] > lo) & (d30["predicted_strikeouts"] <= hi)]
            s5["buckets"][label] = _pitcher_metrics(b)
    pay["s5"] = s5

    # --- S6/7/8 HR boards
    boards = {}
    if not g.empty:
        slates = sorted(g["slate_date"].unique())
        wins = {"yesterday": [str(today - timedelta(days=1))],
                "7d": [s for s in slates if s >= str(today - timedelta(days=7))],
                "30d": [s for s in slates if s >= str(today - timedelta(days=30))],
                "season": slates}
        for board in ("hr_threats", "under_the_radar", "hr_boosts"):
            boards[board] = {w: _board_stats(g, board, ds) for w, ds in wins.items()}
    pay["boards"] = boards

    # --- S9 hitter shadow blend
    s9 = {"captured": False}
    if not hit.empty:
        if "blended_hit_prob" in hit.columns and hit["blended_hit_prob"].notna().sum() >= 100:
            s9["captured"] = True
            d = hit[hit["blended_hit_prob"].notna() & hit["xBA"].notna()].copy()
            d["_b"] = d["blended_hit_prob"]
            d["_cb"] = d["calibrated_blended_hit_prob"]
        else:
            d = hit[hit["xBA"].notna()].copy()
            d["_b"] = [_blend_pct(p, x) for p, x in zip(d["hit_prob"], d["xBA"])]
            d["_cb"] = [_cal_blend_pct(p, x) for p, x in zip(d["hit_prob"], d["xBA"])]
            d = d[d["_b"].notna()]
        if len(d):
            y = (d["actual_hits"] > 0).astype(int).values
            rows = {}
            for name, col in (("raw hit_prob", "hit_prob"), ("blended", "_b"), ("calibrated_blended", "_cb")):
                p = (pd.to_numeric(d[col]) / 100.0).clip(0.01, 0.99).values
                rows[name] = {"n": len(d), "auc": (lambda a: round(a, 4) if a else None)(_auc(y, p)),
                              "brier": round(_brier(y, p), 5), "mean_p": round(float(p.mean()) * 100, 1)}
            s9["rows"] = rows
            aucs = {k: v["auc"] for k, v in rows.items() if v["auc"]}
            s9["winner"] = max(aucs, key=aucs.get) if aucs else None
    pay["s9"] = s9

    # --- S10 pitcher K calibration shadow
    s10 = {"captured": "calibrated_predicted_strikeouts" in pit.columns and pit.get("calibrated_predicted_strikeouts", pd.Series(dtype=float)).notna().sum() >= 50}
    if not pit.empty:
        d = pit.copy()
        if s10["captured"]:
            d = d[d["calibrated_predicted_strikeouts"].notna()]
            d["_c"] = pd.to_numeric(d["calibrated_predicted_strikeouts"])
        else:
            d["_c"] = [_pk_cal(v) for v in d["predicted_strikeouts"]]
        er, ec = d["predicted_strikeouts"] - d["actual_strikeouts"], d["_c"] - d["actual_strikeouts"]
        s10["rows"] = {
            "raw": {"n": len(d), "mae": round(float(er.abs().mean()), 3), "bias": round(float(er.mean()), 3)},
            "calibrated": {"n": len(d), "mae": round(float(ec.abs().mean()), 3), "bias": round(float(ec.mean()), 3)},
        }
        s10["winner"] = "calibrated" if s10["rows"]["calibrated"]["mae"] <= s10["rows"]["raw"]["mae"] else "raw"
    pay["s10"] = s10

    # --- S11 promotion recommendations
    recs = []
    blend_rows = int(hit["blended_hit_prob"].notna().sum()) if (not hit.empty and "blended_hit_prob" in hit.columns) else 0
    if blend_rows >= TH["blend_min_rows"]:
        gain = None
        if s9.get("captured") and s9.get("rows"):
            gain = (s9["rows"]["blended"]["auc"] or 0) - (s9["rows"]["raw hit_prob"]["auc"] or 0)
        verdict = "PROMOTE" if (gain or 0) >= TH["blend_promote_auc_gain"] else "KEEP SHADOW"
    else:
        verdict = "NEEDS DATA"
    recs.append(("Hitter xBA blend (display swap)", verdict,
                 f"{blend_rows} captured shadow rows of {TH['blend_min_rows']} required (gates: hitter_blend_promotion_gates.md)"))
    if s10.get("captured"):
        better = s10["winner"] == "calibrated"
        recs.append(("Pitcher K calibration (display)", "PROMOTE" if better else "ROLL BACK",
                     "captured side-by-side tracking active"))
    else:
        recs.append(("Pitcher K calibration (display)", "KEEP SHADOW",
                     "flag MLB_ENABLE_PITCHER_K_CALIBRATION not enabled; formula-recomputed comparison only"))
    hr_graded = pay["boards"].get("hr_threats", {}).get("season", {}).get("graded", 0)
    hr_slates = int(g["slate_date"].nunique()) if not g.empty else 0
    recs.append(("HR Threat board (public accuracy claims)",
                 "NEEDS DATA" if hr_graded < 1500 or hr_slates < 7 else "PROMOTE",
                 f"{hr_graded} graded players over {hr_slates} slate(s); want ≥1500 over ≥7 slates"))
    utr_graded = pay["boards"].get("under_the_radar", {}).get("season", {}).get("graded", 0)
    recs.append(("Under-the-radar board (public claims)", "NEEDS DATA" if utr_graded < 100 else "PROMOTE",
                 f"{utr_graded} graded of 100 required"))
    pay["s11"] = recs

    # --- S12 daily series for sparklines
    series = {}
    if not hit.empty:
        by = hit.groupby("date")
        series["hit_rate_vs_pred"] = [
            (dt, round(float((d["actual_hits"] > 0).mean()), 3), round(float(d["hit_prob"].mean()) / 100, 3))
            for dt, d in by if len(d) >= 50]
        series["tb2_obs"] = [(dt, round(float((d["actual_tb"] >= 2).mean()), 3), round(float(d["tb2_prob"].mean()) / 100, 3))
                             for dt, d in by if len(d) >= 50]
    if not pit.empty:
        series["k_mae"] = [(dt, round(float((d["predicted_strikeouts"] - d["actual_strikeouts"]).abs().mean()), 2), None)
                           for dt, d in pit.groupby("date") if len(d) >= 5]
    if not g.empty:
        gt = g[(g["board_type"] == "hr_threats") & (g["graded"] == True) & (g["rank"] <= 15)]  # noqa: E712
        series["hr_top15"] = [(dt, round(float((d["actual_hr"] > 0).mean()), 3), None)
                              for dt, d in gt.groupby("slate_date") if len(d) >= 8]
    pay["s12"] = series
    return pay


# ------------------------------------------------------------------- render --

def _chip(light):
    color = {"GREEN": "#22c55e", "YELLOW": "#eab308", "RED": "#ef4444"}.get(light, "#64748b")
    return (f"<span style='display:inline-block;padding:2px 10px;border-radius:999px;font-weight:800;"
            f"font-size:11px;letter-spacing:.06em;background:{color}1f;color:{color};border:1px solid {color}55'>{light}</span>")


def _num(v, nd=3):
    return "—" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def _tbl(head, rows):
    h = "".join(f"<th>{escape(str(c))}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table class='internal-table'><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"


def _spark(points, width=560, height=70, second=False):
    """Inline SVG sparkline. points = [(date, v1, v2|None)]."""
    pts = [(d, a, b) for d, a, b in points if a is not None]
    if len(pts) < 3:
        return "<p class='muted'>Not enough daily data yet.</p>"
    vals = [p[1] for p in pts] + [p[2] for p in pts if p[2] is not None]
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    def xy(i, v):
        return (8 + i * (width - 16) / (len(pts) - 1), height - 12 - (v - lo) / rng * (height - 24))
    def path(idx):
        coords = [xy(i, p[idx]) for i, p in enumerate(pts) if p[idx] is not None]
        return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    svg = [f"<svg viewBox='0 0 {width} {height}' width='100%' height='{height}' role='img'>"]
    svg.append(f"<path d='{path(1)}' fill='none' stroke='#38bdf8' stroke-width='2'/>")
    if second and any(p[2] is not None for p in pts):
        svg.append(f"<path d='{path(2)}' fill='none' stroke='#fbbf24' stroke-width='1.5' stroke-dasharray='4 3'/>")
    svg.append(f"<text x='8' y='{height-2}' font-size='9' fill='#64748b'>{escape(pts[0][0])}</text>")
    svg.append(f"<text x='{width-8}' y='{height-2}' font-size='9' fill='#64748b' text-anchor='end'>{escape(pts[-1][0])}</text>")
    svg.append(f"<text x='{width-8}' y='10' font-size='9' fill='#94a3b8' text-anchor='end'>last {_num(pts[-1][1])}{(' / pred ' + _num(pts[-1][2])) if second and pts[-1][2] is not None else ''}</text>")
    svg.append("</svg>")
    return "".join(svg)


def _sec(title, sub, inner):
    return ("<section class='panel'><div class='panel-head'>"
            f"<h2>{escape(title)}</h2><p class='muted'>{sub}</p></div>{inner}</section>")


def _window_rows(blocks, fields):
    rows = []
    for w in ("7d", "30d", "season"):
        m = blocks.get(w)
        rows.append([w] + ([_num(m.get(f), 4) if isinstance(m.get(f), float) else _num(m.get(f)) for f in fields] if m else ["—"] * len(fields)))
    return rows


def build_body() -> str:
    now = time.time()
    if _CACHE.get("ts", 0) > now - CACHE_TTL_S:
        pay = _CACHE["payload"]
    else:
        pay = compute_payload()
        _CACHE.update(ts=now, payload=pay)

    s1, s2, s3, s4, s5 = pay["s1"], pay["s2"], pay["s3"], pay["s4"], pay["s5"]
    parts = []

    parts.append(
        "<section class='panel internal-banner'><div class='eyebrow'>Internal · Read-only · V2</div>"
        "<h2>MLB Model Performance — single source of truth</h2>"
        f"<p class='muted'>Computed {escape(pay['generated_at'])} from graded tracking + board archives. "
        "Never public, never in sitemap or nav. <a href='/internal/mlb-learning?v=1'>legacy view</a></p></section>")

    lu = s1["last_updated"]
    exec_rows = [
        ["Tracking health (today's append)", _chip(s1["tracking_light"]), f"hitter file {escape(lu['hitter_tracking'])}, pitcher {escape(lu['pitcher_tracking'])}"],
        ["Grading volume (7d)", _chip(s1["graded_light"]), f"{s1['graded_7d']} graded rows"],
        ["Calibration health (hit top bucket)", _chip(s1.get("calibration_light", "RED")), f"gap {_num(s1.get('calibration_gap'), 3)}"],
        ["Graded yesterday / 7d / season", f"{s1['graded_yesterday']} / {s1['graded_7d']} / {s1['graded_season']}", f"HR grades file {escape(lu['hr_grades'])}"],
    ]
    parts.append(_sec("1 · Executive summary", "Thirty-second answer: lights green and arrows up = products improving.",
                      _tbl(["check", "status", "detail"], exec_rows)))

    if s2:
        inner = _tbl(["window", "n", "hit rate", "mean p", "Brier", "AUC"],
                     [[w, m["n"], _num(m["hit_rate"], 3), _num(m["mean_p"], 3), _num(m["brier"], 4), _num(m["auc"], 4)]
                      for w, m in ((x, s2[x]) for x in ("7d", "30d", "season")) if m])
        inner += f"<p>7d trend vs prior 7d: AUC {s2['trend_auc']} · Brier {s2['trend_brier']}</p>"
        inner += _tbl(["bucket (30d)", "n", "predicted %", "observed %"],
                      [[r["bucket"], r["n"], r["pred"], r["obs"]] for r in s2.get("cal", [])])
        parts.append(_sec("2 · Hit probability", "hitter_tracking.csv · graded rows only", inner))

    if s3:
        inner = _tbl(["window", "n", "Brier (2+TB)", "AUC", "obs 2+TB rate", "corr(p, actual TB)"],
                     _window_rows(s3, ["n", "brier", "auc", "obs_2plus", "corr_prob_vs_tb"]))
        if "best_day" in s3:
            inner += (f"<p class='muted'>Best day (Brier): {escape(str(s3['best_day'][0]))} ({s3['best_day'][1]}) · "
                      f"Worst: {escape(str(s3['worst_day'][0]))} ({s3['worst_day'][1]})</p>")
        inner += "<p class='muted'>Note: only a 2+ total-bases <em>probability</em> is published; no TB point projection exists in tracking, so MAE/RMSE against TB counts are not computable (see §missing-data).</p>"
        parts.append(_sec("3 · Total bases (2+ TB probability)", "hitter_tracking.csv actual_tb", inner))

    if s4:
        inner = _tbl(["window", "n", "Brier", "mean p", "obs HR rate", "top-decile HR rate"],
                     _window_rows(s4, ["n", "brier", "mean_p", "obs", "top_decile_rate"]))
        inner += f"<p><strong>Verdict (season): {escape(s4.get('verdict', '—'))}</strong> (mean predicted vs observed)</p>"
        inner += _tbl(["bucket (30d)", "n", "predicted %", "observed %"],
                      [[r["bucket"], r["n"], r["pred"], r["obs"]] for r in s4.get("cal", [])])
        parts.append(_sec("4 · Home run probability", "hitter_tracking.csv actual_hr", inner))

    if s5:
        inner = _tbl(["window", "n", "MAE", "bias", "corr"],
                     _window_rows(s5, ["n", "mae", "bias", "corr"]))
        inner += f"<p>7d MAE trend vs prior 7d: {s5['trend_mae']}</p>"
        inner += _tbl(["projected-K bucket (30d)", "n", "MAE", "bias"],
                      [[lbl, m["n"], _num(m["mae"]), _num(m["bias"])] for lbl, m in s5.get("buckets", {}).items() if m])
        parts.append(_sec("5 · Pitcher strikeouts", "pitcher_tracking.csv", inner))

    board_titles = {"hr_threats": ("6 · HR Threat board", "hr_threat_board_grades.csv (archived pre-game boards, outcome-graded)"),
                    "under_the_radar": ("7 · Under-the-radar HR board", "20-player additive board — graded separately"),
                    "hr_boosts": ("8 · HR Boost board", "boost-ranked view of the full slate")}
    for board, (title, sub) in board_titles.items():
        b = pay["boards"].get(board)
        if not b:
            parts.append(_sec(title, sub, "<p class='muted'>No graded board data yet.</p>"))
            continue
        rows = []
        for w in ("yesterday", "7d", "30d", "season"):
            st = b[w]
            band = st["bands"]
            rows.append([w, st["graded"], st["hr"], _num(st["rate"], 3)] +
                        [f"{band.get(f'top_{k}', {}).get('rate', None) if band else None}".replace("None", "—") for k in (5, 10, 15, 25)])
        parts.append(_sec(title, sub, _tbl(["window", "graded", "HR", "rate", "top5", "top10", "top15", "top25"], rows)))

    s9 = pay["s9"]
    if s9.get("rows"):
        label = ("captured shadow columns" if s9["captured"]
                 else "projections recomputed through the frozen blend formulas on graded rows (capture columns start accumulating 2026-06-11; outcomes are real, never estimated)")
        inner = f"<p class='muted'>Source: {escape(label)}.</p>"
        inner += _tbl(["variant", "n", "AUC", "Brier", "mean p%"],
                      [[("<strong>" + k + " ←</strong>" if k == s9.get("winner") else k), v["n"], _num(v["auc"], 4), _num(v["brier"], 5), _num(v["mean_p"], 1)]
                       for k, v in s9["rows"].items()])
        parts.append(_sec("9 · Hitter shadow blend", "raw vs blended vs calibrated_blended (winner by AUC)", inner))

    s10 = pay["s10"]
    if s10.get("rows"):
        label = ("captured side-by-side tracking" if s10["captured"]
                 else "calibration formula applied retroactively to graded raw projections (flag not yet enabled; outcomes real)")
        inner = f"<p class='muted'>Source: {escape(label)}.</p>"
        inner += _tbl(["variant", "n", "MAE", "bias"],
                      [[("<strong>" + k + " ←</strong>" if k == s10.get("winner") else k), v["n"], _num(v["mae"]), _num(v["bias"])]
                       for k, v in s10["rows"].items()])
        parts.append(_sec("10 · Pitcher K calibration shadow", "raw vs piecewise-calibrated projection (winner by MAE)", inner))

    rec_rows = [[escape(n), _chip({"PROMOTE": "GREEN", "KEEP SHADOW": "YELLOW", "NEEDS DATA": "YELLOW", "ROLL BACK": "RED"}.get(v, "RED")) + f" <strong>{escape(v)}</strong>", escape(d)] for n, v, d in pay["s11"]]
    parts.append(_sec("11 · Promotion recommendations", "Advisory, derived from the documented promotion gates. Promotion is always a manual operator action.",
                      _tbl(["candidate", "verdict", "basis"], rec_rows)))

    s12 = pay["s12"]
    charts = [("Hits — daily observed hit rate (blue) vs mean predicted (amber)", s12.get("hit_rate_vs_pred", []), True),
              ("Total bases — daily observed 2+TB rate vs predicted", s12.get("tb2_obs", []), True),
              ("Strikeouts — daily MAE (lower is better)", s12.get("k_mae", []), False),
              ("HR Threats — daily top-15 HR rate", s12.get("hr_top15", []), False)]
    inner = "".join(f"<h3 style='margin:14px 0 4px;font-size:13px'>{escape(t)}</h3>{_spark(pts, second=two)}" for t, pts, two in charts)
    parts.append(_sec("12 · Historical trends", "Daily series, full graded history (note Apr 14 – May 29 blackout gap).", inner))

    if pay["missing"]:
        parts.append(_sec("Missing data sources", "Reported, never estimated.",
                          "<ul>" + "".join(f"<li>{escape(m)}</li>" for m in pay["missing"]) + "</ul>"))

    parts.append(
        "<style>.internal-banner{border:1px solid rgba(245,158,11,.35);background:linear-gradient(180deg,rgba(245,158,11,.10) 0%,rgba(15,23,42,.92) 100%)}"
        ".internal-banner .eyebrow{color:#fcd34d}"
        ".internal-table{width:100%;border-collapse:collapse;font-size:13px;margin:8px 0}"
        ".internal-table th,.internal-table td{padding:7px 10px;border-bottom:1px solid rgba(30,41,59,.7);text-align:left}"
        ".internal-table th{color:var(--muted);font-size:11px;letter-spacing:.08em;text-transform:uppercase;font-weight:800}"
        ".internal-table td{color:#e2e8f0;font-variant-numeric:tabular-nums}"
        ".internal-table tr:hover td{background:rgba(15,23,42,.6)}</style>")
    return "".join(parts)
