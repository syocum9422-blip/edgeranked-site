"""MLB Stadium Intelligence — 30 evergreen, SEO-indexable ballpark pages.

Read-only. This module ships a curated, static reference dataset of the 30
active MLB ballparks (names, locations, opened year, surface, capacity,
elevation, roof, official outfield dimensions). It never runs or imports any
model, simulation, calibration, grading, or prediction code.

Routes:
  * ``/mlb/stadiums``                — master index (AL / NL directory)
  * ``/mlb/stadium/<stadium_slug>``  — one permanent page per ballpark

The "EdgeRanked Park Intelligence" 0-100 scores (Section 3) are computed by
:func:`park_intelligence`, a pure deterministic function of the published
geometry/elevation/roof attributes below. The methodology is documented in that
function's comments; the formula is intentionally not surfaced on the page.

Empirical park *factors* (Section 4: HR/Run/Singles/Doubles/Triples factors)
are NOT part of EdgeRanked's published dataset, so they render as
"Unavailable" rather than being fabricated.

Data sources (authoritative public references): MLB.com official ballpark
information pages, official team ballpark/media guides, and Baseball
Reference / Ballparks of Baseball reference tables for posted outfield
dimensions, capacity, elevation, opened year, surface, and roof type.
"""

from __future__ import annotations

import json
import re
import unicodedata
from html import escape

from flask import abort


def _team_page_slug(team_name: str) -> str:
    # Same slug scheme as mlb_teams.TEAMS (slugified full team name); computed
    # locally because mlb_teams imports this module.
    text = unicodedata.normalize("NFKD", str(team_name or "").strip())
    ascii_text = text.encode("ascii", "ignore").decode("ascii").lower().replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")

# --- Stadium dataset --------------------------------------------------------
# Fields per record:
#   name, team, team_slug, slug, city, state, league (AL/NL), division,
#   opened, surface, capacity, elevation (ft), roof, tz (display label),
#   dims = {lf, lc, cf, rc, rf} (feet, posted official markers),
#   wind_exposure (0 low .. 3 very high; factual reputation used only for the
#                  Weather Sensitivity score), features (well-known factual
#                  signature characteristics).

