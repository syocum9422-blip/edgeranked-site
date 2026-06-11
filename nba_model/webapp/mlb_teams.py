"""Permanent MLB team pages and team strikeout pages — public SEO content only.

Routes
  * ``/mlb/teams``                    — team index (AL / NL directory)
  * ``/mlb/team/<team_slug>``         — permanent team profile
  * ``/mlb/team/<team_slug>/strikeouts`` — permanent team strikeout profile

Team identity (name, league, division, home stadium) comes from the static
stadium dataset, so every page renders year-round regardless of the slate.
Performance content is built from graded tracking history via
``mlb_player_history`` plus two public stat files; the roster map reads only
player-name and team columns from the daily public-safe CSVs.

Premium-safety contract: no model probability, projection, ranking, or
confidence column is ever read here. Teams on today's slate get a subscriber
teaser instead of any current model output.
"""

from __future__ import annotations

import json
import time
from datetime import date
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from nba_model.webapp import seo_tiers
from nba_model.webapp.mlb_player_history import (
    PAGE_STYLE,
    all_player_histories,
    format_tracked_date,
    render_bar_strip,
    render_cards_grid,
    render_form_list,
    render_panel,
    render_table,
    slugify_player_name,
)
from nba_model.webapp.mlb_stadiums import STADIUMS

ET = ZoneInfo("America/New_York")
CACHE_TTL_SECONDS = 600

TEAMS = [
    {
        "name": s["team"],
        "slug": slugify_player_name(s["team"]),
        "league": s["league"],
        "division": s["division"],
        "stadium_name": s["name"],
        "stadium_slug": s["slug"],
        "city": s["city"],
    }
    for s in STADIUMS
]
BY_SLUG = {t["slug"]: t for t in TEAMS}
BY_NAME = {t["name"]: t for t in TEAMS}

_CACHE = {"key": None, "built_at": 0.0, "data": None}


def _read_csv(path):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _mtime(path):
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


