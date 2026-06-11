"""Permanent MLB daily leaderboard archive — actual outcomes only.

Routes
  * ``/mlb/leaderboards``               — archive index (every graded date)
  * ``/mlb/leaderboards/<YYYY-MM-DD>``  — permanent leaderboards for one slate

One page per graded slate date, built read-only from the graded rows of
``hitter_tracking.csv`` and ``pitcher_tracking.csv``. Pages accumulate as
grading lands; nothing here runs models or grading.

Premium-safety contract: only date, player name, pitcher opponent, and actual
outcome columns are ever read. Historical model probabilities, projections,
and confidence values are never loaded, so this archive cannot become a free
mirror of premium outputs. All rankings are by actual results.
"""

from __future__ import annotations

import json
import re
import time
from html import escape
from pathlib import Path

import pandas as pd

from nba_model.webapp.mlb_player_history import (
    PAGE_STYLE,
    format_tracked_date,
    render_panel,
    render_table,
    slugify_player_name,
)
from nba_model.webapp import mlb_teams

CACHE_TTL_SECONDS = 600
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_HITTER_COLS = ["date", "hitter_name", "actual_hits", "actual_tb", "actual_hr", "actual_rbi"]
_PITCHER_COLS = ["date", "pitcher_name", "opponent", "actual_strikeouts", "actual_outs"]

_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]

_CACHE = {"key": None, "built_at": 0.0, "data": None}


def _read_csv(path):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _mtime(path):
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


def _archive(output_dir):
    """Cached {date: {"hitters": [...], "pitchers": [...]}} of graded rows."""
    output_dir = Path(output_dir)
    hitter_path = output_dir / "hitter_tracking.csv"
    pitcher_path = output_dir / "pitcher_tracking.csv"
    key = (str(output_dir), _mtime(hitter_path), _mtime(pitcher_path))
    now = time.time()
    if _CACHE["data"] is not None and _CACHE["key"] == key and now - _CACHE["built_at"] < CACHE_TTL_SECONDS:
        return _CACHE["data"]

    by_date = {}

    df = _read_csv(hitter_path)
    if not df.empty and {"date", "hitter_name"}.issubset(df.columns):
        cols = [c for c in _HITTER_COLS if c in df.columns]
        sub = df[cols].copy()
        sub["date"] = sub["date"].astype(str)
        sub = sub[sub["date"].str.match(DATE_RE)]
        for col in ("actual_hits", "actual_tb", "actual_hr", "actual_rbi"):
            sub[col] = pd.to_numeric(sub.get(col), errors="coerce")
        sub = sub[sub["actual_hits"].notna() | sub["actual_hr"].notna()]
        sub = sub.sort_values("date").drop_duplicates(["date", "hitter_name"], keep="last")
        for row in sub.itertuples(index=False):
            name = str(row.hitter_name).strip()
            if not name or name.lower() == "nan":
                continue
            day = by_date.setdefault(row.date, {"hitters": [], "pitchers": []})
            day["hitters"].append({
                "name": name,
                "slug": slugify_player_name(name),
                "hits": float(row.actual_hits) if pd.notna(row.actual_hits) else 0.0,
                "tb": float(row.actual_tb) if pd.notna(row.actual_tb) else 0.0,
                "hr": float(row.actual_hr) if pd.notna(row.actual_hr) else 0.0,
                "rbi": float(row.actual_rbi) if pd.notna(row.actual_rbi) else 0.0,
            })

    df = _read_csv(pitcher_path)
    if not df.empty and {"date", "pitcher_name"}.issubset(df.columns):
        cols = [c for c in _PITCHER_COLS if c in df.columns]
        sub = df[cols].copy()
        sub["date"] = sub["date"].astype(str)
        sub = sub[sub["date"].str.match(DATE_RE)]
        for col in ("actual_strikeouts", "actual_outs"):
            sub[col] = pd.to_numeric(sub.get(col), errors="coerce")
        sub = sub[sub["actual_strikeouts"].notna()]
        sub = sub.sort_values("date").drop_duplicates(["date", "pitcher_name"], keep="last")
        for row in sub.itertuples(index=False):
            name = str(row.pitcher_name).strip()
            if not name or name.lower() == "nan":
                continue
            opponent = str(getattr(row, "opponent", "") or "").strip()
            if opponent.lower() == "nan":
                opponent = ""
            day = by_date.setdefault(row.date, {"hitters": [], "pitchers": []})
            day["pitchers"].append({
                "name": name,
                "slug": slugify_player_name(name),
                "opponent": opponent,
                "ks": float(row.actual_strikeouts),
                "outs": float(row.actual_outs) if pd.notna(row.actual_outs) else None,
            })

    _CACHE.update({"key": key, "built_at": now, "data": by_date})
    return by_date