STADIUMS = [
    # ---------------- AL East ----------------
    {"name": "Yankee Stadium", "team": "New York Yankees", "team_slug": "yankees",
     "slug": "yankee-stadium", "city": "Bronx", "state": "New York", "league": "AL",
     "division": "AL East", "opened": 2009, "surface": "Grass", "capacity": 46537,
     "elevation": 55, "roof": "Open air", "tz": "Eastern (ET)",
     "dims": {"lf": 318, "lc": 399, "cf": 408, "rc": 385, "rf": 314}, "wind_exposure": 2,
     "features": ["Short right-field porch", "Asymmetrical outfield"]},
    {"name": "Fenway Park", "team": "Boston Red Sox", "team_slug": "red-sox",
     "slug": "fenway-park", "city": "Boston", "state": "Massachusetts", "league": "AL",
     "division": "AL East", "opened": 1912, "surface": "Grass", "capacity": 37755,
     "elevation": 20, "roof": "Open air", "tz": "Eastern (ET)",
     "dims": {"lf": 310, "lc": 379, "cf": 390, "rc": 380, "rf": 302}, "wind_exposure": 2,
     "features": ["The Green Monster (37-ft left-field wall)", "Pesky's Pole", "Deep center-field triangle"]},
    {"name": "Rogers Centre", "team": "Toronto Blue Jays", "team_slug": "blue-jays",
     "slug": "rogers-centre", "city": "Toronto", "state": "Ontario", "league": "AL",
     "division": "AL East", "opened": 1989, "surface": "Artificial turf", "capacity": 41500,
     "elevation": 266, "roof": "Retractable", "tz": "Eastern (ET)",
     "dims": {"lf": 328, "lc": 375, "cf": 400, "rc": 375, "rf": 328}, "wind_exposure": 1,
     "features": ["Fully retractable roof", "Symmetrical dimensions"]},
    {"name": "Tropicana Field", "team": "Tampa Bay Rays", "team_slug": "rays",
     "slug": "tropicana-field", "city": "St. Petersburg", "state": "Florida", "league": "AL",
     "division": "AL East", "opened": 1990, "surface": "Artificial turf", "capacity": 25000,
     "elevation": 15, "roof": "Fixed dome", "tz": "Eastern (ET)",
     "dims": {"lf": 315, "lc": 370, "cf": 404, "rc": 370, "rf": 322}, "wind_exposure": 0,
     "features": ["Fixed dome", "Catwalk ground rules", "Climate-controlled"]},
    {"name": "Oriole Park at Camden Yards", "team": "Baltimore Orioles", "team_slug": "orioles",
     "slug": "oriole-park-at-camden-yards", "city": "Baltimore", "state": "Maryland", "league": "AL",
     "division": "AL East", "opened": 1992, "surface": "Grass", "capacity": 45971,
     "elevation": 50, "roof": "Open air", "tz": "Eastern (ET)",
     "dims": {"lf": 333, "lc": 384, "cf": 410, "rc": 373, "rf": 318}, "wind_exposure": 1,
     "features": ["Deepened left field (2022)", "Warehouse beyond right field", "Asymmetrical outfield"]},
    # ---------------- AL Central ----------------
    {"name": "Progressive Field", "team": "Cleveland Guardians", "team_slug": "guardians",
     "slug": "progressive-field", "city": "Cleveland", "state": "Ohio", "league": "AL",
     "division": "AL Central", "opened": 1994, "surface": "Grass", "capacity": 34830,
     "elevation": 660, "roof": "Open air", "tz": "Eastern (ET)",
     "dims": {"lf": 325, "lc": 370, "cf": 405, "rc": 375, "rf": 325}, "wind_exposure": 2,
     "features": ["19-ft left-field wall", "Lakefront wind"]},
    {"name": "Target Field", "team": "Minnesota Twins", "team_slug": "twins",
     "slug": "target-field", "city": "Minneapolis", "state": "Minnesota", "league": "AL",
     "division": "AL Central", "opened": 2010, "surface": "Grass", "capacity": 38544,
     "elevation": 815, "roof": "Open air", "tz": "Central (CT)",
     "dims": {"lf": 339, "lc": 377, "cf": 404, "rc": 367, "rf": 328}, "wind_exposure": 2,
     "features": ["Cold-weather spring climate", "Limestone backdrop"]},
    {"name": "Rate Field", "team": "Chicago White Sox", "team_slug": "white-sox",
     "slug": "rate-field", "city": "Chicago", "state": "Illinois", "league": "AL",
     "division": "AL Central", "opened": 1991, "surface": "Grass", "capacity": 40615,
     "elevation": 595, "roof": "Open air", "tz": "Central (CT)",
     "dims": {"lf": 330, "lc": 377, "cf": 400, "rc": 372, "rf": 335}, "wind_exposure": 2,
     "features": ["Symmetrical fences", "Open concourse wind"]},
    {"name": "Comerica Park", "team": "Detroit Tigers", "team_slug": "tigers",
     "slug": "comerica-park", "city": "Detroit", "state": "Michigan", "league": "AL",
     "division": "AL Central", "opened": 2000, "surface": "Grass", "capacity": 41083,
     "elevation": 600, "roof": "Open air", "tz": "Eastern (ET)",
     "dims": {"lf": 345, "lc": 370, "cf": 412, "rc": 365, "rf": 330}, "wind_exposure": 1,
     "features": ["Very deep center field", "Spacious power alleys", "Large foul territory"]},
    {"name": "Kauffman Stadium", "team": "Kansas City Royals", "team_slug": "royals",
     "slug": "kauffman-stadium", "city": "Kansas City", "state": "Missouri", "league": "AL",
     "division": "AL Central", "opened": 1973, "surface": "Grass", "capacity": 37903,
     "elevation": 750, "roof": "Open air", "tz": "Central (CT)",
     "dims": {"lf": 330, "lc": 387, "cf": 410, "rc": 387, "rf": 330}, "wind_exposure": 1,
     "features": ["Deep symmetrical gaps", "Fountains beyond outfield", "Spacious outfield"]},
    # ---------------- AL West ----------------
    {"name": "Daikin Park", "team": "Houston Astros", "team_slug": "astros",
     "slug": "daikin-park", "city": "Houston", "state": "Texas", "league": "AL",
     "division": "AL West", "opened": 2000, "surface": "Grass", "capacity": 41168,
     "elevation": 50, "roof": "Retractable", "tz": "Central (CT)",
     "dims": {"lf": 315, "lc": 366, "cf": 409, "rc": 373, "rf": 326}, "wind_exposure": 1,
     "features": ["Crawford Boxes (short left field)", "Deep center field", "Retractable roof"]},
    {"name": "T-Mobile Park", "team": "Seattle Mariners", "team_slug": "mariners",
     "slug": "t-mobile-park", "city": "Seattle", "state": "Washington", "league": "AL",
     "division": "AL West", "opened": 1999, "surface": "Grass", "capacity": 47929,
     "elevation": 10, "roof": "Retractable", "tz": "Pacific (PT)",
     "dims": {"lf": 331, "lc": 378, "cf": 401, "rc": 381, "rf": 326}, "wind_exposure": 2,
     "features": ["Marine air", "Pitcher-friendly reputation", "Retractable roof (umbrella)"]},
    {"name": "Globe Life Field", "team": "Texas Rangers", "team_slug": "rangers",
     "slug": "globe-life-field", "city": "Arlington", "state": "Texas", "league": "AL",
     "division": "AL West", "opened": 2020, "surface": "Artificial turf", "capacity": 40300,
     "elevation": 545, "roof": "Retractable", "tz": "Central (CT)",
     "dims": {"lf": 329, "lc": 372, "cf": 407, "rc": 374, "rf": 326}, "wind_exposure": 0,
     "features": ["Retractable roof", "Climate-controlled in summer heat"]},
    {"name": "Angel Stadium", "team": "Los Angeles Angels", "team_slug": "angels",
     "slug": "angel-stadium", "city": "Anaheim", "state": "California", "league": "AL",
     "division": "AL West", "opened": 1966, "surface": "Grass", "capacity": 45517,
     "elevation": 160, "roof": "Open air", "tz": "Pacific (PT)",
     "dims": {"lf": 330, "lc": 387, "cf": 400, "rc": 370, "rf": 330}, "wind_exposure": 1,
     "features": ["Symmetrical outfield", "Mild, dry evening air"]},
    {"name": "Sutter Health Park", "team": "Athletics", "team_slug": "athletics",
     "slug": "sutter-health-park", "city": "West Sacramento", "state": "California", "league": "AL",
     "division": "AL West", "opened": 2000, "surface": "Grass", "capacity": 14014,
     "elevation": 25, "roof": "Open air", "tz": "Pacific (PT)",
     "dims": {"lf": 330, "lc": 375, "cf": 403, "rc": 375, "rf": 325}, "wind_exposure": 2,
     "features": ["Temporary Athletics home", "Intimate minor-league-scale park", "Hot inland summers"]},
    # ---------------- NL East ----------------
    {"name": "Truist Park", "team": "Atlanta Braves", "team_slug": "braves",
     "slug": "truist-park", "city": "Atlanta", "state": "Georgia", "league": "NL",
     "division": "NL East", "opened": 2017, "surface": "Grass", "capacity": 41084,
     "elevation": 1050, "roof": "Open air", "tz": "Eastern (ET)",
     "dims": {"lf": 335, "lc": 385, "cf": 400, "rc": 375, "rf": 325}, "wind_exposure": 1,
     "features": ["Warm, humid summers", "Moderate elevation"]},
    {"name": "Citi Field", "team": "New York Mets", "team_slug": "mets",
     "slug": "citi-field", "city": "Queens", "state": "New York", "league": "NL",
     "division": "NL East", "opened": 2009, "surface": "Grass", "capacity": 41922,
     "elevation": 20, "roof": "Open air", "tz": "Eastern (ET)",
     "dims": {"lf": 335, "lc": 370, "cf": 408, "rc": 375, "rf": 330}, "wind_exposure": 2,
     "features": ["Deep center field", "Reconfigured fences (2012)", "Bay breezes"]},
    {"name": "Citizens Bank Park", "team": "Philadelphia Phillies", "team_slug": "phillies",
     "slug": "citizens-bank-park", "city": "Philadelphia", "state": "Pennsylvania", "league": "NL",
     "division": "NL East", "opened": 2004, "surface": "Grass", "capacity": 42792,
     "elevation": 40, "roof": "Open air", "tz": "Eastern (ET)",
     "dims": {"lf": 329, "lc": 374, "cf": 401, "rc": 369, "rf": 330}, "wind_exposure": 2,
     "features": ["Hitter-friendly reputation", "Compact power alleys"]},
    {"name": "Nationals Park", "team": "Washington Nationals", "team_slug": "nationals",
     "slug": "nationals-park", "city": "Washington", "state": "D.C.", "league": "NL",
     "division": "NL East", "opened": 2008, "surface": "Grass", "capacity": 41339,
     "elevation": 25, "roof": "Open air", "tz": "Eastern (ET)",
     "dims": {"lf": 336, "lc": 377, "cf": 402, "rc": 370, "rf": 335}, "wind_exposure": 1,
     "features": ["Balanced dimensions", "Humid summer air"]},
    {"name": "loanDepot Park", "team": "Miami Marlins", "team_slug": "marlins",
     "slug": "loandepot-park", "city": "Miami", "state": "Florida", "league": "NL",
     "division": "NL East", "opened": 2012, "surface": "Grass", "capacity": 37446,
     "elevation": 10, "roof": "Retractable", "tz": "Eastern (ET)",
     "dims": {"lf": 344, "lc": 386, "cf": 400, "rc": 387, "rf": 335}, "wind_exposure": 0,
     "features": ["Retractable roof (usually closed)", "Climate-controlled", "Pitcher-friendly"]},
    # ---------------- NL Central ----------------
    {"name": "Wrigley Field", "team": "Chicago Cubs", "team_slug": "cubs",
     "slug": "wrigley-field", "city": "Chicago", "state": "Illinois", "league": "NL",
     "division": "NL Central", "opened": 1914, "surface": "Grass", "capacity": 41649,
     "elevation": 600, "roof": "Open air", "tz": "Central (CT)",
     "dims": {"lf": 355, "lc": 368, "cf": 400, "rc": 368, "rf": 353}, "wind_exposure": 3,
     "features": ["Wind off Lake Michigan", "Ivy-covered brick walls", "Wind-dependent run scoring"]},
    {"name": "American Family Field", "team": "Milwaukee Brewers", "team_slug": "brewers",
     "slug": "american-family-field", "city": "Milwaukee", "state": "Wisconsin", "league": "NL",
     "division": "NL Central", "opened": 2001, "surface": "Grass", "capacity": 41700,
     "elevation": 635, "roof": "Retractable", "tz": "Central (CT)",
     "dims": {"lf": 342, "lc": 370, "cf": 400, "rc": 370, "rf": 345}, "wind_exposure": 1,
     "features": ["Fan-shaped retractable roof", "Hitter-friendly when open"]},
    {"name": "Busch Stadium", "team": "St. Louis Cardinals", "team_slug": "cardinals",
     "slug": "busch-stadium", "city": "St. Louis", "state": "Missouri", "league": "NL",
     "division": "NL Central", "opened": 2006, "surface": "Grass", "capacity": 44494,
     "elevation": 465, "roof": "Open air", "tz": "Central (CT)",
     "dims": {"lf": 336, "lc": 375, "cf": 400, "rc": 375, "rf": 335}, "wind_exposure": 1,
     "features": ["Balanced dimensions", "Hot, humid summers"]},
    {"name": "Great American Ball Park", "team": "Cincinnati Reds", "team_slug": "reds",
     "slug": "great-american-ball-park", "city": "Cincinnati", "state": "Ohio", "league": "NL",
     "division": "NL Central", "opened": 2003, "surface": "Grass", "capacity": 42319,
     "elevation": 490, "roof": "Open air", "tz": "Eastern (ET)",
     "dims": {"lf": 328, "lc": 379, "cf": 404, "rc": 370, "rf": 325}, "wind_exposure": 2,
     "features": ["Strong home-run park", "Short corners", "River breezes"]},
    {"name": "PNC Park", "team": "Pittsburgh Pirates", "team_slug": "pirates",
     "slug": "pnc-park", "city": "Pittsburgh", "state": "Pennsylvania", "league": "NL",
     "division": "NL Central", "opened": 2001, "surface": "Grass", "capacity": 38747,
     "elevation": 730, "roof": "Open air", "tz": "Eastern (ET)",
     "dims": {"lf": 325, "lc": 383, "cf": 399, "rc": 375, "rf": 320}, "wind_exposure": 1,
     "features": ["Riverfront setting", "21-ft right-field Clemente Wall", "Pitcher-friendly"]},
    # ---------------- NL West ----------------
    {"name": "Dodger Stadium", "team": "Los Angeles Dodgers", "team_slug": "dodgers",
     "slug": "dodger-stadium", "city": "Los Angeles", "state": "California", "league": "NL",
     "division": "NL West", "opened": 1962, "surface": "Grass", "capacity": 56000,
     "elevation": 510, "roof": "Open air", "tz": "Pacific (PT)",
     "dims": {"lf": 330, "lc": 385, "cf": 395, "rc": 385, "rf": 330}, "wind_exposure": 1,
     "features": ["Dry evening air", "Symmetrical outfield", "Large foul territory"]},
    {"name": "Oracle Park", "team": "San Francisco Giants", "team_slug": "giants",
     "slug": "oracle-park", "city": "San Francisco", "state": "California", "league": "NL",
     "division": "NL West", "opened": 2000, "surface": "Grass", "capacity": 41265,
     "elevation": 10, "roof": "Open air", "tz": "Pacific (PT)",
     "dims": {"lf": 339, "lc": 364, "cf": 399, "rc": 421, "rf": 309}, "wind_exposure": 3,
     "features": ["Triples Alley (deep right-center, 421 ft)", "McCovey Cove beyond right field",
                  "Marine layer and bay wind", "Strong pitcher's park"]},
    {"name": "Petco Park", "team": "San Diego Padres", "team_slug": "padres",
     "slug": "petco-park", "city": "San Diego", "state": "California", "league": "NL",
     "division": "NL West", "opened": 2004, "surface": "Grass", "capacity": 40209,
     "elevation": 60, "roof": "Open air", "tz": "Pacific (PT)",
     "dims": {"lf": 336, "lc": 357, "cf": 396, "rc": 387, "rf": 322}, "wind_exposure": 2,
     "features": ["Marine layer suppresses fly balls", "Pitcher-friendly", "Heavy night air"]},
    {"name": "Coors Field", "team": "Colorado Rockies", "team_slug": "rockies",
     "slug": "coors-field", "city": "Denver", "state": "Colorado", "league": "NL",
     "division": "NL West", "opened": 1995, "surface": "Grass", "capacity": 50144,
     "elevation": 5200, "roof": "Open air", "tz": "Mountain (MT)",
     "dims": {"lf": 347, "lc": 390, "cf": 415, "rc": 375, "rf": 350}, "wind_exposure": 2,
     "features": ["Extreme altitude (~5,200 ft)", "Thin air reduces breaking-ball movement",
                  "Largest outfield in MLB", "Humidor-stored baseballs"]},
    {"name": "Chase Field", "team": "Arizona Diamondbacks", "team_slug": "diamondbacks",
     "slug": "chase-field", "city": "Phoenix", "state": "Arizona", "league": "NL",
     "division": "NL West", "opened": 1998, "surface": "Artificial turf", "capacity": 48686,
     "elevation": 1100, "roof": "Retractable", "tz": "Mountain (MST, no DST)",
     "dims": {"lf": 330, "lc": 374, "cf": 407, "rc": 374, "rf": 334}, "wind_exposure": 0,
     "features": ["Retractable roof with A/C", "Dry desert air boosts carry when open",
                  "Humidor-stored baseballs"]},
]