def _clean(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _team_data(output_dir, data_dir):
    """Cached bundle: rosters, lineup K games, season K% table, today's games."""
    output_dir, data_dir = Path(output_dir), Path(data_dir)
    paths = {
        "roster": output_dir / "hitter_predictions_public_safe.csv",
        "starters": output_dir / "mlb_pitcher_projections_today.csv",
        "pitcher_tracking": output_dir / "pitcher_tracking.csv",
        "team_k": data_dir / "team_batting_k_pct_season.csv",
        "weather": output_dir / "mlb_weather_today.json",
    }
    key = tuple((name, _mtime(p)) for name, p in sorted(paths.items()))
    now = time.time()
    if _CACHE["data"] is not None and _CACHE["key"] == key and now - _CACHE["built_at"] < CACHE_TTL_SECONDS:
        return _CACHE["data"]

    # Last-known roster: player-name + team columns only.
    rosters = {}
    player_team = {}
    df = _read_csv(paths["roster"])
    if not df.empty and {"hitter_name", "team"}.issubset(df.columns):
        for _, row in df[["hitter_name", "team"]].drop_duplicates().iterrows():
            name, team = _clean(row["hitter_name"]), _clean(row["team"])
            if name and team in BY_NAME:
                rosters.setdefault(team, set()).add(name)
                player_team.setdefault(slugify_player_name(name), team)

    # Today's probable starters: name + team columns only (public schedule info).
    probables = {}
    df = _read_csv(paths["starters"])
    if not df.empty and {"Pitcher", "Team"}.issubset(df.columns):
        for _, row in df[["Pitcher", "Team"]].drop_duplicates().iterrows():
            name, team = _clean(row["Pitcher"]), _clean(row["Team"])
            if name and team in BY_NAME:
                probables.setdefault(team, name)
                player_team.setdefault(slugify_player_name(name), team)

    # Lineup strikeout history: opposing starters' graded Ks vs each team.
    lineup_k = {}
    df = _read_csv(paths["pitcher_tracking"])
    if not df.empty and {"date", "opponent", "actual_strikeouts"}.issubset(df.columns):
        sub = df[["date", "opponent", "actual_strikeouts"]].copy()
        sub["actual_strikeouts"] = pd.to_numeric(sub["actual_strikeouts"], errors="coerce")
        sub = sub[sub["actual_strikeouts"].notna()]
        sub["date"] = sub["date"].astype(str)
        for (team, day), grp in sub.groupby(["opponent", "date"]):
            team = _clean(team)
            if team in BY_NAME:
                lineup_k.setdefault(team, []).append({"date": day, "ks": float(grp["actual_strikeouts"].sum())})
        for games in lineup_k.values():
            games.sort(key=lambda g: g["date"])

    # Season team batting K% (FanGraphs-sourced public stat).
    team_k = {}
    df = _read_csv(paths["team_k"])
    if not df.empty and {"team", "k_pct"}.issubset(df.columns):
        for _, row in df.iterrows():
            team = _clean(row["team"])
            k_pct = pd.to_numeric(row.get("k_pct"), errors="coerce")
            if team in BY_NAME and pd.notna(k_pct):
                team_k[team] = {
                    "k_pct": float(k_pct),
                    "pa": pd.to_numeric(row.get("pa"), errors="coerce"),
                    "so": pd.to_numeric(row.get("so"), errors="coerce"),
                }
    ranked = sorted(team_k.items(), key=lambda item: item[1]["k_pct"], reverse=True)
    for rank, (team, info) in enumerate(ranked, start=1):
        info["rank"] = rank  # 1 = highest strikeout rate in MLB

    # Teams playing today (public schedule, from the weather feed).
    plays_today = {}
    weather = _read_json(paths["weather"])
    today = date.today().isoformat()
    for game in weather.get("games") or []:
        if _clean(game.get("game_date")) != today:
            continue
        away = _clean(game.get("away_team_name") or game.get("away_team"))
        home = _clean(game.get("home_team_name") or game.get("home_team"))
        if away in BY_NAME and home in BY_NAME:
            plays_today[away] = home
            plays_today[home] = away

    data = {
        "rosters": {team: sorted(names) for team, names in rosters.items()},
        "probables": probables,
        "player_team": player_team,
        "lineup_k": lineup_k,
        "team_k": team_k,
        "plays_today": plays_today,
    }
    _CACHE.update({"key": key, "built_at": now, "data": data})
    return data


def player_team_map(output_dir, data_dir):
    """Last-known {player_slug: team_full_name} from public-safe roster files."""
    return _team_data(output_dir, data_dir)["player_team"]


def team_for_player(output_dir, data_dir, player_slug):
    """Last-known (team_name, team_slug) for a player slug, or (None, None)."""
    data = _team_data(output_dir, data_dir)
    team = data["player_team"].get(player_slug)
    if team and team in BY_NAME:
        return team, BY_NAME[team]["slug"]
    return None, None


def _team_offense(team, data, hitter_index):
    """Graded outcomes of the team's last-known roster, aggregated per date."""
    names = data["rosters"].get(team["name"], [])
    per_date = {}
    leaders = []
    for name in names:
        entry = hitter_index.get(slugify_player_name(name))
        if not entry or not entry.get("hitter_games"):
            continue
        games = entry["hitter_games"]
        leaders.append({
            "name": entry["name"],
            "slug": entry["slug"],
            "games": len(games),
            "hits": sum(g["hits"] or 0 for g in games),
            "hr": sum(g["hr"] or 0 for g in games),
            "rbi": sum(g["rbi"] or 0 for g in games),
        })
        for g in games:
            agg = per_date.setdefault(g["date"], {"players": 0, "hits": 0.0, "hr": 0.0, "rbi": 0.0, "tb": 0.0})
            agg["players"] += 1
            agg["hits"] += g["hits"] or 0
            agg["hr"] += g["hr"] or 0
            agg["rbi"] += g["rbi"] or 0
            agg["tb"] += g["tb"] or 0
    dates = [dict(date=d, **vals) for d, vals in sorted(per_date.items())]
    return dates, leaders


def _result_date_link(date_str):
    return f"<a href='/mlb/results/{escape(date_str)}'>{escape(format_tracked_date(date_str))}</a>"


def _player_link(name, slug=None):
    slug = slug or slugify_player_name(name)
    return f"<a href='/mlb/player/{escape(slug)}'>{escape(name)}</a>"


def _teaser(team, data):
    if team["name"] not in data["plays_today"]:
        return ""
    opponent = data["plays_today"][team["name"]]
    return seo_tiers.render_premium_locked_section(
        seo_tiers.PREMIUM_GAME_ITEMS,
        heading="Today's Projections Are Live",
        note=(
            f"The {team['name']} play the {opponent} today. Today's projections and "
            "advanced team insights are available to subscribers."
        ),
        cta_label="Unlock Today's MLB Projections",
        cta_href="/pricing",
    )


def _trend_word(recent, prior):
    if recent > prior:
        return "increased"
    if recent < prior:
        return "decreased"
    return "held steady"


def _fmt_pct(value):
    return f"{value * 100:.1f}%"


def _breadcrumb_ld(site_origin, trail):
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": f"{site_origin}{path}"}
            for i, (name, path) in enumerate(trail)
        ],
    }