def graded_dates(output_dir):
    """Every date with a leaderboard page, newest first."""
    return sorted(_archive(output_dir).keys(), reverse=True)


def leaderboards_sitemap_entries(output_dir):
    entries = [("/mlb/leaderboards", "daily", "0.7", None)]
    for day in graded_dates(output_dir):
        entries.append((f"/mlb/leaderboards/{day}", "monthly", "0.6", day))
    return entries


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def _fmt_ip(outs):
    if outs is None:
        return "—"
    whole, rem = divmod(int(outs), 3)
    return f"{whole}.{rem}"


def _player_cell(record, team_lookup):
    link = f"<a href='/mlb/player/{escape(record['slug'])}'>{escape(record['name'])}</a>"
    team = team_lookup.get(record["slug"])
    if team and team in mlb_teams.BY_NAME:
        team_slug = mlb_teams.BY_NAME[team]["slug"]
        link += f" <span class='muted'>(<a href='/mlb/team/{escape(team_slug)}'>{escape(team)}</a>)</span>"
    return link


def _opponent_cell(opponent):
    if opponent and opponent in mlb_teams.BY_NAME:
        slug = mlb_teams.BY_NAME[opponent]["slug"]
        return f"vs <a href='/mlb/team/{escape(slug)}'>{escape(opponent)}</a>"
    return f"vs {escape(opponent)}" if opponent else "—"


def _hitter_board(title, eyebrow, rows, columns, note=""):
    if not rows:
        return ""
    return render_panel(eyebrow, title, render_table(columns, rows), note)


def _json_ld(payload):
    return f"<script type='application/ld+json'>{json.dumps(payload)}</script>"


def _breadcrumb(site_origin, trail):
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": f"{site_origin}{path}"}
            for i, (name, path) in enumerate(trail)
        ],
    }


def build_index_body(output_dir, data_dir, site_origin):
    dates = graded_dates(output_dir)
    parts = [PAGE_STYLE]

    intro = (
        "<p class='muted'>Daily MLB leaderboards built from graded, actual results: hits, "
        "home runs, total bases, RBI, and pitcher strikeouts for every tracked slate. "
        "A new page is added each day after results are graded. Historical outcomes only — "
        "no projections appear in this archive.</p>"
        "<p class='muted'>Categories on every dated page: Top Hit Performers · Top Home Run "
        "Performers · Top Total Bases · Top RBI · Most Productive Offensive Games · "
        "Most Strikeout-Dominant Starts · Top Pitching Workloads.</p>"
    )
    parts.append(render_panel("MLB Leaderboards", "Daily MLB Leaderboard Archive", intro,
                              f"{len(dates)} graded slates archived."))

    monthly = {}
    for day in dates:
        monthly.setdefault(day[:7], []).append(day)
    for month_key in sorted(monthly, reverse=True):
        year, month = month_key.split("-")
        days = monthly[month_key]
        links = " · ".join(
            f"<a href='/mlb/leaderboards/{escape(d)}'>{escape(format_tracked_date(d))}</a>" for d in days
        )
        parts.append(render_panel(
            f"{_MONTHS[int(month) - 1]} {year}", f"{_MONTHS[int(month) - 1]} {year} Leaderboards",
            f"<p style='line-height:2.1'>{links}</p>", f"{len(days)} graded slates",
        ))

    related = (
        "<p class='muted'><a href='/mlb/results'>MLB Results Archive</a> · "
        "<a href='/mlb/teams'>All MLB Teams</a> · "
        "<a href='/mlb/stadiums'>MLB Stadium Guide</a></p>"
    )
    parts.append(render_panel("More MLB", "Related MLB Coverage", related))

    parts.append(_json_ld({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "CollectionPage",
                "name": "Daily MLB Leaderboard Archive",
                "url": f"{site_origin}/mlb/leaderboards",
                "description": "Permanent daily MLB leaderboards built from graded actual results.",
            },
            _breadcrumb(site_origin, [("Home", "/"), ("MLB", "/mlb"), ("Leaderboards", "/mlb/leaderboards")]),
        ],
    }))
    return "".join(parts)


