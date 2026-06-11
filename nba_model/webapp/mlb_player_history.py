"""Permanent MLB player profile history — public SEO content only.

Builds year-round player profile sections from the graded rows of
``hitter_tracking.csv`` and ``pitcher_tracking.csv`` so ``/mlb/player/<slug>``
keeps rendering when a player is off the slate, injured, in the minors, or
between starts.

Premium-safety contract: only actual outcomes (hits, total bases, home runs,
RBI, strikeouts, outs) and standard public stat-line context (AVG/OBP/SLG/OPS)
are ever read into the payload. Model probability / projection columns are
never loaded here, so these pages cannot leak premium model outputs. Rows
without graded actuals (i.e. today's slate) are dropped before indexing.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from html import escape
from pathlib import Path

import pandas as pd

CACHE_TTL_SECONDS = 600

# Columns surfaced publicly. Anything not listed here never leaves the CSV.
_HITTER_PUBLIC_COLS = [
    "date", "hitter_name", "actual_hits", "actual_tb", "actual_hr", "actual_rbi",
    "season_avg", "season_obp", "season_slg", "season_ops",
]
_PITCHER_PUBLIC_COLS = [
    "date", "pitcher_name", "opponent", "actual_strikeouts", "actual_outs",
]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_CACHE = {"key": None, "built_at": 0.0, "index": None, "latest_date": ""}


def slugify_player_name(value):
    # Keep in sync with app.slugify_player_name (duplicated to avoid a
    # circular import; both must produce identical slugs for the same name).
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    ascii_text = ascii_text.replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def _read_csv(path):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _num(series):
    return pd.to_numeric(series, errors="coerce")


def _mtime(path):
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


def _build_index(hitter_path, pitcher_path):
    index = {}
    latest_date = ""

    def entry_for(name):
        slug = slugify_player_name(name)
        if not slug:
            return None
        return index.setdefault(slug, {
            "slug": slug,
            "name": str(name).strip(),
            "hitter_games": [],
            "pitcher_games": [],
            "season_context": {},
        })

    hitters = _read_csv(hitter_path)
    if not hitters.empty and {"date", "hitter_name"}.issubset(hitters.columns):
        cols = [c for c in _HITTER_PUBLIC_COLS if c in hitters.columns]
        df = hitters[cols].copy()
        df["date"] = df["date"].astype(str)
        df = df[df["date"].str.match(_DATE_RE)]
        for col in ("actual_hits", "actual_tb", "actual_hr", "actual_rbi",
                    "season_avg", "season_obp", "season_slg", "season_ops"):
            if col in df.columns:
                df[col] = _num(df[col])
        graded = df["actual_hits"].notna() | df["actual_hr"].notna()
        df = df[graded].sort_values("date").drop_duplicates(
            ["date", "hitter_name"], keep="last"
        )
        for row in df.itertuples(index=False):
            entry = entry_for(getattr(row, "hitter_name", ""))
            if entry is None:
                continue
            game = {
                "date": row.date,
                "hits": _val(getattr(row, "actual_hits", None)),
                "tb": _val(getattr(row, "actual_tb", None)),
                "hr": _val(getattr(row, "actual_hr", None)),
                "rbi": _val(getattr(row, "actual_rbi", None)),
            }
            entry["hitter_games"].append(game)
            season_avg = getattr(row, "season_avg", None)
            if season_avg is not None and not pd.isna(season_avg):
                entry["season_context"] = {
                    "avg": float(season_avg),
                    "obp": _val(getattr(row, "season_obp", None)),
                    "slg": _val(getattr(row, "season_slg", None)),
                    "ops": _val(getattr(row, "season_ops", None)),
                    "as_of": row.date,
                }
            latest_date = max(latest_date, row.date)

    pitchers = _read_csv(pitcher_path)
    if not pitchers.empty and {"date", "pitcher_name"}.issubset(pitchers.columns):
        cols = [c for c in _PITCHER_PUBLIC_COLS if c in pitchers.columns]
        df = pitchers[cols].copy()
        df["date"] = df["date"].astype(str)
        df = df[df["date"].str.match(_DATE_RE)]
        for col in ("actual_strikeouts", "actual_outs"):
            if col in df.columns:
                df[col] = _num(df[col])
        df = df[df["actual_strikeouts"].notna()].sort_values("date").drop_duplicates(
            ["date", "pitcher_name"], keep="last"
        )
        for row in df.itertuples(index=False):
            entry = entry_for(getattr(row, "pitcher_name", ""))
            if entry is None:
                continue
            opponent = getattr(row, "opponent", "")
            opponent = "" if (opponent is None or (isinstance(opponent, float) and pd.isna(opponent))) else str(opponent).strip()
            entry["pitcher_games"].append({
                "date": row.date,
                "opponent": opponent,
                "ks": _val(getattr(row, "actual_strikeouts", None)),
                "outs": _val(getattr(row, "actual_outs", None)),
            })
            latest_date = max(latest_date, row.date)

    for entry in index.values():
        dates = [g["date"] for g in entry["hitter_games"]] + [g["date"] for g in entry["pitcher_games"]]
        entry["first_date"] = min(dates)
        entry["last_date"] = max(dates)
    return index, latest_date


def _val(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return float(value)


def _index(hitter_path, pitcher_path):
    key = (str(hitter_path), _mtime(hitter_path), str(pitcher_path), _mtime(pitcher_path))
    now = time.time()
    if _CACHE["index"] is not None and _CACHE["key"] == key and now - _CACHE["built_at"] < CACHE_TTL_SECONDS:
        return _CACHE["index"], _CACHE["latest_date"]
    index, latest_date = _build_index(hitter_path, pitcher_path)
    _CACHE.update({"key": key, "built_at": now, "index": index, "latest_date": latest_date})
    return index, latest_date


def all_player_histories(hitter_path, pitcher_path):
    """Read-only graded-history index keyed by player slug (premium-safe by
    construction — built only from whitelisted outcome columns)."""
    index, latest_date = _index(hitter_path, pitcher_path)
    return index, latest_date


def get_history(hitter_path, pitcher_path, slug):
    """Return the tracked-history entry for a player slug, or None."""
    target = slugify_player_name(str(slug or "").replace("-", " "))
    if not target:
        return None
    index, latest_date = _index(hitter_path, pitcher_path)
    entry = index.get(target)
    if entry is None:
        return None
    payload = dict(entry)
    payload["dataset_latest_date"] = latest_date
    return payload


def sitemap_players(hitter_path, pitcher_path):
    """All tracked players for the sitemap: list of (slug, name, lastmod)."""
    index, _ = _index(hitter_path, pitcher_path)
    return sorted(
        ((slug, entry["name"], entry["last_date"]) for slug, entry in index.items()),
        key=lambda item: item[0],
    )


def history_counts(hitter_path, pitcher_path):
    index, _ = _index(hitter_path, pitcher_path)
    hitters = sum(1 for e in index.values() if e["hitter_games"])
    pitchers = sum(1 for e in index.values() if e["pitcher_games"])
    return {"players": len(index), "hitters": hitters, "pitchers": pitchers}


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]

PAGE_STYLE = """
<style>
.ph-table{width:100%;border-collapse:collapse;margin-top:12px;font-size:14px}
.ph-table th,.ph-table td{padding:10px 12px;border-bottom:1px solid var(--line,#1e293b);text-align:left}
.ph-table th{color:var(--text-muted,#94a3b8);font-weight:600;text-transform:uppercase;letter-spacing:.04em;font-size:12px}
.ph-table tr:hover td{background:rgba(59,130,246,.05)}
.ph-form-list{list-style:none;margin:12px 0 0;padding:0}
.ph-form-list li{padding:8px 0;border-bottom:1px solid var(--line,#1e293b);color:var(--text,#e8e9ec)}
.ph-form-list li:last-child{border-bottom:none}
.ph-spark{width:100%;height:auto;margin-top:12px;display:block}
.ph-spark-caption{color:var(--text-muted,#9aa0a6);font-size:12px;margin-top:6px}
</style>
"""


def _fmt_date(date_str):
    try:
        year, month, day = date_str.split("-")
        return f"{_MONTHS[int(month) - 1]} {int(day)}, {year}"
    except (ValueError, IndexError):
        return date_str


format_tracked_date = _fmt_date


def _fmt_rate(value, digits=3):
    if value is None:
        return "—"
    text = f"{value:.{digits}f}"
    return text[1:] if text.startswith("0.") else text


def _fmt_count(value):
    if value is None:
        return "—"
    return str(int(value))


def _fmt_ip(outs):
    if outs is None:
        return "—"
    whole, rem = divmod(int(outs), 3)
    return f"{whole}.{rem}"


def _panel(eyebrow, heading, inner, note=""):
    note_html = f"<p class='muted'>{escape(note)}</p>" if note else ""
    return (
        "<section class='panel'><div class='panel-head'><div>"
        f"<div class='eyebrow'>{escape(eyebrow)}</div><h2>{escape(heading)}</h2></div>"
        f"{note_html}</div>{inner}</section>"
    )


def _table(headers, rows):
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table class='ph-table'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _form_list(sentences):
    items = "".join(f"<li>{escape(s)}</li>" for s in sentences if s)
    return f"<ul class='ph-form-list'>{items}</ul>"


def _bar_strip(points, caption):
    """Inline SVG bar strip from (label, value, highlight) tuples — actuals only."""
    if not points:
        return ""
    peak = max((value for _, value, _ in points), default=0) or 1
    width, height, pad = 760, 120, 4
    bar_w = (width - pad * 2) / len(points)
    bars = []
    for i, (label, value, highlight) in enumerate(points):
        bar_h = max(3, (value / peak) * (height - 20))
        x = pad + i * bar_w
        color = "var(--accent-2, #22c55e)" if highlight else "var(--accent, #3b82f6)"
        bars.append(
            f"<rect x='{x:.1f}' y='{height - bar_h:.1f}' width='{max(bar_w - 3, 2):.1f}' "
            f"height='{bar_h:.1f}' rx='2' fill='{color}'><title>{escape(label)}: {value:g}</title></rect>"
        )
    return (
        f"<svg class='ph-spark' viewBox='0 0 {width} {height}' role='img' "
        f"aria-label='{escape(caption)}' xmlns='http://www.w3.org/2000/svg'>" + "".join(bars) + "</svg>"
        f"<p class='ph-spark-caption'>{escape(caption)}</p>"
    )


def _result_date_link(date_str):
    return f"<a href='/mlb/results/{escape(date_str)}'>{escape(_fmt_date(date_str))}</a>"


def _trend_word(recent, prior):
    if recent > prior:
        return "increased"
    if recent < prior:
        return "decreased"
    return "held steady"


def _hitter_sections(entry):
    games = sorted(entry["hitter_games"], key=lambda g: g["date"])
    if not games:
        return []
    name = entry["name"]
    total = len(games)
    hits = sum(g["hits"] or 0 for g in games)
    hr = sum(g["hr"] or 0 for g in games)
    rbi = sum(g["rbi"] or 0 for g in games)
    tb = sum(g["tb"] or 0 for g in games)
    sections = []

    # Player overview
    season = entry.get("season_context") or {}
    cards = [
        ("Tracked Games", str(total), f"Graded games since {_fmt_date(games[0]['date'])}"),
        ("Last Tracked Game", _fmt_date(games[-1]["date"]), "Most recent graded result"),
        ("Tracked Hits", _fmt_count(hits), f"{hits / total:.2f} hits per tracked game"),
        ("Tracked Home Runs", _fmt_count(hr), f"{rbi:.0f} RBI across tracked games"),
    ]
    if season.get("avg") is not None:
        caption = f"OPS {_fmt_rate(season.get('ops'))} · as of {_fmt_date(season.get('as_of', ''))}"
        cards.append(("Season AVG", _fmt_rate(season["avg"]), caption))
    inner = _cards(cards)
    sections.append(_panel("Hitting Overview", f"{name} — Tracked Hitting History", inner,
                           "Outcome history from EdgeRanked's graded MLB result tracking."))

    # Recent form indicators
    last10 = games[-10:]
    last15 = games[-15:]
    hit_games_10 = sum(1 for g in last10 if (g["hits"] or 0) >= 1)
    multi_hit_15 = sum(1 for g in last15 if (g["hits"] or 0) >= 2)
    sentences = [
        f"Recorded a hit in {hit_games_10} of his last {len(last10)} tracked games.",
        f"{multi_hit_15} multi-hit games across his last {len(last15)} tracked games.",
    ]
    if total >= 20:
        recent_hr = sum(g["hr"] or 0 for g in games[-10:])
        prior_hr = sum(g["hr"] or 0 for g in games[-20:-10])
        sentences.append(
            f"Home run production has {_trend_word(recent_hr, prior_hr)} over his last 10 tracked games "
            f"({recent_hr:.0f} HR vs {prior_hr:.0f} in the prior 10)."
        )
        recent_tb = sum(g["tb"] or 0 for g in last10) / len(last10)
        season_tb = tb / total
        comparison = "above" if recent_tb > season_tb else ("below" if recent_tb < season_tb else "in line with")
        sentences.append(
            f"Total-base output over the last 10 tracked games is {comparison} his tracked-season rate."
        )
    sections.append(_panel("Recent Form", "Recent Form Indicators", _form_list(sentences),
                           "Computed from graded game outcomes only."))

    # Trend chart — last 20 games, total bases, HR games highlighted
    recent = games[-20:]
    points = [(_fmt_date(g["date"]), g["tb"] or 0, (g["hr"] or 0) >= 1) for g in recent]
    chart = _bar_strip(points, f"Total bases by tracked game (last {len(recent)} games; green bars = home run games).")
    sections.append(_panel("Performance Trend", "Total Bases Trend", chart,
                           "Each bar is one graded game. Hover for the date and total."))

    # Rolling performance metrics
    rows = []
    for label, window in (("Last 5 tracked games", 5), ("Last 10 tracked games", 10),
                          ("Last 15 tracked games", 15), ("All tracked games", total)):
        sample = games[-window:]
        n = len(sample)
        rows.append([
            escape(label), str(n),
            str(sum(1 for g in sample if (g["hits"] or 0) >= 1)),
            f"{sum(g['hits'] or 0 for g in sample):.0f}",
            f"{sum(g['hr'] or 0 for g in sample):.0f}",
            f"{sum(g['rbi'] or 0 for g in sample):.0f}",
            f"{(sum(g['tb'] or 0 for g in sample) / n):.2f}",
        ])
    sections.append(_panel("Rolling Metrics", "Rolling Performance Metrics",
                           _table(["Window", "Games", "Games w/ Hit", "Hits", "HR", "RBI", "TB / Game"], rows)))

    # Monthly historical outcomes
    monthly = {}
    for g in games:
        monthly.setdefault(g["date"][:7], []).append(g)
    month_rows = []
    for month_key in sorted(monthly, reverse=True):
        sample = monthly[month_key]
        year, month = month_key.split("-")
        month_rows.append([
            escape(f"{_MONTHS[int(month) - 1]} {year}"), str(len(sample)),
            f"{sum(g['hits'] or 0 for g in sample):.0f}",
            f"{sum(g['hr'] or 0 for g in sample):.0f}",
            f"{sum(g['rbi'] or 0 for g in sample):.0f}",
            f"{sum(g['tb'] or 0 for g in sample):.0f}",
        ])
    sections.append(_panel("Historical Outcomes", "Monthly Outcome Summary",
                           _table(["Month", "Games", "Hits", "HR", "RBI", "Total Bases"], month_rows)))

    # Recent game log
    log_rows = [
        [_result_date_link(g["date"]), _fmt_count(g["hits"]), _fmt_count(g["tb"]),
         _fmt_count(g["hr"]), _fmt_count(g["rbi"])]
        for g in reversed(games[-15:])
    ]
    sections.append(_panel("Game Log", "Recent Game Log",
                           _table(["Date", "Hits", "Total Bases", "HR", "RBI"], log_rows),
                           "Dates link to the full graded slate in the MLB Results Archive."))
    return sections


def _pitcher_sections(entry):
    games = sorted(entry["pitcher_games"], key=lambda g: g["date"])
    if not games:
        return []
    name = entry["name"]
    total = len(games)
    ks = sum(g["ks"] or 0 for g in games)
    outs = sum(g["outs"] or 0 for g in games if g["outs"] is not None)
    sections = []

    cards = [
        ("Tracked Starts", str(total), f"Graded starts since {_fmt_date(games[0]['date'])}"),
        ("Last Tracked Start", _fmt_date(games[-1]["date"]), "Most recent graded result"),
        ("Strikeouts", _fmt_count(ks), f"{ks / total:.1f} strikeouts per tracked start"),
        ("Innings Recorded", _fmt_ip(outs), "Across all tracked starts"),
    ]
    sections.append(_panel("Pitching Overview", f"{name} — Tracked Pitching History", _cards(cards),
                           "Outcome history from EdgeRanked's graded MLB result tracking."))

    last5 = games[-5:]
    six_plus = sum(1 for g in last5 if (g["ks"] or 0) >= 6)
    sentences = [
        f"Struck out six or more batters in {six_plus} of his last {len(last5)} tracked starts.",
        f"Averaging {sum(g['ks'] or 0 for g in last5) / len(last5):.1f} strikeouts over his last {len(last5)} tracked starts.",
    ]
    if total >= 6:
        recent_k = sum(g["ks"] or 0 for g in games[-3:]) / 3
        season_k = ks / total
        comparison = "above" if recent_k > season_k else ("below" if recent_k < season_k else "in line with")
        sentences.append(f"Recent strikeout rate is {comparison} his tracked-season average.")
    sections.append(_panel("Recent Form", "Recent Form Indicators", _form_list(sentences),
                           "Computed from graded start outcomes only."))

    recent = games[-15:]
    points = [(_fmt_date(g["date"]), g["ks"] or 0, (g["ks"] or 0) >= 7) for g in recent]
    chart = _bar_strip(points, f"Strikeouts by tracked start (last {len(recent)} starts; green bars = 7+ strikeout starts).")
    sections.append(_panel("Performance Trend", "Strikeout Trend", chart,
                           "Each bar is one graded start. Hover for the date and total."))

    rows = []
    for label, window in (("Last 3 tracked starts", 3), ("Last 5 tracked starts", 5),
                          ("Last 10 tracked starts", 10), ("All tracked starts", total)):
        sample = games[-window:]
        n = len(sample)
        sample_outs = [g["outs"] for g in sample if g["outs"] is not None]
        ip_per = _fmt_ip(sum(sample_outs) / len(sample_outs)) if sample_outs else "—"
        rows.append([
            escape(label), str(n),
            f"{sum(g['ks'] or 0 for g in sample):.0f}",
            f"{(sum(g['ks'] or 0 for g in sample) / n):.1f}",
            ip_per,
        ])
    sections.append(_panel("Rolling Metrics", "Rolling Performance Metrics",
                           _table(["Window", "Starts", "Strikeouts", "K / Start", "IP / Start"], rows)))

    log_rows = [
        [_result_date_link(g["date"]), escape(g["opponent"] or "—"),
         _fmt_count(g["ks"]), _fmt_ip(g["outs"])]
        for g in reversed(games[-15:])
    ]
    sections.append(_panel("Game Log", "Recent Start Log",
                           _table(["Date", "Opponent", "Strikeouts", "IP"], log_rows),
                           "Dates link to the full graded slate in the MLB Results Archive."))
    return sections


def _cards(cards):
    body = []
    for label, value, caption in cards:
        body.append(
            "<article class='metric-card'>"
            f"<div class='metric-label'>{escape(str(label))}</div>"
            f"<div class='metric-value'>{escape(str(value))}</div>"
            f"<p class='metric-caption'>{escape(str(caption))}</p>"
            "</article>"
        )
    return "<div class='metric-grid'>" + "".join(body) + "</div>"


# Shared render primitives, reused by the team pages module.
render_panel = _panel
render_table = _table
render_cards_grid = _cards
render_bar_strip = _bar_strip
render_form_list = _form_list


def player_kind(entry):
    kinds = []
    if entry.get("hitter_games"):
        kinds.append("Hitter")
    if entry.get("pitcher_games"):
        kinds.append("Pitcher")
    return " / ".join(kinds) or "Player"


def render_history_body(entry, site_origin):
    """Full history body for one player: sections + JSON-LD. Actuals only."""
    name = entry["name"]
    slug = entry["slug"]
    parts = [PAGE_STYLE]
    parts.extend(_hitter_sections(entry))
    parts.extend(_pitcher_sections(entry))

    methodology = (
        "<p class='muted'>EdgeRanked grades every tracked MLB slate against official results. "
        "This page summarizes the recorded outcomes — hits, total bases, home runs, RBI, "
        "strikeouts, and innings — for games where this player appeared in our tracking. "
        "It reflects tracked games only, not the player's complete MLB statistics, and "
        "tracking windows may contain gaps. Today's model projections are not shown here.</p>"
    )
    parts.append(_panel("Methodology", "How This History Is Tracked", methodology))

    page_url = f"{site_origin}/mlb/player/{slug}"
    json_ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "ProfilePage",
                "name": f"{name} — MLB Tracked Performance History",
                "url": page_url,
                "mainEntity": {
                    "@type": "Person",
                    "name": name,
                    "url": page_url,
                    "description": f"{name} MLB tracked game outcomes, trends, and game logs on EdgeRanked AI.",
                },
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{site_origin}/"},
                    {"@type": "ListItem", "position": 2, "name": "MLB", "item": f"{site_origin}/mlb"},
                    {"@type": "ListItem", "position": 3, "name": name, "item": page_url},
                ],
            },
        ],
    }
    parts.append(f"<script type='application/ld+json'>{json.dumps(json_ld)}</script>")
    return "".join(parts)


def history_meta(entry):
    """Title/description strings for the permanent profile page."""
    name = entry["name"]
    kind = player_kind(entry)
    games = len(entry.get("hitter_games") or []) + len(entry.get("pitcher_games") or [])
    description = (
        f"{name} MLB performance history on EdgeRanked AI: {games} tracked game outcomes, "
        f"recent form, rolling trends, and a graded game log. {kind} coverage with "
        "season summaries and historical results."
    )
    title = f"{name} MLB Player History, Game Log & Trends | EdgeRanked AI"
    return title, description