BY_SLUG = {s["slug"]: s for s in STADIUMS}
SLUG_RE = re.compile(r"^[a-z0-9-]+$")


# --- proprietary park-intelligence scoring (deterministic) ------------------

def _clamp(value: float) -> int:
    return int(round(max(0.0, min(100.0, value))))


def park_intelligence(s: dict) -> dict:
    """Return five 0-100 outlook scores for a ballpark.

    Pure, deterministic function of the published geometry/elevation/roof
    attributes — identical inputs always yield identical outputs. Methodology
    (kept internal; never rendered):

      size_index   = 0.50*corner + 0.30*gap + 0.20*CF   (bigger = more spacious)
      short_porch  = how far the shorter corner sits inside a 335-ft baseline
      altitude     = elevation lift, capped (thin air aids carry & scoring)
      roof_open    = open-air exposure multiplier for weather sensitivity

    Home Run / Run / Extra-Base climb as parks shrink and air thins; Pitcher
    Friendliness is the spacious/thin-air inverse; Weather Sensitivity keys off
    roof type, elevation, and a curated wind-exposure rating.
    """
    d = s["dims"]
    lf, lc, cf, rc, rf = d["lf"], d["lc"], d["cf"], d["rc"], d["rf"]
    corner = (lf + rf) / 2.0
    gap = (lc + rc) / 2.0
    size_index = 0.50 * corner + 0.30 * gap + 0.20 * cf
    short_porch = max(0.0, 335 - min(lf, rf))
    elev = s["elevation"]
    altitude = min(elev / 130.0, 42.0)
    roof = s["roof"].lower()
    is_dome = "dome" in roof
    is_retract = "retract" in roof

    # Home Run Environment
    hr = 50 + (360 - size_index) * 0.85 + altitude + short_porch * 0.7
    if is_dome:
        hr -= 4

    # Run Scoring Environment
    run = 50 + (362 - size_index) * 0.70 + altitude * 0.9 + short_porch * 0.35

    # Pitcher Friendliness (spacious + thin-air-free favors pitchers)
    pitcher = 50 + (size_index - 360) * 0.85 - altitude * 0.9 + (cf - 400) * 0.25

    # Extra-Base Hit Environment (deep gaps / right-center & big CF -> 2B/3B)
    xbh = 50 + (gap - 372) * 0.85 + (cf - 400) * 0.45 + (max(rc, lc) - 380) * 0.55 + altitude * 0.4

    # Weather Sensitivity (exposure to wind/temp/humidity swings)
    if is_dome:
        weather = 12
    elif is_retract:
        weather = 38 + s["wind_exposure"] * 4
    else:
        weather = 58 + s["wind_exposure"] * 9 + min(elev / 900.0, 8)

    return {
        "Home Run Environment": _clamp(hr),
        "Run Scoring Environment": _clamp(run),
        "Pitcher Friendliness": _clamp(pitcher),
        "Extra Base Hit Environment": _clamp(xbh),
        "Weather Sensitivity": _clamp(weather),
    }


