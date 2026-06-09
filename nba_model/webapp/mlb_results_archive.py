"""MLB Results Archive — permanent, SEO-indexable historical slate pages.

Read-only. This module never runs models, simulations, or grading. It only
*consumes* already-published artifacts:

  * ``hitter_tracking.csv``   -> hr_prob / hit_prob projections + actual_hr / actual_hits
  * ``pitcher_tracking.csv``  -> predicted_strikeouts vs actual_strikeouts
  * ``hitter_summary_today.csv`` (current slate) -> best-effort player -> team lookup

It builds:
  * ``/mlb/results``              — master archive hub (newest dates first)
  * ``/mlb/results/YYYY-MM-DD``   — one permanent page per graded slate

All page chrome (canonical, robots, og/twitter) comes from the host app's
``render_layout``; Article + Breadcrumb JSON-LD is injected into the page body.
Sitemap entries are exposed via :func:`results_sitemap_entries` so the master
``/sitemap.xml`` builder can include every archive URL.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
from flask import abort

HITTER_FILE = "hitter_tracking.csv"
PITCHER_FILE = "pitcher_tracking.csv"
SUMMARY_FILE = "daily_betting_summary.csv"
TEAM_LOOKUP_FILE = "hitter_summary_today.csv"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TOP_N = 15
HIGHLIGHT_N = 3

# --- cached CSV reads (keyed on path + mtime; copy on use) ------------------

_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_LOCK = threading.Lock()


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return pd.DataFrame()
    key = str(path)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
    try:
        df = pd.read_csv(path)
    except Exception:
        df = pd.DataFrame()
    with _LOCK:
        _CACHE[key] = (mtime, df)
    return df


def _num(series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _fmt(value, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "—"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "—"
    if f != f:  # NaN
        return "—"
    return f"{f:.{digits}f}{suffix}"


def _fmt_signed(value, digits: int = 1) -> str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "—"
    if f != f:
        return "—"
    return f"{f:+.{digits}f}"


def _pretty_date(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
    except ValueError:
        return date_str


# --- data layer (read-only) -------------------------------------------------


def graded_dates(output_dir: Path) -> list[str]:
    """Return every slate date that has graded actuals, newest first."""
    hitters = _read_csv(output_dir / HITTER_FILE)
    pitchers = _read_csv(output_dir / PITCHER_FILE)
    dates: set[str] = set()

    if not hitters.empty and "date" in hitters.columns:
        h = hitters.copy()
        h["date"] = h["date"].astype(str)
        for d, grp in h.groupby("date"):
            if _num(grp.get("actual_hr")).notna().any() or _num(grp.get("actual_hits")).notna().any():
                dates.add(d)

    if not pitchers.empty and "date" in pitchers.columns:
        p = pitchers.copy()
        p["date"] = p["date"].astype(str)
        for d, grp in p.groupby("date"):
            if _num(grp.get("actual_strikeouts")).notna().any():
                dates.add(d)

    return sorted((d for d in dates if DATE_RE.match(d)), reverse=True)


def _team_lookup(output_dir: Path) -> dict[str, str]:
    df = _read_csv(output_dir / TEAM_LOOKUP_FILE)
    lookup: dict[str, str] = {}
    if not df.empty and "Hitter" in df.columns and "Team" in df.columns:
        for _, row in df.iterrows():
            name = str(row.get("Hitter", "")).strip()
            team = str(row.get("Team", "")).strip()
            if name and team and team.lower() != "nan":
                lookup.setdefault(name, team)
    return lookup


def build_slate(output_dir: Path, date_str: str) -> dict:
    """Assemble all archive sections for one graded date from existing data."""
    hitters = _read_csv(output_dir / HITTER_FILE)
    pitchers = _read_csv(output_dir / PITCHER_FILE)
    teams = _team_lookup(output_dir)

    hh = hitters[hitters["date"].astype(str) == date_str].copy() if not hitters.empty and "date" in hitters.columns else pd.DataFrame()
    pp = pitchers[pitchers["date"].astype(str) == date_str].copy() if not pitchers.empty and "date" in pitchers.columns else pd.DataFrame()

    for col in ("hr_prob", "hit_prob", "actual_hr", "actual_hits"):
        if col in hh.columns:
            hh[col] = _num(hh[col])
    for col in ("predicted_strikeouts", "actual_strikeouts"):
        if col in pp.columns:
            pp[col] = _num(pp[col])

    # --- Section 1: slate summary
    unique_pitchers = int(pp["pitcher_name"].nunique()) if "pitcher_name" in pp.columns else 0
    games = (unique_pitchers + 1) // 2 if unique_pitchers else 0
    summary = {
        "date": date_str,
        "pretty_date": _pretty_date(date_str),
        "games": games,
        "hitters": int(len(hh)),
        "pitchers": int(len(pp)),
    }

    # --- Section 2: top home run threat results (ranked by model HR probability)
    hr_results = []
    if not hh.empty and "actual_hr" in hh.columns and "hr_prob" in hh.columns:
        graded = hh[hh["actual_hr"].notna()].sort_values("hr_prob", ascending=False)
        for rank, (_, row) in enumerate(graded.head(TOP_N).iterrows(), start=1):
            actual_hr = row.get("actual_hr")
            hr_results.append({
                "rank": rank,
                "player": str(row.get("hitter_name", "")).strip(),
                "team": teams.get(str(row.get("hitter_name", "")).strip(), "—"),
                "matchup": str(row.get("pitcher_name", "")).strip() or "—",
                "hr_prob": row.get("hr_prob"),
                "homered": bool(actual_hr is not None and float(actual_hr) >= 1),
            })

    # --- Section 3: pitcher strikeout results
    k_results = []
    if not pp.empty and "actual_strikeouts" in pp.columns and "predicted_strikeouts" in pp.columns:
        graded = pp[pp["actual_strikeouts"].notna()].sort_values("predicted_strikeouts", ascending=False)
        for _, row in graded.head(TOP_N).iterrows():
            pred = row.get("predicted_strikeouts")
            act = row.get("actual_strikeouts")
            diff = (float(act) - float(pred)) if (pred is not None and act is not None and pred == pred and act == act) else None
            k_results.append({
                "pitcher": str(row.get("pitcher_name", "")).strip(),
                "opponent": str(row.get("opponent", "")).strip() or "—",
                "projected": pred,
                "actual": act,
                "diff": diff,
                "accurate": bool(diff is not None and abs(diff) <= 1.0),
            })

    # --- Section 4: hit probability results
    hit_results = []
    if not hh.empty and "actual_hits" in hh.columns and "hit_prob" in hh.columns:
        graded = hh[hh["actual_hits"].notna()].sort_values("hit_prob", ascending=False)
        for _, row in graded.head(TOP_N).iterrows():
            actual_hits = row.get("actual_hits")
            hit_results.append({
                "player": str(row.get("hitter_name", "")).strip(),
                "team": teams.get(str(row.get("hitter_name", "")).strip(), "—"),
                "matchup": str(row.get("pitcher_name", "")).strip() or "—",
                "hit_prob": row.get("hit_prob"),
                "got_hit": bool(actual_hits is not None and float(actual_hits) >= 1),
            })

    # --- Section 5: model highlights (deterministic, no LLM)
    highlights = _build_highlights(hh, pp, teams)

    return {
        "summary": summary,
        "hr_results": hr_results,
        "k_results": k_results,
        "hit_results": hit_results,
        "highlights": highlights,
    }


def _build_highlights(hh: pd.DataFrame, pp: pd.DataFrame, teams: dict) -> dict:
    highlights = {"top_hr": [], "top_k": [], "surprises": [], "best": None}

    # Top home run calls: highest model HR probability among players who homered.
    if not hh.empty and "actual_hr" in hh.columns and "hr_prob" in hh.columns:
        hit_hr = hh[(hh["actual_hr"].notna()) & (hh["actual_hr"] >= 1)].sort_values("hr_prob", ascending=False)
        for _, row in hit_hr.head(HIGHLIGHT_N).iterrows():
            highlights["top_hr"].append({
                "player": str(row.get("hitter_name", "")).strip(),
                "hr_prob": row.get("hr_prob"),
            })

    # Top strikeout calls: highest-projected starts the model met or beat.
    if not pp.empty and "actual_strikeouts" in pp.columns and "predicted_strikeouts" in pp.columns:
        graded = pp[pp["actual_strikeouts"].notna()].copy()
        if not graded.empty:
            met = graded[graded["actual_strikeouts"] >= graded["predicted_strikeouts"]].sort_values("predicted_strikeouts", ascending=False)
            for _, row in met.head(HIGHLIGHT_N).iterrows():
                highlights["top_k"].append({
                    "pitcher": str(row.get("pitcher_name", "")).strip(),
                    "projected": row.get("predicted_strikeouts"),
                    "actual": row.get("actual_strikeouts"),
                })

            # Biggest surprise: largest absolute strikeout miss in either direction.
            graded = graded.assign(_absdiff=(graded["actual_strikeouts"] - graded["predicted_strikeouts"]).abs())
            for _, row in graded.sort_values("_absdiff", ascending=False).head(2).iterrows():
                highlights["surprises"].append({
                    "kind": "pitcher",
                    "name": str(row.get("pitcher_name", "")).strip(),
                    "projected": row.get("predicted_strikeouts"),
                    "actual": row.get("actual_strikeouts"),
                })

    # Highest performing projection: most confident HR call that paid off; else
    # the most accurate high-volume strikeout projection.
    if highlights["top_hr"]:
        top = highlights["top_hr"][0]
        highlights["best"] = {
            "kind": "hr",
            "label": "Home Run Projection",
            "player": top["player"],
            "detail": f"Model HR probability {_fmt(top['hr_prob'], 1, '%')} — result: Home Run.",
        }
    elif highlights["top_k"]:
        top = highlights["top_k"][0]
        highlights["best"] = {
            "kind": "k",
            "label": "Strikeout Projection",
            "player": top["pitcher"],
            "detail": f"Projected {_fmt(top['projected'])} strikeouts — recorded {_fmt(top['actual'], 0)}.",
        }
    return highlights


# --- rendering --------------------------------------------------------------

_ARCHIVE_STYLES = """
<style>
.results-archive{max-width:1100px;margin:0 auto}
.results-archive .panel{margin-bottom:22px}
.ra-table{width:100%;border-collapse:collapse;margin-top:12px;font-size:14px}
.ra-table th,.ra-table td{padding:10px 12px;border-bottom:1px solid var(--line,#1e293b);text-align:left}
.ra-table th{color:var(--muted,#94a3b8);font-weight:600;text-transform:uppercase;letter-spacing:.04em;font-size:12px}
.ra-table tr:hover td{background:rgba(59,130,246,.05)}
.ra-rank{color:var(--muted,#94a3b8);font-variant-numeric:tabular-nums}
.ra-badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700;letter-spacing:.02em}
.ra-hit{background:rgba(16,185,129,.15);color:#34d399;border:1px solid rgba(16,185,129,.3)}
.ra-miss{background:rgba(148,163,184,.12);color:#94a3b8;border:1px solid rgba(148,163,184,.25)}
.ra-accurate{background:rgba(59,130,246,.15);color:#60a5fa;border:1px solid rgba(59,130,246,.3)}
.ra-summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-top:14px}
.ra-summary-card{background:var(--surface,#121929);border:1px solid var(--line,#1e293b);border-radius:14px;padding:16px}
.ra-summary-card .ra-num{font-size:26px;font-weight:800;color:var(--ink,#f8fafc)}
.ra-summary-card .ra-lab{color:var(--muted,#94a3b8);font-size:13px;margin-top:4px}
.ra-highlight-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-top:14px}
.ra-highlight{background:var(--surface,#121929);border:1px solid var(--line,#1e293b);border-radius:14px;padding:16px}
.ra-highlight h4{margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:#60a5fa}
.ra-highlight ul{margin:0;padding-left:18px;color:var(--ink,#e5edf7);font-size:14px;line-height:1.6}
.ra-best{background:linear-gradient(135deg,rgba(59,130,246,.14),rgba(16,185,129,.08));border:1px solid rgba(59,130,246,.3);border-radius:14px;padding:18px;margin-top:14px}
.ra-best strong{color:#fff}
.ra-archive-nav{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;margin:8px 0 22px}
.ra-archive-nav a{display:inline-flex;align-items:center;gap:6px;padding:9px 16px;border-radius:10px;border:1px solid var(--line,#1e293b);background:var(--surface,#121929);color:#cbd5f5;text-decoration:none;font-size:14px;font-weight:600}
.ra-archive-nav a:hover{border-color:#3b82f6;color:#fff}
.ra-related{display:flex;flex-wrap:wrap;gap:10px;margin-top:8px}
.ra-related a{padding:8px 14px;border-radius:999px;border:1px solid var(--line,#1e293b);color:#94a3b8;text-decoration:none;font-size:13px}
.ra-related a:hover{color:#fff;border-color:#3b82f6}
.ra-date-list{list-style:none;padding:0;margin:14px 0 0;display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
.ra-date-list a{display:flex;justify-content:space-between;align-items:center;padding:14px 16px;border-radius:12px;border:1px solid var(--line,#1e293b);background:var(--surface,#121929);color:var(--ink,#e5edf7);text-decoration:none}
.ra-date-list a:hover{border-color:#3b82f6}
.ra-date-list .ra-date-meta{color:var(--muted,#94a3b8);font-size:12px}
.ra-empty{color:var(--muted,#94a3b8);font-style:italic;margin-top:10px}
</style>
"""


def _json_ld_block(scripts: list[dict]) -> str:
    import json
    out = []
    for data in scripts:
        out.append('<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + "</script>")
    return "".join(out)


def _panel(eyebrow: str, heading: str, inner: str, note: str = "") -> str:
    note_html = f"<p class='muted'>{escape(note)}</p>" if note else ""
    return (
        "<section class='panel'><div class='panel-head'><div>"
        f"<div class='eyebrow'>{escape(eyebrow)}</div><h2>{escape(heading)}</h2></div>"
        f"{note_html}</div>{inner}</section>"
    )


def _hit_badge(ok: bool, yes: str, no: str) -> str:
    cls = "ra-hit" if ok else "ra-miss"
    return f"<span class='ra-badge {cls}'>{escape(yes if ok else no)}</span>"


def render_daily_body(site_origin: str, slate: dict, prev_date, next_date) -> str:
    s = slate["summary"]
    date_str = s["date"]
    pretty = s["pretty_date"]

    # Section 1 — slate summary
    summary_cards = "".join(
        f"<div class='ra-summary-card'><div class='ra-num'>{escape(str(v))}</div><div class='ra-lab'>{escape(lab)}</div></div>"
        for v, lab in [
            (s["games"], "Games covered"),
            (s["hitters"], "Hitters evaluated"),
            (s["pitchers"], "Pitchers evaluated"),
            (pretty, "Slate date"),
        ]
    )
    sec1 = _panel("Slate Summary", f"MLB Model Results — {pretty}",
                  f"<div class='ra-summary-grid'>{summary_cards}</div>",
                  "Every figure below is drawn from EdgeRanked's published projection and tracking artifacts for this date.")

    # Section 2 — HR threat results
    if slate["hr_results"]:
        rows = "".join(
            "<tr>"
            f"<td class='ra-rank'>#{r['rank']}</td>"
            f"<td>{escape(r['player'])}</td>"
            f"<td>{escape(r['team'])}</td>"
            f"<td>vs {escape(r['matchup'])}</td>"
            f"<td>{_fmt(r['hr_prob'], 1, '%')}</td>"
            f"<td>{_hit_badge(r['homered'], 'Home Run', 'No Home Run')}</td>"
            "</tr>"
            for r in slate["hr_results"]
        )
        inner = ("<table class='ra-table'><thead><tr>"
                 "<th>Rank</th><th>Player</th><th>Team</th><th>Matchup</th><th>HR Probability</th><th>Result</th>"
                 "</tr></thead><tbody>" + rows + "</tbody></table>")
    else:
        inner = "<p class='ra-empty'>No graded home run projections are available for this slate.</p>"
    sec2 = _panel("Home Run Threats", "Top Home Run Threat Results", inner,
                  "Players ranked by the model's home run probability, with the recorded outcome.")

    # Section 3 — pitcher strikeout results
    if slate["k_results"]:
        rows = "".join(
            "<tr>"
            f"<td>{escape(r['pitcher'])}</td>"
            f"<td>{escape(r['opponent'])}</td>"
            f"<td>{_fmt(r['projected'])}</td>"
            f"<td>{_fmt(r['actual'], 0)}</td>"
            f"<td>{_fmt_signed(r['diff'])}</td>"
            f"<td>{'<span class=\"ra-badge ra-accurate\">On Target</span>' if r['accurate'] else ''}</td>"
            "</tr>"
            for r in slate["k_results"]
        )
        inner = ("<table class='ra-table'><thead><tr>"
                 "<th>Pitcher</th><th>Opponent</th><th>Projected Ks</th><th>Actual Ks</th><th>Difference</th><th></th>"
                 "</tr></thead><tbody>" + rows + "</tbody></table>")
    else:
        inner = "<p class='ra-empty'>No graded strikeout projections are available for this slate.</p>"
    sec3 = _panel("Strikeouts", "Pitcher Strikeout Results", inner,
                  "Projected strikeouts versus actual, ordered by projection strength. “On Target” marks calls within one strikeout.")

    # Section 4 — hit probability results
    if slate["hit_results"]:
        rows = "".join(
            "<tr>"
            f"<td>{escape(r['player'])}</td>"
            f"<td>{escape(r['team'])}</td>"
            f"<td>vs {escape(r['matchup'])}</td>"
            f"<td>{_fmt(r['hit_prob'], 1, '%')}</td>"
            f"<td>{_hit_badge(r['got_hit'], 'Hit', 'No Hit')}</td>"
            "</tr>"
            for r in slate["hit_results"]
        )
        inner = ("<table class='ra-table'><thead><tr>"
                 "<th>Player</th><th>Team</th><th>Matchup</th><th>Hit Probability</th><th>Result</th>"
                 "</tr></thead><tbody>" + rows + "</tbody></table>")
    else:
        inner = "<p class='ra-empty'>No graded hit projections are available for this slate.</p>"
    sec4 = _panel("Hit Probability", "Hit Probability Results", inner,
                  "Players ranked by projected hit probability, with the recorded outcome.")

    # Section 5 — model highlights
    h = slate["highlights"]
    cols = []
    if h["top_hr"]:
        items = "".join(f"<li>{escape(x['player'])} — {_fmt(x['hr_prob'], 1, '%')} HR probability</li>" for x in h["top_hr"])
        cols.append(f"<div class='ra-highlight'><h4>Top Home Run Calls</h4><ul>{items}</ul></div>")
    if h["top_k"]:
        items = "".join(f"<li>{escape(x['pitcher'])} — proj {_fmt(x['projected'])}, recorded {_fmt(x['actual'], 0)}</li>" for x in h["top_k"])
        cols.append(f"<div class='ra-highlight'><h4>Top Strikeout Calls</h4><ul>{items}</ul></div>")
    if h["surprises"]:
        items = "".join(f"<li>{escape(x['name'])} — proj {_fmt(x['projected'])}, recorded {_fmt(x['actual'], 0)}</li>" for x in h["surprises"])
        cols.append(f"<div class='ra-highlight'><h4>Biggest Surprises</h4><ul>{items}</ul></div>")
    best_html = ""
    if h["best"]:
        b = h["best"]
        best_html = (f"<div class='ra-best'><strong>Highest Performing Projection — {escape(b['label'])}:</strong> "
                     f"{escape(b['player'])}. {escape(b['detail'])}</div>")
    inner = (f"<div class='ra-highlight-grid'>{''.join(cols)}</div>{best_html}") if (cols or best_html) else "<p class='ra-empty'>No standout calls were recorded for this slate.</p>"
    sec5 = _panel("Model Highlights", "What the Model Got Right", inner,
                  "Automatically surfaced from the graded results for this date — no manual analysis.")

    # Phase 4 — archive navigation
    nav_parts = []
    if prev_date:
        nav_parts.append(f"<a href='/mlb/results/{prev_date}'>← {escape(_pretty_date(prev_date))}</a>")
    else:
        nav_parts.append("<span></span>")
    nav_parts.append("<a href='/mlb/results'>Back to Results Archive</a>")
    if next_date:
        nav_parts.append(f"<a href='/mlb/results/{next_date}'>{escape(_pretty_date(next_date))} →</a>")
    else:
        nav_parts.append("<span></span>")
    archive_nav = f"<div class='ra-archive-nav'>{''.join(nav_parts)}</div>"

    related = ("<section class='panel'><div class='panel-head'><div>"
               "<div class='eyebrow'>Explore More</div><h2>Related MLB Pages</h2></div></div>"
               "<div class='ra-related'>"
               "<a href='/mlb/projections'>MLB Projections</a>"
               "<a href='/mlb/weather'>MLB Weather</a>"
               "<a href='/mlb/intel'>MLB Intel</a>"
               "<a href='/mlb'>MLB Home</a>"
               "</div></section>")

    # Phase 3 — structured data (Article + Breadcrumb)
    page_url = f"{site_origin}/mlb/results/{date_str}"
    json_ld = _json_ld_block([
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": f"MLB Model Results — {pretty}",
            "description": f"EdgeRanked AI home run, strikeout, and hit probability model results for the {pretty} MLB slate.",
            "datePublished": date_str,
            "dateModified": date_str,
            "url": page_url,
            "mainEntityOfPage": {"@type": "WebPage", "@id": page_url},
            "author": {"@type": "Organization", "name": "EdgeRankedSportsAI"},
            "publisher": {"@type": "Organization", "name": "EdgeRankedSportsAI"},
        },
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "MLB", "item": f"{site_origin}/mlb"},
                {"@type": "ListItem", "position": 2, "name": "Results Archive", "item": f"{site_origin}/mlb/results"},
                {"@type": "ListItem", "position": 3, "name": pretty, "item": page_url},
            ],
        },
    ])

    return _ARCHIVE_STYLES + json_ld + "<div class='results-archive'>" + archive_nav + sec1 + sec2 + sec3 + sec4 + sec5 + related + "</div>"


def render_hub_body(site_origin: str, dates: list[str], output_dir: Path) -> str:
    intro = (
        "<section class='panel'><div class='panel-head'><div>"
        "<div class='eyebrow'>Transparent Track Record</div><h2>MLB Results Archive</h2></div></div>"
        "<p class='muted'>A permanent, day-by-day record of how the EdgeRanked AI MLB model performed. "
        "Every slate below links to a full results page covering daily model results, historical projection "
        "outcomes, home run threat performance, strikeout projection performance, and hit probability outcomes — "
        "built entirely from our published projections and graded actuals.</p></section>"
    )

    if dates:
        items = []
        for d in dates:
            items.append(
                f"<a href='/mlb/results/{d}'><span>{escape(_pretty_date(d))}</span>"
                f"<span class='ra-date-meta'>{escape(d)}</span></a>"
            )
        listing = (
            "<section class='panel'><div class='panel-head'><div>"
            "<div class='eyebrow'>Daily Archives</div><h2>Browse by Date</h2></div>"
            f"<p class='muted'>{len(dates)} graded slates · newest first</p></div>"
            f"<ul class='ra-date-list'>{''.join(items)}</ul></section>"
        )
    else:
        listing = "<section class='panel'><p class='ra-empty'>No graded slates are available yet. Check back after the next slate is scored.</p></section>"

    json_ld = _json_ld_block([
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "MLB", "item": f"{site_origin}/mlb"},
                {"@type": "ListItem", "position": 2, "name": "Results Archive", "item": f"{site_origin}/mlb/results"},
            ],
        },
    ])

    related = ("<div class='ra-related' style='margin-top:18px'>"
               "<a href='/mlb/projections'>MLB Projections</a>"
               "<a href='/mlb/weather'>MLB Weather</a>"
               "<a href='/mlb/intel'>MLB Intel</a>"
               "<a href='/mlb'>MLB Home</a>"
               "</div>")

    return _ARCHIVE_STYLES + json_ld + "<div class='results-archive'>" + intro + listing + related + "</div>"


# --- sitemap integration ----------------------------------------------------


def results_sitemap_entries(output_dir: Path) -> list[tuple[str, str, str, str]]:
    """Return (path, changefreq, priority, lastmod) for the hub + every archive
    page, newest first. Newest pages get the highest priority.
    """
    dates = graded_dates(output_dir)
    entries: list[tuple[str, str, str, str]] = []
    today = datetime.now().date().isoformat()
    entries.append(("/mlb/results", "daily", "0.8", today))
    for idx, d in enumerate(dates):
        # newest few at 0.7, then taper to 0.4 floor
        if idx < 3:
            priority = "0.7"
        elif idx < 10:
            priority = "0.6"
        elif idx < 25:
            priority = "0.5"
        else:
            priority = "0.4"
        changefreq = "weekly" if idx < 7 else "monthly"
        entries.append((f"/mlb/results/{d}", changefreq, priority, d))
    return entries


# --- route registration -----------------------------------------------------


def register_mlb_results_routes(flask_app, render_layout, output_dir, site_origin):
    """Install /mlb/results and /mlb/results/<date> on the host Flask app."""
    output_dir = Path(output_dir)

    @flask_app.get("/mlb/results")
    def mlb_results_hub():
        dates = graded_dates(output_dir)
        body = render_hub_body(site_origin, dates, output_dir)
        return render_layout(
            "MLB Results Archive",
            "Daily, transparent MLB model results — home run threats, strikeout projections, and hit probability outcomes.",
            body,
            "/mlb/results",
            meta_description="Browse EdgeRanked AI's MLB Results Archive: a permanent, day-by-day record of home run threat, strikeout, and hit probability model outcomes for every graded slate.",
            document_title="MLB Results Archive | EdgeRanked AI",
            hero_kicker="MLB",
        )

    @flask_app.get("/mlb/results/<date_str>")
    def mlb_results_daily(date_str):
        if not DATE_RE.match(date_str):
            abort(404)
        dates = graded_dates(output_dir)
        if date_str not in dates:
            abort(404)
        slate = build_slate(output_dir, date_str)
        pretty = slate["summary"]["pretty_date"]
        # dates are newest-first; "previous" = older date, "next" = newer date
        idx = dates.index(date_str)
        prev_date = dates[idx + 1] if idx + 1 < len(dates) else None  # older
        next_date = dates[idx - 1] if idx - 1 >= 0 else None  # newer
        body = render_daily_body(site_origin, slate, prev_date, next_date)
        return render_layout(
            f"MLB Model Results — {pretty}",
            "Home run threat, strikeout, and hit probability results for this MLB slate.",
            body,
            "/mlb/results",
            meta_description=(f"EdgeRanked AI MLB model results for {pretty}: top home run threats, pitcher "
                              f"strikeout projections versus actuals, and hit probability outcomes with graded results."),
            document_title=f"MLB Results — {pretty} | EdgeRanked AI",
            hero_kicker="MLB Results",
        )