def build_date_body(day, output_dir, data_dir, site_origin):
    archive = _archive(output_dir)
    slate = archive.get(day) or {"hitters": [], "pitchers": []}
    hitters, pitchers = slate["hitters"], slate["pitchers"]
    try:
        team_lookup = mlb_teams.player_team_map(output_dir, data_dir)
    except Exception:
        team_lookup = {}
    pretty = format_tracked_date(day)
    parts = [PAGE_STYLE]

    summary = (
        f"<p class='muted'>Graded results for the {pretty} MLB slate: {len(hitters)} tracked "
        f"hitters and {len(pitchers)} tracked starting pitchers. Every leaderboard below ranks "
        "actual recorded outcomes — hits, home runs, total bases, RBI, strikeouts, and innings. "
        f"See the <a href='/mlb/results/{escape(day)}'>full graded slate results</a> for this date.</p>"
    )
    parts.append(render_panel("Slate Summary", f"MLB Leaderboards — {pretty}", summary))

    def top(records, sort_keys, limit=10, require=None):
        pool = [r for r in records if require is None or require(r)]
        return sorted(pool, key=sort_keys)[:limit]

    if hitters:
        rows = [
            [f"#{i + 1}", _player_cell(r, team_lookup), f"{r['hits']:.0f}", f"{r['tb']:.0f}", f"{r['rbi']:.0f}"]
            for i, r in enumerate(top(hitters, lambda r: (-r["hits"], -r["tb"], r["name"]), require=lambda r: r["hits"] >= 1))
        ]
        parts.append(_hitter_board("Top Hit Performers", "Hits", rows,
                                   ["Rank", "Player", "Hits", "Total Bases", "RBI"]))

        rows = [
            [f"#{i + 1}", _player_cell(r, team_lookup), f"{r['hr']:.0f}", f"{r['tb']:.0f}", f"{r['rbi']:.0f}"]
            for i, r in enumerate(top(hitters, lambda r: (-r["hr"], -r["tb"], r["name"]), require=lambda r: r["hr"] >= 1))
        ]
        parts.append(_hitter_board("Top Home Run Performers", "Home Runs", rows,
                                   ["Rank", "Player", "HR", "Total Bases", "RBI"],
                                   "Every tracked hitter who homered on this slate." if rows else ""))

        rows = [
            [f"#{i + 1}", _player_cell(r, team_lookup), f"{r['tb']:.0f}", f"{r['hits']:.0f}", f"{r['hr']:.0f}"]
            for i, r in enumerate(top(hitters, lambda r: (-r["tb"], -r["hits"], r["name"]), require=lambda r: r["tb"] >= 1))
        ]
        parts.append(_hitter_board("Top Total Bases Performers", "Total Bases", rows,
                                   ["Rank", "Player", "Total Bases", "Hits", "HR"]))

        rows = [
            [f"#{i + 1}", _player_cell(r, team_lookup), f"{r['rbi']:.0f}", f"{r['hr']:.0f}", f"{r['hits']:.0f}"]
            for i, r in enumerate(top(hitters, lambda r: (-r["rbi"], -r["hr"], r["name"]), require=lambda r: r["rbi"] >= 1))
        ]
        parts.append(_hitter_board("Top RBI Performers", "RBI", rows,
                                   ["Rank", "Player", "RBI", "HR", "Hits"]))

        rows = [
            [f"#{i + 1}", _player_cell(r, team_lookup),
             f"{r['hits'] + r['tb'] + r['rbi']:.0f}", f"{r['hits']:.0f}", f"{r['tb']:.0f}", f"{r['hr']:.0f}", f"{r['rbi']:.0f}"]
            for i, r in enumerate(top(hitters, lambda r: (-(r["hits"] + r["tb"] + r["rbi"]), r["name"]),
                                      require=lambda r: (r["hits"] + r["tb"] + r["rbi"]) >= 3))
        ]
        parts.append(_hitter_board("Most Productive Offensive Games", "Combined Production", rows,
                                   ["Rank", "Player", "Combined", "Hits", "TB", "HR", "RBI"],
                                   "Combined = hits + total bases + RBI (actual outcomes)."))

    if pitchers:
        rows = [
            [f"#{i + 1}", _player_cell(r, team_lookup), _opponent_cell(r["opponent"]),
             f"{r['ks']:.0f}", _fmt_ip(r["outs"])]
            for i, r in enumerate(top(pitchers, lambda r: (-r["ks"], r["name"])))
        ]
        parts.append(_hitter_board("Most Strikeout-Dominant Starts", "Strikeouts", rows,
                                   ["Rank", "Pitcher", "Opponent", "Strikeouts", "IP"]))

        with_outs = [r for r in pitchers if r["outs"] is not None]
        rows = [
            [f"#{i + 1}", _player_cell(r, team_lookup), _opponent_cell(r["opponent"]),
             _fmt_ip(r["outs"]), f"{r['ks']:.0f}"]
            for i, r in enumerate(top(with_outs, lambda r: (-(r["outs"] or 0), -r["ks"], r["name"])))
        ]
        parts.append(_hitter_board("Top Pitching Workloads", "Innings", rows,
                                   ["Rank", "Pitcher", "Opponent", "IP", "Strikeouts"],
                                   "Deepest tracked starts on this slate by innings recorded."))

    # Prev / next navigation
    dates = graded_dates(output_dir)  # newest first
    nav_bits = []
    try:
        idx = dates.index(day)
    except ValueError:
        idx = -1
    if idx != -1:
        if idx + 1 < len(dates):
            prev_day = dates[idx + 1]
            nav_bits.append(f"<a href='/mlb/leaderboards/{escape(prev_day)}'>&larr; {escape(format_tracked_date(prev_day))}</a>")
        nav_bits.append("<a href='/mlb/leaderboards'>All Leaderboards</a>")
        if idx > 0:
            next_day = dates[idx - 1]
            nav_bits.append(f"<a href='/mlb/leaderboards/{escape(next_day)}'>{escape(format_tracked_date(next_day))} &rarr;</a>")
    related = (
        "<p class='muted'>" + " · ".join(nav_bits) + "</p>"
        f"<p class='muted'><a href='/mlb/results/{escape(day)}'>Full {escape(pretty)} graded results</a> · "
        "<a href='/mlb/teams'>All MLB Teams</a></p>"
    )
    parts.append(render_panel("Archive", "More From the Archive", related))

    parts.append(_json_ld({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Article",
                "headline": f"MLB Leaderboards — {pretty}",
                "datePublished": day,
                "url": f"{site_origin}/mlb/leaderboards/{day}",
                "description": f"Daily MLB leaderboards for {pretty}: top hits, home runs, total bases, RBI, and strikeout performances from graded results.",
            },
            _breadcrumb(site_origin, [("Home", "/"), ("MLB", "/mlb"),
                                      ("Leaderboards", "/mlb/leaderboards"),
                                      (pretty, f"/mlb/leaderboards/{day}")]),
        ],
    }))
    return "".join(parts)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