def _tier_label(score: int) -> str:
    if score >= 78:
        return "Extreme"
    if score >= 63:
        return "Elevated"
    if score >= 45:
        return "Average"
    if score >= 30:
        return "Suppressed"
    return "Strongly Suppressed"


# --- narrative generation (factual, attribute-driven, unique per park) ------

def _location(s: dict) -> str:
    return f"{s['city']}, {s['state']}"


def overview_paragraph(s: dict) -> str:
    """Section 1 factual summary (200+ words) built from verified attributes."""
    d = s["dims"]
    surface = s["surface"].lower()
    roof = s["roof"].lower()
    roof_clause = {
        "open air": "It is an open-air ballpark fully exposed to local weather.",
        "retractable": "Its retractable roof lets the club open or close the park depending on weather.",
        "fixed dome": "It is a fully enclosed, climate-controlled domed stadium.",
    }.get(roof, f"Its roof configuration is {s['roof'].lower()}.")
    deepest = max(d, key=d.get)
    shortest = min(d, key=d.get)
    field_names = {"lf": "left field", "lc": "left-center", "cf": "center field", "rc": "right-center", "rf": "right field"}
    return (
        f"{s['name']} is the home ballpark of the {s['team']}, located in {_location(s)}. "
        f"The stadium opened in {s['opened']} and seats approximately {s['capacity']:,} fans. "
        f"It sits at an elevation of roughly {s['elevation']:,} feet above sea level and operates in the "
        f"{s['tz']} time zone. The playing surface is {surface}. {roof_clause} "
        f"From a hitter's and pitcher's perspective, the outfield measures {d['lf']} feet down the left-field "
        f"line, {d['lc']} feet to left-center, {d['cf']} feet to straightaway center, {d['rc']} feet to "
        f"right-center, and {d['rf']} feet down the right-field line. "
        f"Its deepest posted distance is {field_names[deepest]} at {d[deepest]} feet, while the most reachable "
        f"corner is {field_names[shortest]} at {d[shortest]} feet. "
        f"As one of the 30 active Major League Baseball ballparks, {s['name']} combines these fixed dimensions, "
        f"its {s['elevation']:,}-foot elevation, and its {s['roof'].lower()} configuration to shape how the ball "
        f"carries, how pitchers attack the zone, and how run scoring plays out across a season. "
        f"The {s['team']} compete in the {s['division']} of the "
        f"{'American' if s['league'] == 'AL' else 'National'} League, and this venue serves as their fixed home "
        f"environment for all home games on the schedule. "
        f"Relative to a typical big-league outfield, the {d['cf']}-foot center-field distance and "
        f"{(d['lf'] + d['rf']) // 2}-foot average corner here place {s['name']} on the "
        f"{'deeper, more spacious' if (0.5 * (d['lf'] + d['rf']) / 2 + 0.3 * (d['lc'] + d['rc']) / 2 + 0.2 * d['cf']) >= 358 else 'more compact, hitter-accessible'} "
        f"end of the league spectrum. "
        f"The reference figures on this page are evergreen stadium facts rather than daily projections, and they "
        f"anchor EdgeRanked's park-adjusted MLB projection, weather, and results coverage for this venue."
    )