def _json_ld(payload):
    return f"<script type='application/ld+json'>{json.dumps(payload)}</script>"


# --------------------------------------------------------------------------
# Page bodies
# --------------------------------------------------------------------------

def build_team_index_body(site_origin):
    divisions = {}
    for team in TEAMS:
        divisions.setdefault(team["division"], []).append(team)
    parts = [PAGE_STYLE]
    intro = (
        "<p class='muted'>Permanent profiles for all 30 MLB clubs: tracked offensive "
        "history, strikeout tendencies, rosters with player profile links, and home "
        "ballpark intelligence. Updated as graded results are recorded.</p>"
        "<p class='muted'><a href='/mlb/players'>Browse the full A–Z player directory</a> · "
        "<a href='/mlb/leaderboards'>Daily leaderboards</a> · "
        "<a href='/mlb/stadiums'>Stadium guide</a></p>"
    )
    parts.append(render_panel("MLB Teams", "All 30 MLB Team Profiles", intro))
    order = ["AL East", "AL Central", "AL West", "NL East", "NL Central", "NL West"]
    for division in order:
        teams = divisions.get(division, [])
        if not teams:
            continue
        rows = [
            [
                f"<a href='/mlb/team/{escape(t['slug'])}'>{escape(t['name'])}</a>",
                f"<a href='/mlb/team/{escape(t['slug'])}/strikeouts'>Strikeout Profile</a>",
                f"<a href='/mlb/stadium/{escape(t['stadium_slug'])}'>{escape(t['stadium_name'])}</a>",
                escape(t["city"]),
            ]
            for t in sorted(teams, key=lambda t: t["name"])
        ]
        parts.append(render_panel(division, division, render_table(["Team", "Strikeouts", "Home Stadium", "City"], rows)))

    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "ItemList",
                "name": "MLB Team Profiles",
                "itemListElement": [
                    {"@type": "ListItem", "position": i + 1, "name": t["name"],
                     "url": f"{site_origin}/mlb/team/{t['slug']}"}
                    for i, t in enumerate(TEAMS)
                ],
            },
            _breadcrumb_ld(site_origin, [("Home", "/"), ("MLB", "/mlb"), ("Teams", "/mlb/teams")]),
        ],
    }
    parts.append(_json_ld(ld))
    return "".join(parts)


