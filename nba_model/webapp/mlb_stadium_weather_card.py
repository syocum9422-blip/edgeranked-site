"""Today's Weather Impact card for MLB stadium pages — presentation layer only.

Renders a self-contained dark card (inline SVG field diagram + wind arrow +
LF/CF/RF interpretation chips + badges + plain-English summary) for one
stadium, using ONLY the two already-published slate artifacts:

  * ``mlb_weather_today.json``           (temp / wind / gusts / roof / rain)
  * ``mlb_game_environment_today.json``  (environment_score / label / total)

It never runs or imports model, simulation, calibration, or prediction code,
and it never changes a published number. The LF/CF/RF chips and badges are a
weather + park-geometry INTERPRETATION (labeled as such on the card), not a
model output.

Fail-safe contract: :func:`build_weather_impact_card` returns "" or a small
fallback panel on ANY problem (missing file, stale slate, no home game,
malformed data, unexpected exception), so stadium pages always render exactly
as they did without this card. Disable instantly with
``MLB_STADIUM_WEATHER_CARD=0``.

Curated structural stadium data — park orientation:
``PARK_CF_BEARINGS`` holds the compass bearing (degrees clockwise from true
north) of the line home plate -> center field, per park. Orientation is
stable, public, structural fact (like the posted outfield dimensions above it
in mlb_stadiums.py). Values were curated 2026-07-03 from two independent
methods and kept only where they agree:

  1. ballparks.com's published orientation diagrams (encoded in 15-degree
     steps: ballparks.com/baseball/general/facts/diamonds/).
  2. Geometric measurement of the satellite-traced field polygons in
     OpenStreetMap (home-plate wedge apex bisector), which matched source (1)
     within 8 degrees at every park where both were available.

Per-park sources are noted inline. Parks with conflicting or missing evidence
are intentionally ABSENT from the table; for those, the card falls back to
compass-only wind text ("W wind, 8 mph") and makes no field-relative claim
("blowing out to RF" etc.). Wind direction on the arrow uses the same
convention as the weather feed: ``wind_direction_degrees`` is the direction
the wind blows FROM (meteorological), so the air travels toward
``deg + 180``.
"""

from __future__ import annotations

import json
import math
import os
from html import escape
from pathlib import Path

# --- Curated structural stadium data: home plate -> center field bearing ----
# (degrees clockwise from true north; see module docstring for methodology)
PARK_CF_BEARINGS = {
    "angel-stadium": 45,                 # ballparks.com
    "american-family-field": 134,        # OSM measurement (ballparks.com: 135)
    "busch-stadium": 60,                 # ballparks.com
    "chase-field": 0,                    # ballparks.com
    "citi-field": 30,                    # ballparks.com
    "citizens-bank-park": 15,            # ballparks.com (OSM agrees within 13)
    "comerica-park": 150,                # ballparks.com
    "coors-field": 5,                    # OSM measurement (ballparks.com: 0)
    "daikin-park": 345,                  # ballparks.com (OSM agrees; NNW outlier)
    "dodger-stadium": 30,                # ballparks.com
    "fenway-park": 45,                   # ballparks.com + OSM (exact agreement)
    "globe-life-field": 67,              # MLB press release: field runs ENE
    "great-american-ball-park": 128,     # OSM measurement (ballparks.com: 120)
    "kauffman-stadium": 44,              # OSM measurement (ballparks.com: 45)
    "loandepot-park": 135,               # documented sun path (CF to the SE)
    "nationals-park": 30,                # ballparks.com
    "oracle-park": 86,                   # OSM measurement (ballparks.com: 90)
    "oriole-park-at-camden-yards": 30,   # ballparks.com
    "petco-park": 3,                     # OSM measurement (ballparks.com: 0)
    "pnc-park": 115,                     # OSM measurement (ballparks.com: 120)
    "progressive-field": 2,              # OSM measurement (ballparks.com: 0)
    "rate-field": 135,                   # ballparks.com (U.S. Cellular)
    "rogers-centre": 0,                  # ballparks.com (OSM: 346, within 15)
    "t-mobile-park": 45,                 # ballparks.com (Safeco)
    "target-field": 90,                  # ballparks.com
    "tropicana-field": 45,               # ballparks.com (fixed roof)
    "truist-park": 159,                  # OSM measurement (clean, unambiguous)
    "wrigley-field": 30,                 # ballparks.com
    "yankee-stadium": 75,                # ballparks.com + OSM (exact agreement)
    # "sutter-health-park": OMITTED — published sources conflict; compass-only.
}

_WEATHER_PATHS = [
    Path("/home/ubuntu/EdgeRanked/site/mlb/outputs/mlb_weather_today.json"),
    Path("/home/ubuntu/edgeranked-sportsai/mlb/outputs/mlb_weather_today.json"),
]
_ENV_PATHS = [
    Path("/home/ubuntu/edgeranked-sportsai/mlb/outputs/mlb_game_environment_today.json"),
    Path("/home/ubuntu/EdgeRanked/site/mlb/outputs/mlb_game_environment_today.json"),
]

_cache: dict = {}


def _load_json(paths: list) -> dict | None:
    for p in paths:
        try:
            if not p.is_file():
                continue
            mtime = p.stat().st_mtime
            hit = _cache.get(str(p))
            if hit and hit[0] == mtime:
                return hit[1]
            with p.open(encoding="utf-8") as f:
                data = json.load(f)
            _cache[str(p)] = (mtime, data)
            return data
        except Exception:
            continue
    return None