def characteristics_paragraph(s: dict) -> str:
    """Section 7 unique ballpark profile (250+ words) from geometry + features."""
    d = s["dims"]
    lf, rf, cf = d["lf"], d["rf"], d["cf"]
    parts = []
    parts.append(
        f"{s['name']} carries a distinct on-field character driven by its geometry, elevation, and exposure to "
        f"the elements. The park stands at about {s['elevation']:,} feet of elevation in {_location(s)}, a factor "
        f"that influences how far well-struck balls travel and how much break pitchers can generate."
    )
    # corner asymmetry / handedness geometry
    diff = lf - rf
    if abs(diff) >= 12:
        if diff > 0:
            parts.append(
                f"The outfield is notably asymmetrical: left field plays {lf} feet while right field is only {rf} "
                f"feet, a {abs(diff)}-foot gap that gives left-handed pull hitters a more inviting target down the "
                f"right-field line."
            )
        else:
            parts.append(
                f"The outfield is notably asymmetrical: right field plays {rf} feet while left field is only {lf} "
                f"feet, a {abs(diff)}-foot gap that rewards right-handed pull hitters down the left-field line."
            )
    else:
        parts.append(
            f"The corners are close to symmetrical ({lf} feet to left, {rf} feet to right), so neither batter "
            f"handedness gains an obvious pull-side advantage from the foul lines."
        )
    # center field depth
    if cf >= 408:
        parts.append(
            f"Center field is deep at {cf} feet, turning many would-be home runs into long outs and rewarding "
            f"hitters who can drive the ball into the gaps for extra bases."
        )
    elif cf <= 396:
        parts.append(
            f"Center field is relatively shallow at {cf} feet, keeping straightaway drives in play as home-run "
            f"threats."
        )
    else:
        parts.append(f"Center field plays a fairly standard {cf} feet.")
    # roof / weather
    roof = s["roof"].lower()
    if "dome" in roof:
        parts.append(
            "Because the stadium is fully enclosed, weather is effectively removed from the equation — there is no "
            "wind, rain, temperature swing, or humidity effect, producing highly consistent conditions year-round."
        )
    elif "retract" in roof:
        parts.append(
            "With a retractable roof, conditions can swing between fully exposed and climate-controlled depending on "
            "whether the roof is open, which can meaningfully change how the ball carries on a given night."
        )
    else:
        parts.append(
            "As an open-air park, conditions here are shaped by wind, temperature, and humidity, so the same swing "
            "can produce different outcomes from a cool, heavy night to a warm, dry afternoon."
        )
    # deterministic run/HR lean from the proprietary ratings
    sc = park_intelligence(s)
    run_lean = ("clearly favors hitters and run scoring" if sc["Run Scoring Environment"] >= 60
                else "clearly favors pitchers and run prevention" if sc["Run Scoring Environment"] <= 42
                else "plays close to neutral for run scoring")
    parts.append(
        f"On EdgeRanked's deterministic park-intelligence scale, {s['name']} {run_lean}, grading {sc['Run Scoring Environment']}"
        f"/100 for run environment and {sc['Home Run Environment']}/100 for home runs. Its extra-base-hit environment "
        f"rates {sc['Extra Base Hit Environment']}/100, reflecting how the gaps and {d['cf']}-foot center field reward "
        f"doubles and triples, while pitcher friendliness sits at {sc['Pitcher Friendliness']}/100."
    )
    # surface implications
    if "turf" in s["surface"].lower():
        parts.append(
            "The artificial-turf surface produces faster, truer ground-ball hops and slightly more balls scooting "
            "through the infield than a natural-grass field."
        )
    else:
        parts.append(
            "The natural-grass surface plays at a conventional infield speed, with hop and reaction times typical of a "
            "grass field."
        )
    # capacity / scale
    parts.append(
        f"With a seating capacity of roughly {s['capacity']:,}, the park's scale and configuration also influence foul "
        f"territory and the overall feel of at-bats for both hitters and pitchers."
    )
    # weather sensitivity + setting close
    parts.append(
        f"Located in {_location(s)} within the {s['tz']} time zone, {s['name']} carries an EdgeRanked weather "
        f"sensitivity rating of {sc['Weather Sensitivity']}/100, a measure of how much day-to-day conditions can move "
        f"its scoring environment relative to other Major League ballparks."
    )
    # signature features
    if s.get("features"):
        feats = "; ".join(s["features"])
        parts.append(f"Signature characteristics include: {feats}.")
    parts.append(
        f"Taken together, these traits make {s['name']} a unique environment within Major League Baseball, and they "
        f"feed directly into EdgeRanked's park-aware projection, weather, and results coverage for {s['team']} games."
    )
    return " ".join(parts)


def handedness_analysis(s: dict) -> dict:
    d = s["dims"]
    lf, rf = d["lf"], d["rf"]
    diff = lf - rf
    if diff >= 12:
        lhh = (f"Left-handed hitters benefit from a shorter right field ({rf} ft) relative to left ({lf} ft), "
               f"making the pull-side porch more reachable.")
        rhh = (f"Right-handed hitters face a deeper left field ({lf} ft) on the pull side, so opposite-field power "
               f"and gap contact are more productive paths.")
    elif diff <= -12:
        lhh = (f"Left-handed hitters face a deeper right field ({rf} ft) on the pull side, favoring gap-to-gap and "
               f"opposite-field contact.")
        rhh = (f"Right-handed hitters benefit from a shorter left field ({lf} ft) relative to right ({rf} ft), "
               f"making the pull-side fence more reachable.")
    else:
        lhh = (f"With near-symmetrical corners ({rf} ft to right), left-handed hitters gain no pronounced pull-side "
               f"edge; overall carry and weather drive their outcomes.")
        rhh = (f"With near-symmetrical corners ({lf} ft to left), right-handed hitters gain no pronounced pull-side "
               f"edge; overall carry and weather drive their outcomes.")
    return {"lhh": lhh, "rhh": rhh}