def register_mlb_leaderboard_routes(flask_app, render_layout, output_dir, data_dir, site_origin):
    @flask_app.get("/mlb/leaderboards")
    def mlb_leaderboards_index():
        count = len(graded_dates(output_dir))
        return render_layout(
            "MLB Leaderboards",
            f"Daily leaderboards from {count} graded MLB slates — hits, home runs, total bases, RBI, and strikeouts.",
            build_index_body(output_dir, data_dir, site_origin),
            "/mlb/leaderboards",
            hero_kicker="MLB Leaderboard Archive",
            meta_description=("Daily MLB leaderboard archive from EdgeRanked AI: top hit, home run, "
                              "total bases, RBI, and strikeout performances for every graded slate. "
                              "Historical actual results only."),
            document_title="Daily MLB Leaderboard Archive | EdgeRanked AI",
        )

    @flask_app.get("/mlb/leaderboards/<slate_date>")
    def mlb_leaderboards_date(slate_date):
        day = str(slate_date).strip()
        if not DATE_RE.match(day) or day not in _archive(output_dir):
            return _not_found(render_layout)
        pretty = format_tracked_date(day)
        return render_layout(
            f"MLB Leaderboards — {pretty}",
            "Top graded performances from this slate: hits, home runs, total bases, RBI, and strikeouts.",
            build_date_body(day, output_dir, data_dir, site_origin),
            "/mlb/leaderboards",
            hero_kicker="MLB Leaderboard Archive",
            meta_description=(f"MLB leaderboards for {pretty}: top hit, home run, total bases, RBI, and "
                              "pitcher strikeout performances from graded actual results."),
            document_title=f"MLB Leaderboards {pretty} — Top Performances | EdgeRanked AI",
        )


def _not_found(render_layout):
    body = (
        "<section class='panel empty-panel'>"
        "<div class='eyebrow'>Leaderboard Not Found</div>"
        "<h2>No graded leaderboard for that date.</h2>"
        "<p class='muted'>Results may not be graded yet for this slate, or the date is outside "
        "the tracked archive. Browse every available date in the leaderboard index.</p>"
        "<div class='cta-row'><a class='cta-btn primary' href='/mlb/leaderboards'>All Leaderboards</a></div>"
        "</section>"
    )
    html = render_layout(
        "MLB Leaderboard Not Found",
        "That leaderboard date is not available.",
        body,
        "/mlb/leaderboards",
        hero_kicker="MLB Leaderboard Archive",
        meta_description="This MLB leaderboard date is not available. Browse the full daily leaderboard archive.",
        document_title="MLB Leaderboard Not Found | EdgeRanked AI",
    )
    return html, 404