def build_team_body(team, output_dir, data_dir, site_origin):
    data = _team_data(output_dir, data_dir)
    hitter_index, _ = all_player_histories(
        Path(output_dir) / "hitter_tracking.csv", Path(output_dir) / "pitcher_tracking.csv"
    )
    dates, leaders = _team_offense(team, data, hitter_index)
    k_info = data["team_k"].get(team["name"], {})
    parts = [PAGE_STYLE]

    # Overview
    cards = [
        ("Division", team["division"], f"{team['league']} · {team['city']}"),
        ("Home Stadium", team["stadium_name"], "Ballpark intelligence linked below"),
    ]
    if dates:
        cards.append(("Tracked Game Dates", str(len(dates)),
                      f"Graded roster outcomes since {format_tracked_date(dates[0]['date'])}"))
    if k_info:
        cards.append(("Season Batting K%", _fmt_pct(k_info["k_pct"]),
                      f"#{k_info['rank']} highest strikeout rate in MLB"))
    overview_links = (
        "<p class='muted' style='margin-top:14px'>"
        f"<a href='/mlb/stadium/{escape(team['stadium_slug'])}'>{escape(team['stadium_name'])} ballpark profile</a> · "
        f"<a href='/mlb/team/{escape(team['slug'])}/strikeouts'>{escape(team['name'])} strikeout profile</a> · "
        "<a href='/mlb/results'>MLB Results Archive</a></p>"
    )
    parts.append(render_panel("Team Overview", f"{team['name']} — Team Profile",
                              render_cards_grid(cards) + overview_links,
                              "Permanent team profile built from tracked, graded game outcomes."))

    parts.append(_teaser(team, data))

    if dates:
        # Recent team performance
        recent = dates[-10:]
        rows = [
            [_result_date_link(d["date"]), str(d["players"]), f"{d['hits']:.0f}",
             f"{d['hr']:.0f}", f"{d['rbi']:.0f}", f"{d['tb']:.0f}"]
            for d in reversed(recent)
        ]
        parts.append(render_panel(
            "Recent Performance", "Recent Team Performance",
            render_table(["Date", "Tracked Hitters", "Hits", "HR", "RBI", "Total Bases"], rows),
            "Combined graded outcomes for tracked hitters on the current roster. Dates link to full slate results.",
        ))

        # Form indicators
        last5 = dates[-5:]
        prior5 = dates[-10:-5]
        sentences = [
            f"Tracked hitters combined for {sum(d['hits'] for d in last5):.0f} hits over the last {len(last5)} tracked dates.",
            f"{sum(d['hr'] for d in last5):.0f} home runs across the last {len(last5)} tracked dates.",
        ]
        if prior5:
            recent_hr = sum(d["hr"] for d in last5)
            prior_hr = sum(d["hr"] for d in prior5)
            sentences.append(
                f"Power production has {_trend_word(recent_hr, prior_hr)} versus the prior five tracked dates "
                f"({recent_hr:.0f} HR vs {prior_hr:.0f})."
            )
        parts.append(render_panel("Recent Form", "Recent Form Indicators", render_form_list(sentences),
                                  "Computed from graded outcomes of tracked roster hitters only."))

        # Power production trend
        recent20 = dates[-20:]
        points = [(format_tracked_date(d["date"]), d["hr"], d["hr"] >= 2) for d in recent20]
        chart = render_bar_strip(points, f"Home runs by tracked date (last {len(recent20)} dates; green bars = multi-homer dates).")
        parts.append(render_panel("Power Production", "Historical Power Production", chart,
                                  "Each bar is one tracked slate date for the current roster."))

        # Monthly offensive history
        monthly = {}
        for d in dates:
            monthly.setdefault(d["date"][:7], []).append(d)
        month_rows = []
        for key in sorted(monthly, reverse=True):
            sample = monthly[key]
            year, month = key.split("-")
            month_name = ["January", "February", "March", "April", "May", "June", "July",
                          "August", "September", "October", "November", "December"][int(month) - 1]
            month_rows.append([
                escape(f"{month_name} {year}"), str(len(sample)),
                f"{sum(d['hits'] for d in sample):.0f}", f"{sum(d['hr'] for d in sample):.0f}",
                f"{sum(d['rbi'] for d in sample):.0f}", f"{sum(d['tb'] for d in sample):.0f}",
            ])
        parts.append(render_panel("Historical Trends", "Historical Offensive Performance",
                                  render_table(["Month", "Tracked Dates", "Hits", "HR", "RBI", "Total Bases"], month_rows)))

        # Team leaders
        if leaders:
            hr_leaders = sorted(leaders, key=lambda l: (-l["hr"], -l["hits"]))[:5]
            hit_leaders = sorted(leaders, key=lambda l: (-l["hits"], -l["hr"]))[:5]
            hr_rows = [[_player_link(l["name"], l["slug"]), str(l["games"]), f"{l['hr']:.0f}", f"{l['rbi']:.0f}"] for l in hr_leaders]
            hit_rows = [[_player_link(l["name"], l["slug"]), str(l["games"]), f"{l['hits']:.0f}", f"{l['rbi']:.0f}"] for l in hit_leaders]
            inner = (
                "<h3 style='margin:14px 0 0'>Tracked Home Run Leaders</h3>"
                + render_table(["Player", "Tracked Games", "HR", "RBI"], hr_rows)
                + "<h3 style='margin:22px 0 0'>Tracked Hit Leaders</h3>"
                + render_table(["Player", "Tracked Games", "Hits", "RBI"], hit_rows)
            )
            parts.append(render_panel("Team Leaders", "Recent Team Leaders", inner,
                                      "Leaders among tracked hitters on the current roster. Names link to full player histories."))
    else:
        parts.append(render_panel("Recent Performance", "Tracked History Pending",
                                  "<p class='muted'>Graded outcome history for this roster will appear here as results are recorded.</p>"))

    # Active player directory
    roster = data["rosters"].get(team["name"], [])
    directory_bits = [_player_link(name) for name in roster]
    probable = data["probables"].get(team["name"])
    if probable:
        directory_bits.append(_player_link(probable) + " <span class='muted'>(probable starter)</span>")
    if directory_bits:
        inner = "<p style='line-height:2.1'>" + " · ".join(directory_bits) + "</p>"
        parts.append(render_panel("Player Directory", "Active Player Directory", inner,
                                  "Recently active tracked players. Each link opens a permanent player history profile."))

    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "SportsTeam",
                "name": team["name"],
                "sport": "Baseball",
                "url": f"{site_origin}/mlb/team/{team['slug']}",
                "memberOf": {"@type": "SportsOrganization", "name": f"MLB {team['division']}"},
                "location": {"@type": "StadiumOrArena", "name": team["stadium_name"]},
            },
            _breadcrumb_ld(site_origin, [("Home", "/"), ("MLB", "/mlb"), ("Teams", "/mlb/teams"),
                                         (team["name"], f"/mlb/team/{team['slug']}")]),
        ],
    }
    parts.append(_json_ld(ld))
    return "".join(parts)