def weather_paragraph(s: dict) -> str:
    roof = s["roof"].lower()
    if "dome" in roof:
        return (
            f"{s['name']} is a fixed-dome environment, so wind, temperature, humidity, and precipitation are removed "
            f"from play. That makes batted-ball carry highly consistent and minimizes the night-to-night variance that "
            f"open-air parks experience. EdgeRanked's MLB weather intelligence treats this park as a controlled, "
            f"low-sensitivity environment."
        )
    base = (
        f"As {'a retractable-roof' if 'retract' in roof else 'an open-air'} ballpark at roughly {s['elevation']:,} "
        f"feet of elevation, {s['name']} is shaped by real weather. Warmer air and lower humidity let the ball carry "
        f"farther, while cool, damp, or heavy marine air suppresses fly-ball distance. Wind direction matters most: a "
        f"breeze blowing out turns fly balls into home runs, while an inbound wind knocks them down. "
    )
    if s["wind_exposure"] >= 3:
        base += "This park has a strong reputation for wind that can swing run scoring dramatically from day to day. "
    elif s["wind_exposure"] == 2:
        base += "Wind is a meaningful, regularly-felt factor here. "
    if "retract" in roof:
        base += "When the roof is closed, those weather effects are largely neutralized. "
    base += "These effects are evergreen tendencies; EdgeRanked layers live forecasts on top of them for game-day projections."
    return base


# --- rendering --------------------------------------------------------------

_STADIUM_STYLES = """
<style>
.stadiums{max-width:1100px;margin:0 auto}
.stadiums .panel{margin-bottom:22px}
.st-table{width:100%;border-collapse:collapse;margin-top:12px;font-size:14px}
.st-table th,.st-table td{padding:10px 12px;border-bottom:1px solid var(--line,#1e293b);text-align:left}
.st-table th{color:var(--muted,#94a3b8);font-weight:600;text-transform:uppercase;letter-spacing:.04em;font-size:12px}
.st-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-top:14px}
.st-fact{background:var(--surface,#121929);border:1px solid var(--line,#1e293b);border-radius:14px;padding:14px}
.st-fact .v{font-size:18px;font-weight:800;color:var(--ink,#f8fafc)}
.st-fact .l{color:var(--muted,#94a3b8);font-size:12px;margin-top:4px;text-transform:uppercase;letter-spacing:.04em}
.st-dims{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:12px;margin-top:14px}
.st-dim{background:var(--surface,#121929);border:1px solid var(--line,#1e293b);border-radius:14px;padding:14px;text-align:center}
.st-dim .v{font-size:24px;font-weight:800;color:#60a5fa}
.st-dim .l{color:var(--muted,#94a3b8);font-size:12px;margin-top:4px}
.st-scores{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-top:14px}
.st-score{background:var(--surface,#121929);border:1px solid var(--line,#1e293b);border-radius:14px;padding:16px}
.st-score .name{font-size:13px;color:var(--muted,#94a3b8);text-transform:uppercase;letter-spacing:.04em}
.st-score .num{font-size:30px;font-weight:800;color:var(--ink,#f8fafc);margin:6px 0 2px}
.st-bar{height:6px;border-radius:999px;background:rgba(148,163,184,.18);overflow:hidden;margin-top:8px}
.st-bar>span{display:block;height:100%;background:linear-gradient(90deg,#3b82f6,#22c55e)}
.st-score .tier{font-size:12px;color:#60a5fa;margin-top:8px;font-weight:600}
.st-prose{color:var(--ink,#e5edf7);line-height:1.7;margin-top:10px}
.st-hand{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
@media(max-width:640px){.st-hand{grid-template-columns:1fr}}
.st-hand .card{background:var(--surface,#121929);border:1px solid var(--line,#1e293b);border-radius:14px;padding:16px}
.st-hand h4{margin:0 0 8px;color:#60a5fa;font-size:13px;text-transform:uppercase;letter-spacing:.04em}
.st-unavailable{color:var(--muted,#94a3b8);font-style:italic;margin-top:10px}
.st-related{display:flex;flex-wrap:wrap;gap:10px;margin-top:8px}
.st-related a{padding:8px 14px;border-radius:999px;border:1px solid var(--line,#1e293b);color:#cbd5f5;text-decoration:none;font-size:13px}
.st-related a:hover{color:#fff;border-color:#3b82f6}
.st-dir{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:14px}
@media(max-width:760px){.st-dir{grid-template-columns:1fr}}
.st-dir ul{list-style:none;padding:0;margin:8px 0 0}
.st-dir li{margin:0 0 6px}
.st-dir a{display:flex;justify-content:space-between;padding:11px 14px;border-radius:10px;border:1px solid var(--line,#1e293b);background:var(--surface,#121929);color:var(--ink,#e5edf7);text-decoration:none}
.st-dir a:hover{border-color:#3b82f6}
.st-dir .meta{color:var(--muted,#94a3b8);font-size:12px}
#st-search{width:100%;padding:12px 14px;border-radius:12px;border:1px solid var(--line,#1e293b);background:var(--surface,#121929);color:var(--ink,#e5edf7);font-size:15px;margin-top:6px}
</style>
"""


def _panel(eyebrow, heading, inner, note=""):
    note_html = f"<p class='muted'>{escape(note)}</p>" if note else ""
    return ("<section class='panel'><div class='panel-head'><div>"
            f"<div class='eyebrow'>{escape(eyebrow)}</div><h2>{escape(heading)}</h2></div>"
            f"{note_html}</div>{inner}</section>")


def _json_ld(scripts):
    return "".join('<script type="application/ld+json">' + json.dumps(x, ensure_ascii=False) + "</script>" for x in scripts)


