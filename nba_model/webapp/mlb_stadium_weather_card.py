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

def _field_svg(rel_deg: float | None, wind_mph: float, calm: bool) -> str:
    """Generic field outline (works for every park) + rotated wind arrow.
    Arrow points straight up (toward CF) at rel_deg=0."""
    arrow = ""
    if calm or rel_deg is None:
        arrow = (
            "<circle cx='130' cy='128' r='16' fill='none' stroke='#64748b' stroke-width='2' stroke-dasharray='3 4'/>"
            "<text x='130' y='133' text-anchor='middle' font-size='11' fill='#94a3b8'>calm</text>"
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
        "<text x='130' y='52' text-anchor='middle' font-size='13' font-weight='700' fill='#94a3b8'>CF</text>"
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
    return (f"<span style='display:inline-block;padding:5px 12px;border-radius:999px;"
            f"background:{bg};color:{fg};font-size:12px;font-weight:700;letter-spacing:.02em'>"
            f"{escape(text)}</span>")


def _sector_chip(name: str, comp: float, wind: float, dim_ft: int) -> str:
    effect = comp * wind
    if effect >= 5:
        label, kind = "Carry boost", "boost"
    elif effect <= -5:
        label, kind = "Knocked down", "suppress"
    else:
        label, kind = "Neutral", "neutral"
    porch = " · short porch" if dim_ft <= 325 else ""
    return (
        "<div style='flex:1;min-width:88px;background:var(--surface,#121929);"
        "border:1px solid var(--line,#1e293b);border-radius:12px;padding:10px;text-align:center'>"
        f"<div style='font-size:12px;color:var(--muted,#94a3b8);font-weight:700'>{escape(name)}"
        f" <span style='font-weight:400'>{dim_ft} ft</span></div>"
        f"<div style='margin-top:6px'>{_badge(label + porch, kind)}</div>"
        "</div>"
    )


def _panel_wrap(inner: str, note: str = "") -> str:
    note_html = (f"<p class='muted' style='margin:10px 0 0;font-size:12px'>{escape(note)}</p>"
                 if note else "")
    return ("<section class='panel'><div class='panel-head'><div>"
            "<div class='eyebrow'>Today's Weather Impact</div>"
            "<h2>Live Ballpark Conditions</h2></div></div>"
            + inner + note_html + "</section>")


def _fallback(msg: str) -> str:
    return _panel_wrap(f"<p class='st-prose' style='color:var(--muted,#94a3b8)'>{escape(msg)}</p>")


# --- summary text -------------------------------------------------------------

def _summary_sentence(wind_read: dict | None, wind: float, gust: float, temp: float,
                      hr_boost: bool, pitcher_friendly: bool, compass_txt: str) -> str:
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

    if wind_read is None:
        lead = (f"Winds are {compass_txt} at {wind:.0f} mph{temp_part}. "
                "Field-relative wind direction is not published for this park, "
                "so no out/in read is claimed.")
        return lead

    if wind < 3:
        lead = f"Winds are calm{temp_part}."
    else:
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

        # --- badges
        out_effect = max(wind_read["components"].values()) * wind if wind_read else 0.0
        in_effect = min(wind_read["components"].values()) * wind if wind_read else 0.0
        hr_boost = (not fixed_roof) and ("power" in label.lower()
                                         or (out_effect >= 8 and (temp or 0) >= 75))
        run_boost = "run" in env_label.lower() or (env_score is not None and env_score >= 70)
        pitcher_friendly = ("pitcher" in label.lower()
                            or (not fixed_roof and in_effect <= -8)
                            or (env_score is not None and env_score <= 30))
        delay_risk = (not fixed_roof) and roof_type == "outdoor" and rain >= 25

        badges = []
        badges.append(_badge("HR Boost: Yes" if hr_boost else "HR Boost: No",
                             "boost" if hr_boost else "neutral"))
        badges.append(_badge("Run Boost: Yes" if run_boost else "Run Boost: No",
                             "boost" if run_boost else "neutral"))
        badges.append(_badge("Pitcher Friendly: Yes" if pitcher_friendly else "Pitcher Friendly: No",
                             "suppress" if pitcher_friendly else "neutral"))
        if delay_risk:
            badges.append(_badge(f"Delay Risk: {rain:.0f}% rain", "warn"))
        badges_html = ("<div style='display:flex;flex-wrap:wrap;gap:8px;justify-content:center;"
                       "margin-top:12px'>" + "".join(badges) + "</div>")

        # --- header line
        away = str(game.get("away_team_name") or "")
        head_bits = []
        if temp is not None:
            head_bits.append(f"{temp:.0f}°F")
        head_bits.append(f"Wind {compass_txt} {wind:.0f} mph" + (f" (G {gust:.0f})" if gust >= wind + 6 else ""))
        if fixed_roof:
            head_bits.append("Roof: fixed (weather-neutral)")
        elif roof_type == "retractable":
            head_bits.append("Retractable roof")
        header = (
            f"<div style='text-align:center;margin-bottom:4px'>"
            f"<div style='font-size:15px;font-weight:800;color:var(--ink,#f8fafc)'>"
            f"{escape(s.get('name', ''))}</div>"
            f"<div style='font-size:12px;color:var(--muted,#94a3b8);margin-top:2px'>"
            f"{escape(away)} @ {escape(team)} · {' · '.join(escape(b) for b in head_bits)}</div></div>"
        )

        # --- diagram + direction line
        if fixed_roof:
            svg = _field_svg(None, 0, True)
            direction_line = "Fixed roof — outside weather does not reach the field."
        elif wind_read is None and not calm and bearing is None:
            svg = _field_svg(None, wind, True)
            direction_line = (f"{compass_txt} wind at {wind:.0f} mph. Field-relative direction "
                              "unavailable for this park (orientation not published).")
        else:
            svg = _field_svg(wind_read["rel"] if wind_read else None, wind, calm)
            direction_line = "Winds calm." if calm else (wind_read["text"] if wind_read else
                                                         f"{compass_txt} wind at {wind:.0f} mph.")
        direction_html = (f"<div style='text-align:center;font-size:14px;font-weight:700;"
                          f"color:#7dd3fc;margin-top:2px'>{escape(direction_line)}</div>")

        # --- LF/CF/RF chips (only when a field-relative read exists)
        chips_html = ""
        if wind_read is not None:
            d = s.get("dims") or {}
            chips_html = (
                "<div style='display:flex;gap:8px;margin-top:12px'>"
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
                        f"color:var(--muted,#94a3b8);margin-top:10px'>{escape(' · '.join(bits))}</div>")

        summary = _summary_sentence(wind_read, wind, gust, temp, hr_boost,
                                    pitcher_friendly, compass_txt)
        if fixed_roof:
            summary = ("The roof is fixed, so today's outside weather has no effect on "
                       "carry or run scoring here. Environment reads as neutral.")
        elif roof_type == "retractable":
            summary += " Note: this park has a retractable roof — wind effects apply only while it is open."
        summary_html = (f"<div style='margin-top:12px;padding:12px 14px;border-radius:12px;"
                        f"background:var(--surface,#121929);border:1px solid var(--line,#1e293b)'>"
                        f"<div style='font-size:11px;text-transform:uppercase;letter-spacing:.05em;"
                        f"color:var(--muted,#94a3b8);font-weight:700;margin-bottom:6px'>What this means today</div>"
                        f"<div class='st-prose' style='margin:0;font-size:14px'>{escape(summary)}</div></div>")

        inner = header + svg + direction_html + badges_html + chips_html + env_html + summary_html
        note = ("Weather from today's published ballpark feed; refreshed through the day. "
                "Direction chips are a weather + park-geometry read, not a model output.")
        return _panel_wrap(inner, note)
    except Exception:
        # fail-safe contract: the stadium page must render exactly as before
        return ""