def build_team_strikeout_body(team, output_dir, data_dir, site_origin):
    data = _team_data(output_dir, data_dir)
    k_info = data["team_k"].get(team["name"], {})
    games = data["lineup_k"].get(team["name"], [])
    parts = [PAGE_STYLE]

    cards = [("Division", team["division"], f"{team['league']} · {team['city']}")]
    if k_info:
        cards.append(("Season Batting K%", _fmt_pct(k_info["k_pct"]),
                      f"#{k_info['rank']} highest strikeout rate in MLB"))
        so, pa = k_info.get("so"), k_info.get("pa")
        if pd.notna(so) and pd.notna(pa):
            cards.append(("Season Strikeouts", f"{so:.0f}", f"Across {pa:.0f} plate appearances"))
    if games:
        total_k = sum(g["ks"] for g in games)
        cards.append(("Tracked K / Game", f"{total_k / len(games):.1f}",
                      f"vs opposing starters across {len(games)} tracked games"))
    intro_links = (
        "<p class='muted' style='margin-top:14px'>"
        f"<a href='/mlb/team/{escape(team['slug'])}'>{escape(team['name'])} team profile</a> · "
        f"<a href='/mlb/stadium/{escape(team['stadium_slug'])}'>{escape(team['stadium_name'])} ballpark profile</a> · "
        "<a href='/mlb/results'>MLB Results Archive</a></p>"
    )
    parts.append(render_panel("Strikeout Overview", f"{team['name']} — Strikeout Profile",
                              render_cards_grid(cards) + intro_links,
                              "How often this lineup strikes out: season rates plus graded game-by-game history."))

    parts.append(_teaser(team, data))

    if games:
        # Trend chart + sentences
        recent20 = games[-20:]
        points = [(format_tracked_date(g["date"]), g["ks"], g["ks"] >= 9) for g in recent20]
        chart = render_bar_strip(points, f"Strikeouts vs the opposing starter by tracked game (last {len(recent20)}; green bars = 9+ strikeout games).")
        parts.append(render_panel("Recent Trends", "Recent Strikeout Trends", chart,
                                  "Strikeouts recorded by opposing starting pitchers against this lineup in tracked games."))

        last5 = games[-5:]
        prior5 = games[-10:-5]
        season_rate = sum(g["ks"] for g in games) / len(games)
        recent_rate = sum(g["ks"] for g in last5) / len(last5)
        comparison = "above" if recent_rate > season_rate else ("below" if recent_rate < season_rate else "in line with")
        sentences = [
            f"Struck out {sum(g['ks'] for g in last5):.0f} times against opposing starters over the last {len(last5)} tracked games.",
            f"Recent strikeout rate is {comparison} the tracked-season average ({recent_rate:.1f} vs {season_rate:.1f} per game).",
        ]
        if prior5:
            sentences.append(
                f"Strikeout volume has {_trend_word(sum(g['ks'] for g in last5), sum(g['ks'] for g in prior5))} "
                "versus the prior five tracked games."
            )
        parts.append(render_panel("Trend Indicators", "Recent Trend Indicators", render_form_list(sentences),
                                  "Computed from graded outcomes only."))

        # Rolling metrics
        rows = []
        for label, window in (("Last 5 tracked games", 5), ("Last 10 tracked games", 10),
                              ("Last 15 tracked games", 15), ("All tracked games", len(games))):
            sample = games[-window:]
            rows.append([escape(label), str(len(sample)),
                         f"{sum(g['ks'] for g in sample):.0f}",
                         f"{sum(g['ks'] for g in sample) / len(sample):.1f}"])
        parts.append(render_panel("Rolling Metrics", "Rolling Strikeout Metrics",
                                  render_table(["Window", "Games", "Strikeouts", "K / Game"], rows)))

        # Monthly history
        monthly = {}
        for g in games:
            monthly.setdefault(g["date"][:7], []).append(g)
        month_rows = []
        for key in sorted(monthly, reverse=True):
            sample = monthly[key]
            year, month = key.split("-")
            month_name = ["January", "February", "March", "April", "May", "June", "July",
                          "August", "September", "October", "November", "December"][int(month) - 1]
            month_rows.append([escape(f"{month_name} {year}"), str(len(sample)),
                               f"{sum(g['ks'] for g in sample):.0f}",
                               f"{sum(g['ks'] for g in sample) / len(sample):.1f}"])
        parts.append(render_panel("Historical Performance", "Historical Team Strikeout Performance",
                                  render_table(["Month", "Tracked Games", "Strikeouts", "K / Game"], month_rows)))
    else:
        parts.append(render_panel("Recent Trends", "Tracked History Pending",
                                  "<p class='muted'>Graded strikeout history for this lineup will appear here as results are recorded.</p>"))

    # League comparison (public season stat) with links to every team K page
    if data["team_k"]:
        ranked = sorted(data["team_k"].items(), key=lambda item: item[1]["k_pct"], reverse=True)
        rows = []
        for name, info in ranked:
            other = BY_NAME[name]
            label = f"<a href='/mlb/team/{escape(other['slug'])}/strikeouts'>{escape(name)}</a>"
            if name == team["name"]:
                label = f"<strong>{label}</strong>"
            rows.append([f"#{info['rank']}", label, _fmt_pct(info["k_pct"])])
        parts.append(render_panel("League Context", "MLB Team Strikeout Rates",
                                  render_table(["Rank", "Team", "Season Batting K%"], rows),
                                  "Full-season team batting strikeout rates (public stats). Higher rank = more strikeout-prone lineup."))

    ld = {
        "@context": "https://schema.org",
        "@graph": [
            _breadcrumb_ld(site_origin, [("Home", "/"), ("MLB", "/mlb"), ("Teams", "/mlb/teams"),
                                         (team["name"], f"/mlb/team/{team['slug']}"),
                                         ("Strikeouts", f"/mlb/team/{team['slug']}/strikeouts")]),
        ],
    }
    parts.append(_json_ld(ld))
    return "".join(parts)