def render_stadium_body(site_origin: str, s: dict) -> str:
    d = s["dims"]
    scores = park_intelligence(s)
    page_url = f"{site_origin}/mlb/stadium/{s['slug']}"

    # Section 1 — overview
    facts = [
        (s["team"], "Home Team"), (_location(s), "Location"), (str(s["opened"]), "Opened"),
        (f"{s['capacity']:,}", "Capacity"), (s["surface"], "Surface"),
        (f"{s['elevation']:,} ft", "Elevation"), (s["roof"], "Roof"), (s["tz"], "Time Zone"),
    ]
    facts_html = "".join(f"<div class='st-fact'><div class='v'>{escape(v)}</div><div class='l'>{escape(l)}</div></div>" for v, l in facts)
    team_slug = _team_page_slug(s["team"])
    team_line = (
        f"<p class='st-prose'>Home of the <a href='/mlb/team/{team_slug}'>{escape(s['team'])}</a> — "
        f"see the <a href='/mlb/team/{team_slug}'>team profile</a> and "
        f"<a href='/mlb/team/{team_slug}/strikeouts'>strikeout tendencies</a>.</p>"
    )
    sec1 = _panel("Overview", f"{s['name']} Overview",
                  f"<div class='st-facts'>{facts_html}</div><p class='st-prose'>{escape(overview_paragraph(s))}</p>" + team_line)

    # Section 2 — dimensions
    dim_order = [("Left Field", d["lf"]), ("Left-Center", d["lc"]), ("Center Field", d["cf"]),
                 ("Right-Center", d["rc"]), ("Right Field", d["rf"])]
    dims_cards = "".join(f"<div class='st-dim'><div class='v'>{v}</div><div class='l'>{escape(l)}</div></div>" for l, v in dim_order)
    dims_table = ("<table class='st-table'><thead><tr><th>Field</th><th>Distance</th></tr></thead><tbody>"
                  + "".join(f"<tr><td>{escape(l)}</td><td>{v} ft</td></tr>" for l, v in dim_order)
                  + "</tbody></table>")
    sec2 = _panel("Dimensions", "Official Outfield Dimensions",
                  f"<div class='st-dims'>{dims_cards}</div>{dims_table}",
                  "Posted official outfield distances (feet).")

    # Section 3 — EdgeRanked Park Intelligence
    score_cards = ""
    for name, val in scores.items():
        score_cards += (f"<div class='st-score'><div class='name'>{escape(name)}</div>"
                        f"<div class='num'>{val}<span style='font-size:14px;color:#94a3b8'>/100</span></div>"
                        f"<div class='st-bar'><span style='width:{val}%'></span></div>"
                        f"<div class='tier'>{escape(_tier_label(val))}</div></div>")
    sec3 = _panel("EdgeRanked Park Intelligence", "Proprietary Park Ratings",
                  f"<div class='st-scores'>{score_cards}</div>",
                  "EdgeRanked's deterministic 0-100 outlook ratings derived from verified park geometry, elevation, and configuration. Higher favors the named environment; Pitcher Friendliness is the inverse.")

    # Section 4 — park factors (unavailable, not fabricated)
    pf_rows = "".join(f"<tr><td>{escape(l)}</td><td><span class='st-unavailable'>Unavailable</span></td></tr>"
                      for l in ["Home Run Factor", "Run Factor", "Singles Factor", "Doubles Factor", "Triples Factor"])
    sec4 = _panel("Park Factors", "Empirical Park Factors",
                  f"<table class='st-table'><thead><tr><th>Factor</th><th>Value</th></tr></thead><tbody>{pf_rows}</tbody></table>",
                  "Verified multi-season empirical park factors are not part of EdgeRanked's published dataset, so they are shown as Unavailable rather than estimated.")

    # Section 5 — handedness
    hand = handedness_analysis(s)
    sec5_inner = ("<div class='st-hand'>"
                  f"<div class='card'><h4>Left-Handed Hitter Impact</h4><p class='st-prose' style='margin-top:0'>{escape(hand['lhh'])}</p></div>"
                  f"<div class='card'><h4>Right-Handed Hitter Impact</h4><p class='st-prose' style='margin-top:0'>{escape(hand['rhh'])}</p></div>"
                  "</div>")
    sec5 = _panel("Handedness", "Handedness Analysis", sec5_inner,
                  "Geometry-based read on how the park's dimensions play for each batter handedness.")

    # Section 6 — weather impact
    sec6 = _panel("Weather Impact", "Weather & Environment",
                  f"<p class='st-prose'>{escape(weather_paragraph(s))}</p>")

    # Section 7 — notable characteristics
    sec7 = _panel("Notable Characteristics", "Ballpark Profile",
                  f"<p class='st-prose'>{escape(characteristics_paragraph(s))}</p>")

    # Section 8 — related resources
    related = ("<div class='st-related'>"
               f"<a href='/mlb/team/{team_slug}'>{escape(s['team'])} Team Profile</a>"
               f"<a href='/mlb/team/{team_slug}/strikeouts'>{escape(s['team'])} Strikeouts</a>"
               "<a href='/mlb/teams'>All MLB Teams</a>"
               "<a href='/mlb/weather'>MLB Weather</a>"
               "<a href='/mlb/results'>MLB Results Archive</a>"
               "<a href='/mlb'>MLB Home</a>"
               "<a href='/mlb/stadiums'>All Stadiums</a>"
               "</div>")
    sec8 = _panel("Related EdgeRanked Resources", f"Explore {s['team']} Coverage", related)

    # Structured data: SportsVenue + Breadcrumb + FAQ
    hr_score = scores["Home Run Environment"]
    park_lean = ("a hitter-friendly park" if scores["Run Scoring Environment"] >= 58
                 else "a pitcher-friendly park" if scores["Run Scoring Environment"] <= 42
                 else "a balanced, fairly neutral park")
    json_ld = _json_ld([
        {
            "@context": "https://schema.org", "@type": "StadiumOrArena",
            "name": s["name"], "url": page_url,
            "address": {"@type": "PostalAddress", "addressLocality": s["city"],
                        "addressRegion": s["state"], "addressCountry": "US" if s["state"] not in ("Ontario",) else "CA"},
            "maximumAttendeeCapacity": s["capacity"],
            "additionalProperty": [
                {"@type": "PropertyValue", "name": "Opened", "value": s["opened"]},
                {"@type": "PropertyValue", "name": "Surface", "value": s["surface"]},
                {"@type": "PropertyValue", "name": "Roof", "value": s["roof"]},
                {"@type": "PropertyValue", "name": "Elevation (ft)", "value": s["elevation"]},
                {"@type": "PropertyValue", "name": "Center Field (ft)", "value": d["cf"]},
            ],
        },
        {
            "@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "MLB", "item": f"{site_origin}/mlb"},
                {"@type": "ListItem", "position": 2, "name": "Stadiums", "item": f"{site_origin}/mlb/stadiums"},
                {"@type": "ListItem", "position": 3, "name": s["name"], "item": page_url},
            ],
        },
        {
            "@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": f"When did {s['name']} open?",
                 "acceptedAnswer": {"@type": "Answer", "text": f"{s['name']} opened in {s['opened']} and is the home of the {s['team']} in {_location(s)}."}},
                {"@type": "Question", "name": f"What are the outfield dimensions at {s['name']}?",
                 "acceptedAnswer": {"@type": "Answer", "text": f"Left field is {d['lf']} ft, left-center {d['lc']} ft, center field {d['cf']} ft, right-center {d['rc']} ft, and right field {d['rf']} ft."}},
                {"@type": "Question", "name": f"Is {s['name']} a hitter's park or a pitcher's park?",
                 "acceptedAnswer": {"@type": "Answer", "text": f"By EdgeRanked's deterministic park ratings, {s['name']} grades as {park_lean}, with a Home Run Environment score of {hr_score}/100."}},
            ],
        },
    ])

    breadcrumb_nav = ("<div class='st-related' style='margin-bottom:14px'>"
                      "<a href='/mlb'>MLB</a><a href='/mlb/stadiums'>Stadiums</a>"
                      f"<span style='color:#94a3b8;padding:8px 4px'>{escape(s['name'])}</span></div>")

    return (_STADIUM_STYLES + json_ld + "<div class='stadiums'>" + breadcrumb_nav
            + sec1 + sec2 + sec3 + sec4 + sec5 + sec6 + sec7 + sec8 + "</div>")