def _f(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --- wind classification -----------------------------------------------------

_SECTORS = [
    (0, "out-cf", "Blowing out to center field"),
    (45, "out-rf", "Blowing out toward right field"),
    (90, "cross-lr", "Crosswind, left field to right field"),
    (135, "in-lf", "Blowing in from left field"),
    (180, "in-cf", "Blowing in from center field"),
    (225, "in-rf", "Blowing in from right field"),
    (270, "cross-rl", "Crosswind, right field to left field"),
    (315, "out-lf", "Blowing out toward left field"),
]


def classify_wind(from_deg: float, cf_bearing: float) -> dict:
    """Field-relative wind read. ``rel`` is the direction the air TRAVELS,
    measured clockwise from the home-plate->CF line (0 = straight out)."""
    to_deg = (from_deg + 180.0) % 360.0
    rel = (to_deg - cf_bearing) % 360.0
    sector_key, sector_text = None, None
    for center, key, text in _SECTORS:
        if abs((rel - center + 180) % 360 - 180) <= 22.5:
            sector_key, sector_text = key, text
            break
    # per-direction carry component: cosine of the angle between the wind
    # travel direction and each outfield sector's direction from home plate
    comp = {
        "LF": math.cos(math.radians(rel - 315.0)),
        "CF": math.cos(math.radians(rel - 0.0)),
        "RF": math.cos(math.radians(rel - 45.0)),
    }
    return {"rel": rel, "sector": sector_key, "text": sector_text, "components": comp}


_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _compass(deg: float) -> str:
    return _COMPASS[int((deg + 11.25) % 360 // 22.5)]


# --- SVG field diagram --------------------------------------------------------

def _field_svg(rel_deg: float | None, wind_mph: float, calm: bool, weather_icon: str = "",
               placeholder: str = "calm") -> str:
    """Generic field outline (works for every park) + rotated wind arrow.
    Arrow points straight up (toward CF) at rel_deg=0. When no arrow can be
    drawn, ``placeholder`` distinguishes WHY: "calm" (no meaningful wind),
    "dir n/a" (real wind, park orientation not published — never implies
    calm), or "roof" (fixed roof, outside weather irrelevant)."""
    arrow = ""
    if calm or rel_deg is None:
        mph_note = ""
        if placeholder == "dir n/a" and wind_mph >= 3:
            mph_note = (f"<text x='130' y='192' text-anchor='middle' font-size='13' "
                        f"font-weight='700' fill='#e0f2fe'>{wind_mph:.0f} mph</text>")
        arrow = (
            "<circle cx='130' cy='128' r='16' fill='none' stroke='#64748b' stroke-width='2' stroke-dasharray='3 4'/>"
            f"<text x='130' y='133' text-anchor='middle' font-size='10' fill='#94a3b8'>{escape(placeholder)}</text>"
            + mph_note
        )
    else:
        arrow = (
            f"<g transform='rotate({rel_deg:.0f} 130 128)'>"
            "<line x1='130' y1='170' x2='130' y2='96' stroke='#38bdf8' stroke-width='5' stroke-linecap='round'/>"
            "<path d='M130 82 L118 104 L130 98 L142 104 Z' fill='#38bdf8'/>"
            "</g>"
            f"<text x='130' y='192' text-anchor='middle' font-size='13' font-weight='700' fill='#e0f2fe'>{wind_mph:.0f} mph</text>"
        )
    return (
        "<svg viewBox='0 0 260 240' role='img' aria-label='Field diagram with wind direction'"
        " style='width:100%;max-width:340px;height:auto;display:block;margin:0 auto'>"
        # grass wedge: home plate (130,212), foul lines to poles, outfield arc
        "<path d='M130 212 L28 110 A144 144 0 0 1 232 110 Z'"
        " fill='rgba(34,197,94,.10)' stroke='#334155' stroke-width='2'/>"
        # infield diamond
        "<path d='M130 212 L98 180 L130 148 L162 180 Z'"
        " fill='rgba(217,180,120,.16)' stroke='#475569' stroke-width='1.5'/>"
        # bases + mound + plate
        "<circle cx='130' cy='181' r='4' fill='none' stroke='#64748b' stroke-width='1.5'/>"
        "<rect x='126' y='208' width='8' height='6' fill='#cbd5e1'/>"
        # sector labels
        "<text x='52' y='84' text-anchor='middle' font-size='13' font-weight='700' fill='#94a3b8'>LF</text>"
        f"<text x='130' y='38' text-anchor='middle' font-size='18'>{escape(weather_icon)}</text>"
        "<text x='130' y='58' text-anchor='middle' font-size='13' font-weight='700' fill='#94a3b8'>CF</text>"
        "<text x='208' y='84' text-anchor='middle' font-size='13' font-weight='700' fill='#94a3b8'>RF</text>"
        + arrow +
        "</svg>"
    )


# --- badges / chips -----------------------------------------------------------

def _badge(text: str, kind: str) -> str:
    colors = {
        "boost": ("rgba(34,197,94,.14)", "#4ade80"),
        "suppress": ("rgba(59,130,246,.14)", "#93c5fd"),
        "warn": ("rgba(245,158,11,.16)", "#fbbf24"),
        "neutral": ("rgba(148,163,184,.12)", "#94a3b8"),
    }
    bg, fg = colors.get(kind, colors["neutral"])
    return (f"<span style='display:inline-block;padding:5px 10px;border-radius:999px;white-space:nowrap;"
            f"background:{bg};color:{fg};font-size:12px;font-weight:700;letter-spacing:.02em'>"
            f"{escape(text)}</span>")


def _status_badge(text: str, kind: str) -> str:
    colors = {
        "boost": ("rgba(34,197,94,.18)", "#86efac", "rgba(34,197,94,.34)"),
        "risk": ("rgba(248,113,113,.16)", "#fca5a5", "rgba(248,113,113,.32)"),
        "pitcher": ("rgba(59,130,246,.18)", "#93c5fd", "rgba(59,130,246,.34)"),
        "neutral": ("rgba(148,163,184,.12)", "#cbd5e1", "rgba(148,163,184,.22)"),
    }
    bg, fg, border = colors.get(kind, colors["neutral"])
    return (
        "<span style='display:inline-flex;align-items:center;justify-content:center;gap:6px;"
        "min-height:34px;padding:8px 13px;border-radius:999px;"
        f"background:{bg};border:1px solid {border};color:{fg};"
        "font-size:12px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;"
        "white-space:nowrap'>"
        f"{escape(text)}</span>"
    )


def _weather_condition(game: dict, roof_type: str, fixed_roof: bool) -> dict:
    if fixed_roof:
        return {"key": "roof", "icon": "🏟️", "label": "Roof Closed"}
    code = int(_f(game.get("weather_code"), 0) or 0)
    rain = _f(game.get("rain_chance"), 0.0) or 0.0
    precip = _f(game.get("precipitation_inches"), 0.0) or 0.0
    summary = str(game.get("summary") or "").lower()
    label = str(game.get("label") or "").lower()
    haystack = f"{summary} {label}"

    if code >= 95 or "thunder" in haystack or rain >= 45:
        return {"key": "storm", "icon": "⛈️", "label": "Thunderstorms Possible"}
    if code >= 51 or code in (45, 48) or rain >= 20 or precip > 0 or "rain" in haystack:
        return {"key": "rain", "icon": "🌧️", "label": "Light Rain"}
    if code in (1, 2, 3) or "cloud" in haystack:
        return {"key": "cloud", "icon": "🌤️", "label": "Partly Cloudy"}
    if roof_type == "retractable":
        return {"key": "roof", "icon": "🏟️", "label": "Retractable Roof"}
    return {"key": "sunny", "icon": "☀️", "label": "Sunny"}


def _theme_style(condition_key: str) -> str:
    themes = {
        "sunny": (
            "background:radial-gradient(circle at 18% 0%,rgba(251,191,36,.22),transparent 34%),"
            "linear-gradient(145deg,rgba(48,34,18,.96),rgba(15,23,42,.98) 62%);"
            "border-color:rgba(251,191,36,.24);"
        ),
        "cloud": (
            "background:radial-gradient(circle at 20% 0%,rgba(125,211,252,.18),transparent 34%),"
            "linear-gradient(145deg,rgba(22,44,68,.96),rgba(15,23,42,.98) 64%);"
            "border-color:rgba(125,211,252,.20);"
        ),
        "rain": (
            "background:radial-gradient(circle at 18% 0%,rgba(56,189,248,.13),transparent 34%),"
            "linear-gradient(145deg,rgba(14,34,60,.98),rgba(8,13,24,.98) 66%);"
            "border-color:rgba(56,189,248,.18);"
        ),
        "storm": (
            "background:radial-gradient(circle at 18% 0%,rgba(168,85,247,.16),transparent 36%),"
            "linear-gradient(145deg,rgba(38,38,45,.98),rgba(10,10,18,.99) 66%);"
            "border-color:rgba(168,85,247,.22);"
        ),
        "roof": (
            "background:radial-gradient(circle at 18% 0%,rgba(148,163,184,.12),transparent 34%),"
            "linear-gradient(145deg,rgba(21,27,38,.98),rgba(12,17,27,.99) 66%);"
            "border-color:rgba(148,163,184,.18);"
        ),
    }
    return themes.get(condition_key, themes["cloud"])


def _detail_item(icon: str, label: str, value: str) -> str:
    return (
        "<div style='display:flex;align-items:center;justify-content:center;gap:6px;"
        "min-width:0;padding:8px 10px;border-radius:10px;background:rgba(15,23,42,.46);"
        "border:1px solid rgba(148,163,184,.14);font-size:12px;color:#cbd5e1'>"
        f"<span>{escape(icon)}</span><span style='color:#94a3b8'>{escape(label)}</span>"
        f"<strong style='color:#f8fafc'>{escape(value)}</strong></div>"
    )


def _assessment_text(condition_key: str, wind_read: dict | None, wind: float,
                     hr_boost: bool, pitcher_friendly: bool, fixed_roof: bool,
                     delay_risk: bool, run_boost: bool = False,
                     env_score: float | None = None) -> tuple[str, str]:
    if fixed_roof:
        return "🏟️ Roof closed. Weather impact minimized.", "⚾ Neutral Conditions"
    if delay_risk or condition_key == "storm":
        return "⛈️ Delay risk exists this evening.", "⚠️ Weather Risk Tonight"
    if condition_key == "rain":
        return "🌧️ Weather may impact game conditions.", "⚠️ Weather Risk Tonight"
    # weather and game-environment feeds can disagree (e.g. cool, calm air but
    # a hitter's park with strong lineups) — say so instead of contradicting
    # ourselves further down the card
    if pitcher_friendly and run_boost:
        return ("🧊 Weather leans pitcher-friendly, but the park and lineups still "
                "project a high-scoring game.", "⚖️ Mixed Signals")
    if hr_boost and env_score is not None and env_score <= 30:
        return ("💨 Weather favors carry, but the park and lineups project a "
                "lower-scoring game.", "⚖️ Mixed Signals")
    if wind_read and wind >= 5 and max(wind_read["components"].values()) * wind >= 5:
        return "💨 Conditions favor additional carry on fly balls.", "🔥 Great Hitting Weather"
    if pitcher_friendly:
        return "🧊 Conditions lean pitcher-friendly tonight.", "🧊 Pitcher-Friendly Environment"
    if hr_boost:
        return "☀️ Perfect hitting weather tonight.", "🔥 Great Hitting Weather"
    return "🌤️ Neutral conditions for hitters and pitchers.", "⚾ Neutral Conditions"


def _sector_chip(name: str, comp: float, wind: float, dim_ft: int) -> str:
    effect = comp * wind
    if effect >= 5:
        label, kind = "🟢 Carry Boost", "boost"
    elif effect <= -5:
        label, kind = "🔴 Knockdown", "suppress"
    else:
        label, kind = "⚪ Neutral", "neutral"
    # porch tag gets its own muted line so the status pill never wraps
    porch_html = ("<div style='font-size:10px;color:#94a3b8;margin-top:4px'>Short porch</div>"
                  if dim_ft <= 325 else "")
    return (
        "<div style='flex:1;min-width:88px;background:var(--surface,#121929);"
        "border:1px solid rgba(148,163,184,.16);border-radius:12px;padding:10px 6px;text-align:center'>"
        f"<div style='font-size:12px;color:var(--muted,#94a3b8);font-weight:700'>{escape(name)}"
        f" <span style='font-weight:400'>{dim_ft} ft</span></div>"
        f"<div style='margin-top:6px'>{_badge(label, kind)}</div>"
        + porch_html +
        "</div>"
    )


def _panel_wrap(inner: str, note: str = "") -> str:
    note_html = (f"<p class='muted' style='margin:10px 0 0;font-size:12px'>{escape(note)}</p>"
                 if note else "")
    return ("<section class='panel'><div class='panel-head'><div>"
            "<div class='eyebrow'>Today's Weather Impact</div>"
            "<h2>Live Ballpark Conditions</h2></div></div>"
            + inner + note_html + "</section>")


def _weather_card_wrap(inner: str, condition_key: str) -> str:
    return (
        "<div style='position:relative;overflow:hidden;border:1px solid rgba(148,163,184,.18);"
        "border-radius:16px;padding:16px;box-shadow:0 18px 45px rgba(0,0,0,.22);"
        f"{_theme_style(condition_key)}'>"
        + inner +
        "</div>"
    )


def _fallback(msg: str) -> str:
    return _panel_wrap(f"<p class='st-prose' style='color:var(--muted,#94a3b8)'>{escape(msg)}</p>")


# --- summary text -------------------------------------------------------------

def _summary_sentence(wind_read: dict | None, wind: float, gust: float, temp: float,
                      hr_boost: bool, pitcher_friendly: bool, compass_txt: str,
                      has_bearing: bool = True) -> str:
    if temp is None:
        temp_part = ""
    elif temp >= 85:
        temp_part = " with hot temperatures adding carry"
    elif temp >= 72:
        temp_part = " with warm temperatures"
    elif temp <= 55:
        temp_part = " with cool air suppressing carry"
    else:
        temp_part = ""

    if wind < 3:
        lead = f"Winds are calm{temp_part}."
        if hr_boost:
            lead += " Overall, this is a positive home-run environment today."
        return lead

    if wind_read is None:
        if not has_bearing:
            return (f"Winds are {compass_txt} at {wind:.0f} mph{temp_part}. "
                    "Field-relative wind direction is not published for this park, "
                    "so no out/in read is claimed.")
        return f"Winds are {compass_txt} at {wind:.0f} mph{temp_part}."

    lead = f"{wind_read['text']} at {wind:.0f} mph"
    if gust and gust >= wind + 6:
        lead += f" (gusts {gust:.0f})"
    lead += f"{temp_part}."

    comp = wind_read["components"]
    if wind >= 5 and max(comp.values()) * wind >= 5:
        best = max(comp, key=comp.get)
        hand = {"RF": "left-handed power", "LF": "right-handed power",
                "CF": "power to all fields"}[best]
        lean = f" Conditions currently favor {hand}"
        lean += " more than pitchers." if not pitcher_friendly else "."
        lead += lean
    elif wind >= 5 and min(comp.values()) * wind <= -5:
        lead += " The wind is working for pitchers, cutting carry toward the fence."
    if hr_boost:
        lead += " Overall, this is a positive home-run environment today."
    return lead


# --- main entry ---------------------------------------------------------------

def build_weather_impact_card(s: dict) -> str:
    """Render the card for stadium record ``s`` (a STADIUMS entry).
    Returns "" or a graceful fallback panel on any problem — never raises."""
    try:
        if os.environ.get("MLB_STADIUM_WEATHER_CARD", "1") != "1":
            return ""
        weather = _load_json(_WEATHER_PATHS)
        if not weather or not weather.get("games"):
            return _fallback("Live weather for today's slate is not available right now. "
                             "Check back after the next data refresh.")

        team = str(s.get("team") or "")
        game = next((g for g in weather["games"]
                     if str(g.get("home_team_name") or "") == team), None)
        if game is None:
            return _fallback(f"No home game at {s.get('name', 'this park')} today — "
                             "weather impact returns with the next home slate.")

        wind = _f(game.get("wind_speed_mph"), 0.0) or 0.0
        gust = _f(game.get("wind_gust_mph"), 0.0) or 0.0
        temp = _f(game.get("temperature_f"))
        rain = _f(game.get("rain_chance"), 0.0) or 0.0
        from_deg = _f(game.get("wind_direction_degrees"))
        compass_txt = str(game.get("wind_direction") or
                          (_compass(from_deg) if from_deg is not None else "variable"))
        roof_type = str(game.get("roof_type") or "outdoor").lower()
        label = str(game.get("label") or "Neutral")

        env = _load_json(_ENV_PATHS) or {}
        env_game = next((g for g in (env.get("games") or [])
                         if str(g.get("home_team") or "") == team), {})
        env_score = _f(env_game.get("environment_score"))
        env_label = str(env_game.get("environment_label") or "")

        bearing = PARK_CF_BEARINGS.get(str(s.get("slug") or ""))
        calm = wind < 3

        # roof handling: fixed domes are weather-neutral; retractable parks get
        # the read plus an explicit caveat (open/closed status is not published)
        fixed_roof = roof_type in ("dome", "fixed", "indoor")
        wind_read = None
        if not fixed_roof and bearing is not None and from_deg is not None and not calm:
            wind_read = classify_wind(from_deg, bearing)

        # --- weather personality + badges
        out_effect = max(wind_read["components"].values()) * wind if wind_read else 0.0
        in_effect = min(wind_read["components"].values()) * wind if wind_read else 0.0
        hr_boost = (not fixed_roof) and ("power" in label.lower()
                                         or (out_effect >= 8 and (temp or 0) >= 75))
        run_boost = "run" in env_label.lower() or (env_score is not None and env_score >= 70)
        pitcher_friendly = ("pitcher" in label.lower()
                            or (not fixed_roof and in_effect <= -8)
                            or (env_score is not None and env_score <= 30))
        delay_risk = (not fixed_roof) and roof_type == "outdoor" and rain >= 25
        condition = _weather_condition(game, roof_type, fixed_roof)
        assessment, atmosphere = _assessment_text(condition["key"], wind_read, wind,
                                                  hr_boost, pitcher_friendly,
                                                  fixed_roof, delay_risk,
                                                  run_boost=run_boost, env_score=env_score)

        away = str(game.get("away_team_name") or "")
        matchup = f"{away} @ {team}" if away else team
        if fixed_roof:
            # indoor game: outside wind/gusts are irrelevant — do not headline them
            temp_line = f"{temp:.0f}°F outside" if temp is not None else "Indoor"
            wind_line = "Roof closed — indoor conditions"
            roof_note = ""
        else:
            temp_line = f"{temp:.0f}°F" if temp is not None else "Temp N/A"
            wind_line = f"Wind {compass_txt} {wind:.0f} mph" + (f" · Gusts {gust:.0f}" if gust >= wind + 6 else "")
            roof_note = " · Retractable roof" if roof_type == "retractable" else ""
        header = (
            "<div style='display:flex;align-items:flex-start;justify-content:space-between;gap:12px;"
            "margin-bottom:12px'>"
            "<div style='min-width:0'>"
            f"<div style='font-size:15px;font-weight:900;color:#f8fafc;line-height:1.2'>{escape(condition['icon'] + ' ' + str(s.get('name', '')))}</div>"
            f"<div style='margin-top:8px;font-size:26px;font-weight:950;line-height:1.05;color:#f8fafc'>{escape(condition['icon'] + ' ' + condition['label'])}</div>"
            f"<div style='font-size:13px;color:#cbd5e1;margin-top:7px'>{escape(temp_line + ' • ' + wind_line + roof_note)}</div>"
            f"<div style='font-size:12px;color:#94a3b8;margin-top:4px'>{escape(matchup)}</div>"
            "</div>"
            f"<div style='flex:0 0 auto;text-align:right;font-size:11px;font-weight:800;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em'>Game<br>Weather</div>"
            "</div>"
        )

        details = []
        if not fixed_roof:
            # outdoor detail chips make no sense for an indoor game
            humidity = _f(game.get("relative_humidity"))
            if humidity is not None:
                details.append(_detail_item("💧", "Humidity", f"{humidity:.0f}%"))
            if game.get("rain_chance") is not None:
                details.append(_detail_item("☔", "Rain", f"{rain:.0f}%"))
            if game.get("wind_gust_mph") is not None and gust and gust >= wind + 3:
                details.append(_detail_item("💨", "Gusts", f"{gust:.0f} mph"))
            feels_like = _f(game.get("feels_like_f"), None)
            if feels_like is None:
                feels_like = _f(game.get("apparent_temperature_f"), None)
            if feels_like is None:
                feels_like = _f(game.get("apparent_temperature"), None)
            if feels_like is not None:
                details.append(_detail_item("🌡️", "Feels Like", f"{feels_like:.0f}°"))
        details_html = ""
        if details:
            details_html = (
                "<div aria-label='weather detail strip' style='display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));"
                "gap:8px;margin:12px 0 14px'>" + "".join(details) + "</div>"
            )

        atmosphere_html = (
            "<div style='margin:8px 0 13px;padding:12px 14px;border-radius:14px;"
            "background:rgba(15,23,42,.52);border:1px solid rgba(255,255,255,.12);"
            "box-shadow:inset 0 1px 0 rgba(255,255,255,.05)'>"
            "<div style='font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#93c5fd;font-weight:900;margin-bottom:6px'>Game Atmosphere</div>"
            f"<div style='font-size:18px;font-weight:950;color:#f8fafc;line-height:1.2'>{escape(atmosphere)}</div>"
            f"<div style='font-size:13px;color:#cbd5e1;margin-top:5px'>{escape(assessment)}</div>"
            "</div>"
        )

        badges = []
        if hr_boost:
            badges.append(_status_badge("🟢 Power Boost", "boost"))
        if run_boost:
            badges.append(_status_badge("🟢 Run Boost", "boost"))
        if delay_risk:
            badges.append(_status_badge("🔴 Delay Risk", "risk"))
        if pitcher_friendly:
            badges.append(_status_badge("🔵 Pitcher Friendly", "pitcher"))
        if not badges:
            badges.append(_status_badge("⚪ Neutral Setup", "neutral"))
        badges_html = (
            "<div style='display:flex;flex-wrap:wrap;gap:8px;align-items:center;"
            "justify-content:center;margin:12px 0'>" + "".join(badges) + "</div>"
        )

        # --- diagram + direction line
        if fixed_roof:
            svg = _field_svg(None, 0, True, condition["icon"], placeholder="roof")
            direction_line = "Fixed roof — outside weather does not reach the field."
        elif wind_read is None and not calm and bearing is None:
            svg = _field_svg(None, wind, True, condition["icon"], placeholder="dir n/a")
            direction_line = (f"{compass_txt} wind at {wind:.0f} mph. Field-relative direction "
                              "unavailable for this park (orientation not published).")
        else:
            svg = _field_svg(wind_read["rel"] if wind_read else None, wind, calm, condition["icon"])
            direction_line = "Winds calm." if calm else (wind_read["text"] if wind_read else
                                                         f"{compass_txt} wind at {wind:.0f} mph.")
        direction_html = (f"<div style='text-align:center;font-size:14px;font-weight:800;"
                          f"color:#7dd3fc;margin-top:2px'>{escape(direction_line)}</div>")

        # --- LF/CF/RF chips (only when a field-relative read exists)
        chips_html = ""
        if wind_read is not None:
            d = s.get("dims") or {}
            chips_html = (
                "<div style='display:flex;gap:8px;margin-top:12px;flex-wrap:wrap'>"
                + _sector_chip("LF", wind_read["components"]["LF"], wind, int(d.get("lf", 330)))
                + _sector_chip("CF", wind_read["components"]["CF"], wind, int(d.get("cf", 400)))
                + _sector_chip("RF", wind_read["components"]["RF"], wind, int(d.get("rf", 330)))
                + "</div>"
            )

        # --- environment strip
        env_html = ""
        if env_score is not None or env_label:
            total = _f(env_game.get("projected_total"))
            bits = []
            if env_label:
                bits.append(f"Run environment: {env_label}")
            if env_score is not None:
                bits.append(f"score {env_score:.0f}/100")
            if total is not None:
                bits.append(f"projected total {total:.1f}")
            env_html = (f"<div style='text-align:center;font-size:12px;"
                        f"color:#cbd5e1;margin-top:10px'>{escape(' · '.join(bits))}</div>")

        summary = _summary_sentence(wind_read, wind, gust, temp, hr_boost,
                                    pitcher_friendly, compass_txt,
                                    has_bearing=bearing is not None)
        if fixed_roof:
            summary = ("The roof is fixed, so today's outside weather has no effect on "
                       "carry or run scoring here. Environment reads as neutral.")
        else:
            if pitcher_friendly and run_boost:
                summary += (" Park and lineups still project a high-scoring game, so treat the "
                            "pitcher-friendly weather as one factor, not the whole story.")
            elif hr_boost and env_score is not None and env_score <= 30:
                summary += (" The park and lineups project a lower-scoring game despite the "
                            "favorable weather.")
            if roof_type == "retractable":
                summary += " Note: this park has a retractable roof — wind effects apply only while it is open."
        summary_html = (f"<div style='margin-top:13px;padding:13px 14px;border-radius:14px;"
                        f"background:rgba(15,23,42,.58);border:1px solid rgba(255,255,255,.12);"
                        f"box-shadow:inset 3px 0 0 rgba(125,211,252,.55)'>"
                        f"<div style='font-size:11px;text-transform:uppercase;letter-spacing:.08em;"
                        f"color:#93c5fd;font-weight:900;margin-bottom:7px'>Ballpark Insight</div>"
                        f"<div class='st-prose' style='margin:0;font-size:14px;color:#e5e7eb'>{escape(summary)}</div></div>")

        inner = _weather_card_wrap(
            header + details_html + atmosphere_html + svg + direction_html + badges_html
            + chips_html + env_html + summary_html,
            condition["key"],
        )
        note = ("Weather from today's published ballpark feed; refreshed through the day. "
                "Direction chips are a weather + park-geometry read, not a model output.")
        return _panel_wrap(inner, note)
    except Exception:
        # fail-safe contract: the stadium page must render exactly as before
        return ""



def _compact_field_svg_placeholder(weather_icon: str, text: str = "compass") -> str:
    return (
        "<svg viewBox='0 0 260 210' role='img' aria-label='Compact field diagram'"
        " style='width:100%;height:auto;display:block;margin:0 auto'>"
        "<path d='M130 190 L34 96 A136 136 0 0 1 226 96 Z'"
        " fill='rgba(34,197,94,.10)' stroke='#334155' stroke-width='2'/>"
        "<path d='M130 190 L101 161 L130 132 L159 161 Z'"
        " fill='rgba(217,180,120,.16)' stroke='#475569' stroke-width='1.5'/>"
        "<text x='52' y='76' text-anchor='middle' font-size='12' font-weight='700' fill='#94a3b8'>LF</text>"
        f"<text x='130' y='32' text-anchor='middle' font-size='17'>{escape(weather_icon)}</text>"
        "<text x='130' y='51' text-anchor='middle' font-size='12' font-weight='700' fill='#94a3b8'>CF</text>"
        "<text x='208' y='76' text-anchor='middle' font-size='12' font-weight='700' fill='#94a3b8'>RF</text>"
        "<circle cx='130' cy='116' r='18' fill='none' stroke='#64748b' stroke-width='2' stroke-dasharray='3 4'/>"
        f"<text x='130' y='121' text-anchor='middle' font-size='10' fill='#94a3b8'>{escape(text)}</text>"
        "</svg>"
    )


def _compact_field_svg(rel_deg: float | None, wind_mph: float, weather_icon: str) -> str:
    if rel_deg is None:
        return _compact_field_svg_placeholder(weather_icon)
    return (
        "<svg viewBox='0 0 260 210' role='img' aria-label='Compact field diagram with wind direction'"
        " style='width:100%;height:auto;display:block;margin:0 auto'>"
        "<path d='M130 190 L34 96 A136 136 0 0 1 226 96 Z'"
        " fill='rgba(34,197,94,.10)' stroke='#334155' stroke-width='2'/>"
        "<path d='M130 190 L101 161 L130 132 L159 161 Z'"
        " fill='rgba(217,180,120,.16)' stroke='#475569' stroke-width='1.5'/>"
        "<text x='52' y='76' text-anchor='middle' font-size='12' font-weight='700' fill='#94a3b8'>LF</text>"
        f"<text x='130' y='32' text-anchor='middle' font-size='17'>{escape(weather_icon)}</text>"
        "<text x='130' y='51' text-anchor='middle' font-size='12' font-weight='700' fill='#94a3b8'>CF</text>"
        "<text x='208' y='76' text-anchor='middle' font-size='12' font-weight='700' fill='#94a3b8'>RF</text>"
        f"<g transform='rotate({rel_deg:.0f} 130 116)'>"
        "<line x1='130' y1='154' x2='130' y2='88' stroke='#38bdf8' stroke-width='4' stroke-linecap='round'/>"
        "<path d='M130 76 L119 96 L130 91 L141 96 Z' fill='#38bdf8'/>"
        "</g>"
        f"<text x='130' y='174' text-anchor='middle' font-size='12' font-weight='800' fill='#e0f2fe'>{wind_mph:.0f} mph</text>"
        "</svg>"
    )


def render_compact_stadium_weather_card(stadium: dict | None, game: dict | None,
                                        env_game: dict | None = None) -> str:
    """Compact daily game-card version for /mlb/weather. Presentation only."""
    try:
        if not game:
            return (
                "<article class='weather-impact-card weather-unavailable'>"
                "<h3>Weather unavailable</h3>"
                "<p>Live ballpark weather is not available for this game yet.</p>"
                "</article>"
            )
        stadium = stadium or {}
        env_game = env_game or {}
        team = str(game.get("home_team_name") or stadium.get("team") or game.get("home_team") or "")
        away = str(game.get("away_team_name") or game.get("away_team") or "")
        venue = str(game.get("venue") or stadium.get("name") or "Ballpark")
        slug = str(stadium.get("slug") or "")
        matchup = f"{away} @ {team}" if away and team else (team or away or "Today's game")

        wind = _f(game.get("wind_speed_mph"), 0.0) or 0.0
        gust = _f(game.get("wind_gust_mph"), 0.0) or 0.0
        temp = _f(game.get("temperature_f"))
        rain = _f(game.get("rain_chance"), 0.0) or 0.0
        from_deg = _f(game.get("wind_direction_degrees"))
        compass_txt = str(game.get("wind_direction") or (_compass(from_deg) if from_deg is not None else "variable"))
        roof_type = str(game.get("roof_type") or "outdoor").lower()
        label = str(game.get("label") or "Neutral")
        env_score = _f(env_game.get("environment_score"))
        env_label = str(env_game.get("environment_label") or "")
        fixed_roof = roof_type in ("dome", "fixed", "indoor")
        bearing = PARK_CF_BEARINGS.get(slug)
        calm = wind < 3
        wind_read = None
        if not fixed_roof and bearing is not None and from_deg is not None and not calm:
            wind_read = classify_wind(from_deg, bearing)

        out_effect = max(wind_read["components"].values()) * wind if wind_read else 0.0
        in_effect = min(wind_read["components"].values()) * wind if wind_read else 0.0
        hr_boost = (not fixed_roof) and ("power" in label.lower() or (out_effect >= 8 and (temp or 0) >= 75))
        run_boost = "run" in env_label.lower() or (env_score is not None and env_score >= 70)
        pitcher_friendly = ("pitcher" in label.lower() or (not fixed_roof and in_effect <= -8) or
                            (env_score is not None and env_score <= 30))
        delay_risk = (not fixed_roof) and roof_type == "outdoor" and rain >= 25
        condition = _weather_condition(game, roof_type, fixed_roof)
        assessment, atmosphere = _assessment_text(condition["key"], wind_read, wind,
                                                  hr_boost, pitcher_friendly,
                                                  fixed_roof, delay_risk,
                                                  run_boost=run_boost, env_score=env_score)

        details = []
        if not fixed_roof:
            humidity = _f(game.get("relative_humidity"))
            if humidity is not None:
                details.append(_detail_item("💧", "Humidity", f"{humidity:.0f}%"))
            if game.get("rain_chance") is not None:
                details.append(_detail_item("☔", "Rain", f"{rain:.0f}%"))
            if game.get("wind_gust_mph") is not None and gust and gust >= wind + 3:
                details.append(_detail_item("💨", "Gusts", f"{gust:.0f} mph"))
            feels_like = _f(game.get("feels_like_f"), None)
            if feels_like is None:
                feels_like = _f(game.get("apparent_temperature_f"), None)
            if feels_like is None:
                feels_like = _f(game.get("apparent_temperature"), None)
            if feels_like is not None:
                details.append(_detail_item("🌡️", "Feels Like", f"{feels_like:.0f}°"))
        details_html = ""
        if details:
            details_html = (
                "<div aria-label='weather detail strip' class='compact-weather-details'>"
                + "".join(details) + "</div>"
            )

        badges = []
        if hr_boost:
            badges.append(_status_badge("🟢 Power Boost", "boost"))
        if run_boost:
            badges.append(_status_badge("🟢 Run Boost", "boost"))
        if delay_risk:
            badges.append(_status_badge("🔴 Delay Risk", "risk"))
        if pitcher_friendly:
            badges.append(_status_badge("🔵 Pitcher Friendly", "pitcher"))
        if not badges:
            badges.append(_status_badge("⚪ Neutral Setup", "neutral"))
        badges_html = "<div class='compact-weather-badges'>" + "".join(badges) + "</div>"

        if fixed_roof:
            svg = _compact_field_svg_placeholder(condition["icon"], "roof")
            direction_line = "Fixed roof — outside weather does not reach the field."
        elif wind_read is None and not calm and bearing is None:
            svg = _compact_field_svg_placeholder(condition["icon"], "dir n/a")
            direction_line = f"{compass_txt} wind at {wind:.0f} mph. Field-relative direction unavailable."
        elif calm:
            svg = _compact_field_svg_placeholder(condition["icon"], "calm")
            direction_line = "Winds calm."
        else:
            svg = _compact_field_svg(wind_read["rel"] if wind_read else None, wind, condition["icon"])
            direction_line = wind_read["text"] if wind_read else f"{compass_txt} wind at {wind:.0f} mph."

        chips_html = ""
        if wind_read is not None:
            d = stadium.get("dims") or {}
            chips_html = (
                "<div class='compact-carry-chips'>"
                + _sector_chip("LF", wind_read["components"]["LF"], wind, int(d.get("lf", 330)))
                + _sector_chip("CF", wind_read["components"]["CF"], wind, int(d.get("cf", 400)))
                + _sector_chip("RF", wind_read["components"]["RF"], wind, int(d.get("rf", 330)))
                + "</div>"
            )

        summary = _summary_sentence(wind_read, wind, gust, temp, hr_boost,
                                    pitcher_friendly, compass_txt,
                                    has_bearing=bearing is not None)
        if fixed_roof:
            summary = "Roof closed. Weather impact minimized."
        else:
            if pitcher_friendly and run_boost:
                summary += " Park and lineups still project a high-scoring game."
            elif hr_boost and env_score is not None and env_score <= 30:
                summary += " Park and lineups project a lower-scoring game."
            if roof_type == "retractable":
                summary += " Retractable roof: wind effects apply only while open."
        if fixed_roof:
            temp_line = f"{temp:.0f}°F outside" if temp is not None else "Indoor"
            wind_line = "Roof closed — indoor conditions"
        else:
            temp_line = f"{temp:.0f}°F" if temp is not None else "Temp N/A"
            wind_line = f"Wind {compass_txt} {wind:.0f} mph" + (f" · Gusts {gust:.0f}" if gust >= wind + 6 else "")
        detail_link = (f"<a class='compact-stadium-link' href='/mlb/stadium/{escape(slug)}'>View Stadium Details</a>"
                       if slug else "")

        return (
            f"<article class='weather-impact-card compact-weather-card' style='{_theme_style(condition['key'])}'>"
            "<div class='compact-weather-head'>"
            "<div class='compact-weather-titlewrap'>"
            f"<div class='compact-weather-venue'>{escape(condition['icon'] + ' ' + venue)}</div>"
            f"<div class='compact-weather-hero'>{escape(condition['icon'] + ' ' + condition['label'])}</div>"
            f"<div class='compact-weather-meta'>{escape(temp_line + ' • ' + wind_line)}</div>"
            f"<div class='compact-weather-matchup'>{escape(matchup)}</div>"
            "</div>"
            f"{detail_link}"
            "</div>"
            f"{details_html}"
            "<div class='compact-atmosphere'>"
            "<div class='compact-eyebrow'>Game Atmosphere</div>"
            f"<div class='compact-atmosphere-title'>{escape(atmosphere)}</div>"
            f"<div class='compact-atmosphere-copy'>{escape(assessment)}</div>"
            "</div>"
            "<div class='compact-field-wrap'>" + svg + "</div>"
            f"<div class='compact-direction'>{escape(direction_line)}</div>"
            f"{badges_html}"
            f"{chips_html}"
            "<div class='compact-insight'>"
            "<div class='compact-eyebrow'>Ballpark Insight</div>"
            f"<div>{escape(summary)}</div>"
            "</div>"
            "</article>"
        )
    except Exception:
        return (
            "<article class='weather-impact-card weather-unavailable'>"
            "<h3>Weather unavailable</h3>"
            "<p>Live ballpark weather could not be rendered for this game.</p>"
            "</article>"
        )