# --------------------------------------------------------------------------
# Routes + sitemap
# --------------------------------------------------------------------------

def teams_sitemap_entries(output_dir=None):
    """(path, changefreq, priority, lastmod). lastmod is the latest graded
    tracking date — team content only changes when new results are graded."""
    lastmod = None
    if output_dir is not None:
        try:
            _, lastmod = all_player_histories(
                Path(output_dir) / "hitter_tracking.csv",
                Path(output_dir) / "pitcher_tracking.csv",
            )
        except Exception:
            lastmod = None
    entries = [("/mlb/teams", "weekly", "0.8", lastmod)]
    for team in TEAMS:
        entries.append((f"/mlb/team/{team['slug']}", "daily", "0.7", lastmod))
        entries.append((f"/mlb/team/{team['slug']}/strikeouts", "daily", "0.7", lastmod))
    return entries


def register_mlb_team_routes(flask_app, render_layout, output_dir, data_dir, site_origin, render_subnav=None):
    def _section_nav():
        return render_subnav("/mlb/teams") if render_subnav else None

    @flask_app.get("/mlb/teams")
    def mlb_teams_index():
        return render_layout(
            "MLB Teams",
            "Permanent profiles, tracked performance history, and strikeout tendencies for all 30 MLB clubs.",
            build_team_index_body(site_origin),
            "/mlb/teams",
            _section_nav(),
            hero_kicker="MLB Teams",
            meta_description=("All 30 MLB team profiles on EdgeRanked AI: tracked offensive history, "
                              "strikeout tendencies, rosters with player links, and ballpark intelligence."),
            document_title="MLB Team Profiles — All 30 Clubs | EdgeRanked AI",
        )

    @flask_app.get("/mlb/team/<team_slug>")
    def mlb_team_page(team_slug):
        team = BY_SLUG.get(str(team_slug).strip().lower())
        if not team:
            return _team_not_found(render_layout)
        return render_layout(
            team["name"],
            f"{team['division']} · {team['stadium_name']} · Tracked performance history",
            build_team_body(team, output_dir, data_dir, site_origin),
            "/mlb/teams",
            _section_nav(),
            hero_kicker="MLB Team Profile",
            meta_description=(f"{team['name']} team profile on EdgeRanked AI: tracked offensive history, "
                              f"recent form, team leaders, roster player profiles, and {team['stadium_name']} context."),
            document_title=f"{team['name']} Team Profile, History & Trends | EdgeRanked AI",
        )

    @flask_app.get("/mlb/team/<team_slug>/strikeouts")
    def mlb_team_strikeout_page(team_slug):
        team = BY_SLUG.get(str(team_slug).strip().lower())
        if not team:
            return _team_not_found(render_layout)
        return render_layout(
            f"{team['name']} Strikeouts",
            f"{team['division']} · Lineup strikeout rates, trends, and tracked history",
            build_team_strikeout_body(team, output_dir, data_dir, site_origin),
            "/mlb/teams",
            _section_nav(),
            hero_kicker="Team Strikeout Profile",
            meta_description=(f"How often do the {team['name']} strike out? Season batting K%, MLB rank, "
                              "recent strikeout trends, rolling metrics, and tracked game-by-game history."),
            document_title=f"{team['name']} Strikeout Rate, Trends & History | EdgeRanked AI",
        )


def _team_not_found(render_layout):
    body = (
        "<section class='panel empty-panel'>"
        "<div class='eyebrow'>Team Not Found</div>"
        "<h2>We couldn't find that MLB team.</h2>"
        "<p class='muted'>Browse the full team directory for every MLB club.</p>"
        "<div class='cta-row'><a class='cta-btn primary' href='/mlb/teams'>All MLB Teams</a></div>"
        "</section>"
    )
    html = render_layout(
        "MLB Team Not Found",
        "That team page is not available.",
        body,
        "/mlb/teams",
        hero_kicker="MLB Teams",
        meta_description="This MLB team page is not available. Browse EdgeRanked AI's full MLB team directory.",
        document_title="MLB Team Not Found | EdgeRanked AI",
    )
    return html, 404
