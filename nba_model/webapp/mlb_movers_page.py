"""MLB Biggest Movers — Phase 2 ADMIN-GATED preview page (premium dashboard UI).

Renders /mlb/movers (+ /admin/mlb/movers alias) from the precomputed
``mlb_movers_today.json`` artifact ONLY. Hard constraints (by design, do not
relax without a decision):

  * reads one JSON file with an mtime cache — no model access, no pandas,
    no recalculation, no network, no writes;
  * the route is registered admin-gated (same ``_internal_is_admin`` gate as
    /admin/qa/mlb/board) and ``noindex, nofollow`` until several slates of
    reason-tag output have been reviewed;
  * missing/absent JSON renders a friendly empty state, never an error.

Layout (2026-07-04 redesign — UI only, zero data/schema changes):
compact summary strip -> "Today's Biggest Moves" hero -> "Today's Changes"
reason summary -> STICKY filters -> HR/Hit/PitcherK mover cards (monogram,
abbreviated matchup, sparkline, ET timestamps) -> collapsible New/Dropped.
Sparklines draw whatever points exist: an optional per-mover ``history``
list if a future builder provides one, else the two guaranteed points
(morning_value, current_value) — graceful by construction.

Filters are pure client-side show/hide over data attributes — the server
renders one static document.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path

MOVERS_JSON_PATHS = [
    Path("/home/ubuntu/mlb_model/mlb/outputs/movers/mlb_movers_today.json"),
    Path("/home/ubuntu/edgeranked-sportsai/mlb/outputs/mlb_movers_today.json"),
]

_cache: dict = {}

_SECTION_DEFS = [
    ("hr_prob", "Top HR Movers", "HR probability, points since the morning baseline."),
    ("hit_prob", "Top Hit Movers", "Hit probability, points since the morning baseline."),
    ("proj_pitcher_k", "Top Pitcher K Movers", "Projected strikeouts since the morning baseline."),
]

# consistent tag palette (spec: green / purple / blue / orange / gray)
_TAG_COLORS = {
    "Lineup Confirmed": ("rgba(34,197,94,.15)", "#4ade80"),
    "Starting Pitcher Change": ("rgba(168,85,247,.16)", "#c4b5fd"),
    "Weather Change": ("rgba(56,189,248,.15)", "#7dd3fc"),
    "Model Refresh": ("rgba(249,115,22,.16)", "#fdba74"),
    "Unknown": ("rgba(148,163,184,.12)", "#94a3b8"),
}
# display names only — the underlying tag value in data attrs stays honest
_TAG_DISPLAY = {"Unknown": "Unattributed"}

_ABBREV = {
    "Arizona Diamondbacks": "ARI", "Athletics": "ATH", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS", "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS", "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET", "Houston Astros": "HOU",
    "Kansas City Royals": "KC", "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN",
    "New York Mets": "NYM", "New York Yankees": "NYY", "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
}

_UP, _DOWN = "#4ade80", "#f87171"


def _load_payload() -> dict | None:
    for p in MOVERS_JSON_PATHS:
        try:
            if not p.is_file():
                continue
            mtime = p.stat().st_mtime
            hit = _cache.get(str(p))
            if hit and hit[0] == mtime:
                return hit[1]
            data = json.loads(p.read_text(encoding="utf-8"))
            _cache[str(p)] = (mtime, data)
            return data
        except Exception:
            continue
    return None


def _parse_ts(iso: str):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return None


def _fmt_et_short(iso: str) -> str:
    """'2026-07-04T13:39:36Z' -> '9:39 AM ET' (falls back to UTC text)."""
    dt = _parse_ts(iso)
    if dt is None:
        return str(iso)
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p ET")
    except Exception:
        return dt.astimezone(timezone.utc).strftime("%H:%M UTC")


def _fmt_ts_full(iso: str) -> str:
    dt = _parse_ts(iso)
    if dt is None:
        return str(iso)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _fmt_val(value, kind: str) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{v:.1f}%" if kind == "probability" else f"{v:.2f}"


def _abbrev(team: str) -> str:
    t = str(team or "")
    if t in _ABBREV:
        return _ABBREV[t]
    return "".join(w[0] for w in t.split()[:3]).upper() or "?"


# Official MLB team branding, keyed by the abbreviation _abbrev() produces.
# primary = monogram fill, secondary = border/glow accent, text = glyph color
# (white or black, chosen for contrast on the primary fill). Sourced from each
# club's published brand palette; text flipped to black only where a light-ish
# primary needs it (BAL orange). Marlins/Giants use their dark cap color as the
# primary with the bright accent as the ring — both more recognizable and higher
# contrast than the reverse.
_DEFAULT_COLORS = {"primary": "#334155", "secondary": "#64748b", "text": "#ffffff"}
TEAM_COLORS = {
    "ARI": {"primary": "#A71930", "secondary": "#E3D4AD", "text": "#ffffff"},
    "ATH": {"primary": "#003831", "secondary": "#EFB21E", "text": "#ffffff"},
    "ATL": {"primary": "#CE1141", "secondary": "#13274F", "text": "#ffffff"},
    "BAL": {"primary": "#DF4601", "secondary": "#000000", "text": "#000000"},
    "BOS": {"primary": "#BD3039", "secondary": "#0C2340", "text": "#ffffff"},
    "CHC": {"primary": "#0E3386", "secondary": "#CC3433", "text": "#ffffff"},
    "CWS": {"primary": "#27251F", "secondary": "#C4CED4", "text": "#ffffff"},
    "CIN": {"primary": "#C6011F", "secondary": "#000000", "text": "#ffffff"},
    "CLE": {"primary": "#0C2340", "secondary": "#E31937", "text": "#ffffff"},
    "COL": {"primary": "#33006F", "secondary": "#C4CED4", "text": "#ffffff"},
    "DET": {"primary": "#0C2340", "secondary": "#FA4616", "text": "#ffffff"},
    "HOU": {"primary": "#002D62", "secondary": "#EB6E1F", "text": "#ffffff"},
    "KC":  {"primary": "#004687", "secondary": "#BD9B60", "text": "#ffffff"},
    "LAA": {"primary": "#BA0021", "secondary": "#003263", "text": "#ffffff"},
    "LAD": {"primary": "#005A9C", "secondary": "#FFFFFF", "text": "#ffffff"},
    "MIA": {"primary": "#000000", "secondary": "#00A3E0", "text": "#ffffff"},
    "MIL": {"primary": "#12284B", "secondary": "#FFC52F", "text": "#ffffff"},
    "MIN": {"primary": "#002B5C", "secondary": "#D31145", "text": "#ffffff"},
    "NYM": {"primary": "#002D72", "secondary": "#FF5910", "text": "#ffffff"},
    "NYY": {"primary": "#132448", "secondary": "#C4CED4", "text": "#ffffff"},
    "PHI": {"primary": "#E81828", "secondary": "#002D72", "text": "#ffffff"},
    "PIT": {"primary": "#27251F", "secondary": "#FDB827", "text": "#ffffff"},
    "SD":  {"primary": "#2F241D", "secondary": "#FFC425", "text": "#ffffff"},
    "SF":  {"primary": "#27251F", "secondary": "#FD5A1E", "text": "#ffffff"},
    "SEA": {"primary": "#0C2C56", "secondary": "#005C5C", "text": "#ffffff"},
    "STL": {"primary": "#C41E3A", "secondary": "#0C2340", "text": "#ffffff"},
    "TB":  {"primary": "#092C5C", "secondary": "#8FBCE6", "text": "#ffffff"},
    "TEX": {"primary": "#003278", "secondary": "#C0111F", "text": "#ffffff"},
    "TOR": {"primary": "#134A8E", "secondary": "#1D2D5C", "text": "#ffffff"},
    "WSH": {"primary": "#AB0003", "secondary": "#14225A", "text": "#ffffff"},
}


def _hex_rgba(hex_color: str, alpha: float) -> str:
    """'#RRGGBB' -> 'rgba(r,g,b,a)'; falls back to a neutral tint on bad input."""
    try:
        h = str(hex_color).lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"
    except Exception:
        return f"rgba(100,116,139,{alpha})"


def _monogram(team: str, size: int = 34) -> str:
    ab = _abbrev(team)
    c = TEAM_COLORS.get(ab, _DEFAULT_COLORS)
    fs = 11 if len(ab) > 2 else 12
    glow = _hex_rgba(c["secondary"], 0.45)
    return (f"<span class='mv-mono' style='width:{size}px;height:{size}px;font-size:{fs}px;"
            f"background:{c['primary']};border-color:{c['secondary']};color:{c['text']};"
            f"box-shadow:0 1px 7px -1px {glow}'>{escape(ab)}</span>")


def _matchup(m: dict) -> str:
    return f"{_abbrev(m.get('team'))} vs {_abbrev(m.get('opponent'))}"


def _tag_pill(tag: str, small: bool = False) -> str:
    bg, fg = _TAG_COLORS.get(tag, _TAG_COLORS["Unknown"])
    pad = "2px 9px" if small else "4px 11px"
    return (f"<span style='display:inline-block;padding:{pad};border-radius:999px;"
            f"background:{bg};color:{fg};font-size:11px;font-weight:800;letter-spacing:.03em;"
            f"white-space:nowrap'>{escape(_TAG_DISPLAY.get(tag, tag))}</span>")


def _spark_points(m: dict) -> list:
    """Points for the sparkline: optional future ``history`` list, else the
    two guaranteed endpoints. Never raises, never fewer than 2 points."""
    pts = []
    hist = m.get("history")
    if isinstance(hist, list):
        for v in hist:
            try:
                pts.append(float(v))
            except (TypeError, ValueError):
                continue
    if len(pts) < 2:
        try:
            pts = [float(m.get("morning_value")), float(m.get("current_value"))]
        except (TypeError, ValueError):
            return []
    return pts


def _sparkline(m: dict) -> str:
    pts = _spark_points(m)
    if len(pts) < 2:
        return ""
    w, h, pad = 76, 26, 4
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1.0
    step = (w - 2 * pad) / (len(pts) - 1)
    xy = [(pad + i * step, h - pad - (v - lo) / rng * (h - 2 * pad)) for i, v in enumerate(pts)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in xy)
    color = _UP if m.get("direction") == "up" else _DOWN
    dots = "".join(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='1.6' fill='#475569'/>" for x, y in xy[:-1])
    ex, ey = xy[-1]
    return (f"<svg class='mv-spark' viewBox='0 0 {w} {h}' width='{w}' height='{h}' aria-hidden='true'>"
            f"<polyline points='{poly}' fill='none' stroke='{color}' stroke-width='2'"
            " stroke-linecap='round' stroke-linejoin='round' opacity='.85'/>"
            f"{dots}<circle cx='{ex:.1f}' cy='{ey:.1f}' r='2.6' fill='{color}'/></svg>")


def _delta_chip(m: dict) -> str:
    up = m.get("direction") == "up"
    color = _UP if up else _DOWN
    arrow = "▲" if up else "▼"
    kind = m.get("kind", "probability")
    try:
        txt = f"{float(m.get('abs_change')):+.1f}{'pp' if kind == 'probability' else ''}"
    except (TypeError, ValueError):
        txt = "—"
    return (f"<span style='color:{color};font-weight:900;font-size:15px;white-space:nowrap'>"
            f"{arrow} {escape(txt)}</span>")


def _mover_card(m: dict, market_key: str, updated_short: str, k8_by_pid: dict) -> str:
    up = m.get("direction") == "up"
    color = _UP if up else _DOWN
    kind = m.get("kind", "probability")
    tag = str(m.get("reason_tag") or "Unknown")
    detail = str(m.get("reason_detail") or "")
    detail_html = (f"<div class='mv-detail'>↳ {escape(detail)}</div>" if detail else "")
    k8_html = ""
    if market_key == "proj_pitcher_k":
        k8 = k8_by_pid.get(str(m.get("player_id") or ""))
        if k8:
            k8_html = (f"<div class='mv-detail'>8+ K prob: "
                       f"{_fmt_val(k8.get('morning_value'), 'probability')} → "
                       f"{_fmt_val(k8.get('current_value'), 'probability')}</div>")
    return (
        f"<div class='mv-card' data-market='{escape(market_key)}' data-reason='{escape(tag)}'"
        f" style='border-left:3px solid {color}'>"
        "<div class='mv-card-top'>"
        f"{_monogram(m.get('team'))}"
        "<div class='mv-id'>"
        f"<div class='mv-name'>{escape(str(m.get('player_name', '')))}</div>"
        f"<div class='mv-match'>{escape(_matchup(m))}</div>"
        "</div>"
        f"{_delta_chip(m)}"
        "</div>"
        "<div class='mv-vals'>"
        f"<div class='mv-nums'>{_fmt_val(m.get('morning_value'), kind)}"
        f"<span class='mv-arrow'>→</span>"
        f"<span style='color:{color}'>{_fmt_val(m.get('current_value'), kind)}</span></div>"
        f"{_sparkline(m)}"
        "</div>"
        f"<div class='mv-tags'>{_tag_pill(tag)}</div>"
        + detail_html + k8_html +
        f"<div class='mv-ts'>Updated {escape(updated_short)}</div>"
        "</div>"
    )


def _hero_card(emoji: str, label: str, m: dict | None, kind: str) -> str:
    if not m:
        return (f"<div class='mv-hero-card'><div class='mv-hero-label'>{escape(emoji + ' ' + label)}</div>"
                "<div class='mv-hero-empty'>No qualifying move yet</div></div>")
    up = m.get("direction") == "up"
    color = _UP if up else _DOWN
    tag = str(m.get("reason_tag") or "Unknown")
    return (
        f"<div class='mv-hero-card' style='border-top:3px solid {color}'>"
        f"<div class='mv-hero-label'>{escape(emoji + ' ' + label)}</div>"
        "<div class='mv-hero-row'>"
        f"{_monogram(m.get('team'), 30)}"
        f"<div class='mv-hero-name'>{escape(str(m.get('player_name', '')))}</div>"
        f"{_delta_chip(m)}"
        "</div>"
        f"<div class='mv-hero-vals'>{_fmt_val(m.get('morning_value'), kind)}"
        f"<span class='mv-arrow'>→</span>"
        f"<span style='color:{color};font-weight:800'>{_fmt_val(m.get('current_value'), kind)}</span>"
        f"&nbsp;&nbsp;{_tag_pill(tag, small=True)}</div>"
        "</div>"
    )


def _reason_summary(reason_mix: dict) -> str:
    if not reason_mix:
        return ""
    total = sum(reason_mix.values()) or 1
    order = sorted(reason_mix, key=lambda t: -reason_mix[t])
    segs = "".join(
        f"<span style='display:block;height:100%;float:left;width:{reason_mix[t] / total * 100:.2f}%;"
        f"background:{_TAG_COLORS.get(t, _TAG_COLORS['Unknown'])[1]}'></span>"
        for t in order)
    chips = "".join(
        f"<span class='mv-mixchip'>"
        f"<span class='mv-dot' style='background:{_TAG_COLORS.get(t, _TAG_COLORS['Unknown'])[1]}'></span>"
        f"<strong>{reason_mix[t]}</strong>&nbsp;{escape(_TAG_DISPLAY.get(t, t))}</span>"
        for t in order)
    return ("<div class='mv-mix'>"
            "<div class='mv-mix-title'>Today's Changes</div>"
            f"<div class='mv-mixbar'>{segs}</div>"
            f"<div class='mv-mixchips'>{chips}</div>"
            "</div>")


def _names_details(title: str, count: int, names: list, empty_msg: str, note: str = "") -> str:
    pills = "".join(f"<span class='mv-pill'>{escape(str(n))}</span>" for n in names)
    inner = (f"<div style='margin-top:10px'>{pills}</div>" if names
             else f"<p class='muted' style='margin:10px 0 0'>{escape(empty_msg)}</p>")
    note_html = f"<p class='muted' style='font-size:12px;margin:8px 0 0'>{escape(note)}</p>" if note else ""
    return (f"<details class='mv-details'><summary>{escape(title)}"
            f"<span class='mv-count'>{count}</span></summary>{inner}{note_html}</details>")


_STYLE = """
<style>
.mv-wrap{max-width:1100px;margin:0 auto}
.mv-wrap .panel{padding:16px;margin-bottom:14px}
.mv-strip{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin-top:10px;
  font-size:13px;color:#cbd5e1}
.mv-strip b{color:#f8fafc;font-weight:800}
.mv-copy{color:#94a3b8;font-size:13px;line-height:1.5;margin:8px 0 0}
.mv-hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;margin:0 0 14px}
.mv-hero-card{background:linear-gradient(160deg,rgba(30,41,59,.55),rgba(15,23,42,.92));
  border:1px solid var(--line,#1e293b);border-radius:14px;padding:12px 14px;min-width:0}
.mv-hero-label{font-size:11px;font-weight:900;letter-spacing:.06em;text-transform:uppercase;color:#93c5fd}
.mv-hero-row{display:flex;align-items:center;gap:9px;margin-top:9px}
.mv-hero-name{flex:1;min-width:0;font-weight:800;font-size:15px;color:#f8fafc;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mv-hero-vals{margin-top:7px;font-size:14px;color:#cbd5e1;font-weight:600}
.mv-hero-empty{margin-top:12px;color:#64748b;font-size:13px}
.mv-mono{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;
  border-radius:50%;border:1.5px solid;font-weight:900;letter-spacing:.02em;
  text-shadow:0 1px 1px rgba(0,0,0,.35)}
.mv-mix{background:var(--surface,#121929);border:1px solid var(--line,#1e293b);
  border-radius:14px;padding:12px 14px;margin:0 0 14px}
.mv-mix-title{font-size:11px;font-weight:900;letter-spacing:.06em;text-transform:uppercase;color:#93c5fd}
.mv-mixbar{height:10px;border-radius:999px;overflow:hidden;background:rgba(148,163,184,.12);margin-top:9px}
.mv-mixchips{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:9px}
.mv-mixchip{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:#cbd5e1}
.mv-mixchip strong{color:#f8fafc}
.mv-dot{width:9px;height:9px;border-radius:50%;flex:0 0 auto}
.mv-sticky{position:sticky;top:0;z-index:40;background:rgba(9,14,26,.94);
  -webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);
  margin:0 -6px 14px;padding:9px 6px;border-bottom:1px solid var(--line,#1e293b)}
.mv-frow{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.mv-frow+.mv-frow{margin-top:6px}
.mv-flabel{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.06em;
  font-weight:900;flex:0 0 52px}
.mv-fbtn{padding:9px 15px;min-height:40px;border-radius:999px;border:1px solid var(--line,#1e293b);
  background:var(--surface,#121929);color:#cbd5e1;font-size:13px;font-weight:700;cursor:pointer}
.mv-fbtn.active{border-color:#3b82f6;color:#fff;background:rgba(59,130,246,.16)}
.mv-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(255px,1fr));gap:10px;margin-top:12px}
.mv-card{background:var(--surface,#121929);border:1px solid var(--line,#1e293b);
  border-radius:14px;padding:13px 14px;min-width:0}
.mv-card-top{display:flex;align-items:center;gap:10px}
.mv-id{flex:1;min-width:0}
.mv-name{font-weight:800;color:var(--ink,#f8fafc);font-size:15px;line-height:1.25;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.mv-match{font-size:12px;color:#94a3b8;margin-top:1px;font-weight:600;letter-spacing:.02em}
.mv-vals{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:10px}
.mv-nums{font-size:16px;color:#e2e8f0;font-weight:800}
.mv-arrow{color:#64748b;margin:0 6px;font-weight:400}
.mv-spark{flex:0 0 auto}
.mv-tags{margin-top:9px}
.mv-detail{font-size:12px;color:#94a3b8;margin-top:6px;line-height:1.45}
.mv-ts{font-size:10.5px;color:#64748b;margin-top:8px}
.mv-pill{display:inline-block;margin:3px;padding:6px 12px;border-radius:999px;
  background:rgba(148,163,184,.10);border:1px solid var(--line,#1e293b);color:#cbd5e1;font-size:12px}
.mv-details{background:var(--surface,#121929);border:1px solid var(--line,#1e293b);
  border-radius:14px;padding:12px 14px;margin-bottom:10px}
.mv-details summary{cursor:pointer;font-weight:800;color:var(--ink,#f8fafc);font-size:14px;
  min-height:28px;display:flex;align-items:center;gap:8px;list-style:none}
.mv-details summary::-webkit-details-marker{display:none}
.mv-details summary::before{content:'▸';color:#64748b;transition:transform .15s}
.mv-details[open] summary::before{transform:rotate(90deg)}
.mv-count{background:rgba(59,130,246,.16);color:#93c5fd;border-radius:999px;
  padding:2px 9px;font-size:12px;font-weight:800}
.mv-warn{color:#fca5a5;font-weight:700;margin:10px 0 0;font-size:13px}
.mv-collapsed .mv-more{display:none !important}
.mv-toggle{width:100%;text-align:center}
@media(max-width:640px){
  .mv-wrap .panel{padding:13px}
  .mv-flabel{flex:0 0 100%}
  .mv-nums{font-size:15px}
}
</style>
"""

_FILTER_JS = """
<script>
(function () {
  var state = { market: "all", reason: "all" };
  function apply() {
    document.querySelectorAll(".mv-card").forEach(function (c) {
      var okM = state.market === "all" || c.dataset.market === state.market;
      var okR = state.reason === "all" || c.dataset.reason === state.reason;
      c.style.display = (okM && okR) ? "" : "none";
    });
    document.querySelectorAll(".mv-section[data-market-section]").forEach(function (s) {
      var okM = state.market === "all" || s.dataset.marketSection === state.market;
      s.style.display = okM ? "" : "none";
      var any = Array.prototype.some.call(
        s.querySelectorAll(".mv-card"), function (c) { return c.style.display !== "none"; });
      var e = s.querySelector(".mv-noneleft");
      if (e) e.style.display = any ? "none" : "";
    });
  }
  document.querySelectorAll(".mv-fbtn[data-fgroup]").forEach(function (b) {
    b.addEventListener("click", function () {
      state[b.dataset.fgroup] = b.dataset.fval;
      document.querySelectorAll(".mv-fbtn[data-fgroup='" + b.dataset.fgroup + "']")
        .forEach(function (x) { x.classList.remove("active"); });
      b.classList.add("active");
      if (state.market !== "all" || state.reason !== "all") {
        // filters operate on the full set — auto-expand collapsed sections
        document.querySelectorAll(".mv-section.mv-collapsed").forEach(function (s) {
          s.classList.remove("mv-collapsed");
          var t = s.querySelector(".mv-toggle");
          if (t) t.textContent = t.dataset.less;
        });
      }
      apply();
    });
  });
  document.querySelectorAll(".mv-toggle").forEach(function (t) {
    t.addEventListener("click", function () {
      var s = t.closest(".mv-section");
      var collapsed = s.classList.toggle("mv-collapsed");
      t.textContent = collapsed ? t.dataset.more : t.dataset.less;
    });
  });
  apply();
})();
</script>
"""


def build_body() -> str:
    """Full page body. Never raises; every failure path is a friendly panel."""
    try:
        payload = _load_payload()
        if not payload:
            return ("<section class='panel'><div class='panel-head'><div>"
                    "<div class='eyebrow'>Biggest Movers</div><h2>No movers yet today</h2></div></div>"
                    "<p class='st-prose' style='color:#94a3b8'>Today's movers appear after the first "
                    "afternoon refresh compares against the morning baseline. Check back after the "
                    "next pipeline run.</p></section>")

        meta = payload.get("meta") or {}
        diagnostics = payload.get("diagnostics") or {}
        sections = payload.get("sections") or {}
        reason_mix = payload.get("reason_mix") or {}
        latest_ts = str(meta.get("latest_ts") or "")
        updated_short = _fmt_et_short(latest_ts)
        refresh_label = str(meta.get("latest_refresh_type") or "—").replace("_", " ").title()

        # 1) compact summary strip + explanatory copy
        baseline_ts = str(meta.get("baseline_ts") or "")
        baseline_title = f"{_fmt_ts_full(baseline_ts)} ({meta.get('baseline_type') or ''})"
        strip = (
            "<div class='mv-strip'>"
            f"<span title='{escape(_fmt_ts_full(latest_ts))}'>🕒 Updated: <b>{escape(updated_short)}</b></span>"
            f"<span>📸 Snapshots: <b>{escape(str(meta.get('snapshot_count') or '—'))}</b></span>"
            f"<span>🔄 Refresh: <b>{escape(refresh_label)}</b></span>"
            f"<span title='{escape(baseline_title)}'>"
            f"📅 Baseline: <b>{escape(_fmt_et_short(baseline_ts))}</b></span>"
            f"<span>📆 Slate: <b>{escape(str(meta.get('slate_date') or '—'))}</b></span>"
            "</div>"
        )
        integrity = int(diagnostics.get("frozen_changed_rows") or 0)
        integrity_html = (f"<p class='mv-warn'>⚠ Frozen-game integrity: {integrity} started-game rows "
                          "changed — investigate before trusting deltas.</p>") if integrity else ""
        header = ("<section class='panel'><div class='panel-head'><div>"
                  "<div class='eyebrow'>Internal Preview</div><h2>MLB Biggest Movers</h2></div></div>"
                  "<p class='mv-copy'>Probabilities move throughout the day as lineups, weather, and "
                  "starting pitchers change. Everything below reads the published movers artifact — "
                  "no model access, no recalculation.</p>"
                  + strip + integrity_html + "</section>")

        # 2) hero — today's biggest moves
        def top1(key):
            lst = sections.get(key) or []
            return lst[0] if lst else None
        hero = ("<div class='mv-hero'>"
                + _hero_card("🔥", "Biggest HR Move", top1("hr_prob"), "probability")
                + _hero_card("⚾", "Biggest Hit Move", top1("hit_prob"), "probability")
                + _hero_card("🎯", "Biggest Pitcher Move", top1("proj_pitcher_k"), "projection")
                + "</div>")

        # 3) reason summary near the top
        mix_html = _reason_summary(reason_mix)

        # 4) sticky filters
        tags_present = sorted(reason_mix.keys(), key=lambda t: -reason_mix[t])

        def btn(label, group, value, active=False):
            cls = "mv-fbtn active" if active else "mv-fbtn"
            return (f"<button class='{cls}' data-fgroup='{group}' data-fval='{escape(value)}'>"
                    f"{escape(label)}</button>")
        filters = (
            "<div class='mv-sticky'>"
            "<div class='mv-frow'><span class='mv-flabel'>Market</span>"
            + btn("All", "market", "all", True) + btn("HR", "market", "hr_prob")
            + btn("Hits", "market", "hit_prob") + btn("Pitchers", "market", "proj_pitcher_k")
            + "</div>"
            "<div class='mv-frow'><span class='mv-flabel'>Reason</span>"
            + btn("All reasons", "reason", "all", True)
            + "".join(btn(_TAG_DISPLAY.get(t, t), "reason", t) for t in tags_present)
            + "</div></div>"
        )

        # 5) mover sections
        k8_by_pid = {str(m.get("player_id") or ""): m for m in sections.get("pitcher_k_8plus") or []}
        body_sections = []
        for market_key, title, sub in _SECTION_DEFS:
            movers = sections.get(market_key) or []
            collapsed = len(movers) > 5
            if movers:
                cards = "".join(
                    _mover_card(m, market_key, updated_short, k8_by_pid)
                    .replace("class='mv-card'", "class='mv-card mv-more'" if i >= 5 else "class='mv-card'", 1)
                    for i, m in enumerate(movers))
                toggle = (f"<button class='mv-fbtn mv-toggle' data-more='Show all {len(movers)} ▾'"
                          f" data-less='Show top 5 ▴' style='margin-top:10px'>Show all {len(movers)} ▾</button>"
                          if collapsed else "")
                inner = (f"<div class='mv-grid'>{cards}</div>" + toggle +
                         "<p class='mv-noneleft muted' style='display:none;margin-top:10px'>"
                         "No movers match the current filters.</p>")
            else:
                inner = "<p class='muted' style='margin-top:10px'>No qualifying movers in this market yet.</p>"
            cls = "panel mv-section mv-collapsed" if collapsed else "panel mv-section"
            body_sections.append(
                f"<section class='{cls}' data-market-section='{escape(market_key)}'>"
                "<div class='panel-head'><div>"
                f"<div class='eyebrow'>Biggest Movers</div><h2>{escape(title)}</h2></div>"
                f"<p class='muted' style='margin:0;font-size:12px'>{escape(sub)}</p></div>"
                + inner + "</section>")

        # 6) collapsible new / dropped
        new_names = diagnostics.get("new_players") or []
        dropped_names = diagnostics.get("dropped_players") or []
        extras = (
            _names_details("New Players", int(diagnostics.get("new_player_count") or 0), new_names,
                           "No players added since the morning baseline.")
            + _names_details("Dropped Players", int(diagnostics.get("dropped_player_count") or 0),
                             dropped_names, "No players dropped since the morning baseline.",
                             note="Usually bench players removed when lineups confirm.")
        )

        note = ("<p class='muted' style='font-size:12px;margin-top:8px'>Internal preview — admin-only, "
                "noindex. Values are the published board's own numbers; \"Unattributed\" means no "
                "attribution rule matched, never a guess.</p>")

        return ("<div class='mv-wrap'>" + _STYLE + header + hero + mix_html + filters
                + "".join(body_sections) + extras + note + "</div>" + _FILTER_JS)
    except Exception:
        return ("<section class='panel'><div class='panel-head'><div>"
                "<div class='eyebrow'>Biggest Movers</div><h2>Temporarily unavailable</h2></div></div>"
                "<p class='st-prose' style='color:#94a3b8'>The movers artifact could not be rendered. "
                "The data pipeline is unaffected.</p></section>")