def render_index_body(site_origin: str) -> str:
    al = [s for s in STADIUMS if s["league"] == "AL"]
    nl = [s for s in STADIUMS if s["league"] == "NL"]

    def col(title, parks):
        items = "".join(
            f"<li><a href='/mlb/stadium/{p['slug']}' data-name='{escape(p['name'].lower())} {escape(p['team'].lower())} {escape(p['city'].lower())}'>"
            f"<span>{escape(p['name'])}</span><span class='meta'>{escape(p['team'])}</span></a></li>"
            for p in sorted(parks, key=lambda x: x["name"])
        )
        return f"<div><h3 style='margin:0 0 4px'>{escape(title)}</h3><ul>{items}</ul></div>"

    directory = ("<div class='st-dir' id='st-dir'>" + col("American League", al) + col("National League", nl) + "</div>")
    search = ("<input id='st-search' type='search' placeholder='Search stadiums, teams, or cities…' "
              "oninput=\"var q=this.value.toLowerCase();document.querySelectorAll('#st-dir li').forEach(function(li){var a=li.querySelector('a');li.style.display=a.getAttribute('data-name').indexOf(q)>-1?'':'none';});\">")

    intro = ("<section class='panel'><div class='panel-head'><div>"
             "<div class='eyebrow'>Ballpark Reference</div><h2>MLB Stadium Intelligence</h2></div></div>"
             "<p class='muted'>An authoritative, evergreen reference for all 30 active Major League Baseball ballparks — "
             "official dimensions, capacity, elevation, surface, and roof type, plus EdgeRanked's proprietary park "
             "intelligence ratings for home-run environment, run scoring, pitcher friendliness, extra-base hits, and "
             "weather sensitivity. Each ballpark links directly into EdgeRanked's MLB projections, weather, and results "
             "coverage.</p>" + search + "</section>")

    listing = _panel("Stadium Directory", "All 30 MLB Ballparks", directory,
                     "Browse by league. Every stadium has a full intelligence page.")

    item_list = {
        "@context": "https://schema.org", "@type": "ItemList",
        "name": "MLB Stadium Intelligence", "numberOfItems": len(STADIUMS),
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": s["name"], "url": f"{site_origin}/mlb/stadium/{s['slug']}"}
            for i, s in enumerate(STADIUMS)
        ],
    }
    breadcrumb = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "MLB", "item": f"{site_origin}/mlb"},
            {"@type": "ListItem", "position": 2, "name": "Stadiums", "item": f"{site_origin}/mlb/stadiums"},
        ],
    }
    related = ("<div class='st-related' style='margin-top:18px'>"
               "<a href='/mlb/projections'>MLB Projections</a><a href='/mlb/weather'>MLB Weather</a>"
               "<a href='/mlb/results'>MLB Results Archive</a><a href='/mlb/intel'>MLB Intel</a>"
               "<a href='/mlb'>MLB Home</a></div>")

    return (_STADIUM_STYLES + _json_ld([item_list, breadcrumb]) + "<div class='stadiums'>" + intro + listing + related + "</div>")


# --- sitemap integration ----------------------------------------------------

def stadiums_sitemap_entries():
    """Return (path, changefreq, priority) for the index + all 30 stadiums."""
    entries = [("/mlb/stadiums", "monthly", "0.8")]
    for s in STADIUMS:
        entries.append((f"/mlb/stadium/{s['slug']}", "monthly", "0.8"))
    return entries


# --- route registration -----------------------------------------------------

def register_mlb_stadium_routes(flask_app, render_layout, site_origin):
    @flask_app.get("/mlb/stadiums")
    def mlb_stadiums_index():
        body = render_index_body(site_origin)
        return render_layout(
            "MLB Stadium Intelligence",
            "Official dimensions, park factors, and EdgeRanked park intelligence for all 30 MLB ballparks.",
            body, "/mlb/stadiums",
            meta_description="MLB Stadium Intelligence: official dimensions, capacity, elevation, surface, roof type, and EdgeRanked's proprietary park ratings for all 30 Major League Baseball ballparks.",
            document_title="MLB Stadium Intelligence | EdgeRanked AI",
            hero_kicker="MLB",
        )

    @flask_app.get("/mlb/stadium/<stadium_slug>")
    def mlb_stadium_page(stadium_slug):
        if not SLUG_RE.match(stadium_slug or "") or stadium_slug not in BY_SLUG:
            abort(404)
        s = BY_SLUG[stadium_slug]
        body = render_stadium_body(site_origin, s)
        return render_layout(
            f"{s['name']} — Dimensions, Park Factors & Intelligence",
            f"Home of the {s['team']} in {_location(s)}.",
            body, "/mlb/stadiums",
            meta_description=(f"{s['name']} ({s['team']}, {_location(s)}): official outfield dimensions, capacity "
                              f"{s['capacity']:,}, {s['elevation']:,}-ft elevation, {s['roof'].lower()} roof, and "
                              f"EdgeRanked park intelligence ratings."),
            document_title=f"{s['name']} — Park Dimensions & Intelligence | EdgeRanked AI",
            hero_kicker="MLB Stadium",
        )
