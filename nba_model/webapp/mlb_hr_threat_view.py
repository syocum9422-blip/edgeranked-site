"""MLB Home Run Threats — read-only API and page (production V2 board)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from flask import jsonify

HR_THREAT_PUBLIC_JSON = Path(
    "/home/ubuntu/mlb_model/hr_threat/outputs/hr_threats_public_safe.json"
)

# Additive "Under the Radar" board (separate source; never modifies the board above).
UTR_PUBLIC_JSON = Path(
    "/home/ubuntu/mlb_model/hr_threat/outputs/under_the_radar_hr_threats_public_safe.json"
)
UTR_DISPLAY_LIMIT = 20
UTR_DESCRIPTION = (
    "These hitters are receiving a stronger-than-normal home run outlook today "
    "due to favorable matchup, weather, stadium, and pitcher conditions. Players "
    "on this board meet minimum power thresholds and are not already featured "
    "among today’s top Home Run Threats."
)

# Display-only cap for the HTML page (API returns full board).
PAGE_DISPLAY_LIMIT = 30

TEAM_ABBREV = {
    "Arizona Diamondbacks": "ARI",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Athletics": "ATH",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",
    "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}


def load_hr_threats():
    """Read published public-safe HR Threat JSON. Never runs the engine."""
    if not HR_THREAT_PUBLIC_JSON.is_file():
        return {
            "status": "unavailable",
            "reason": "hr_threats_unavailable",
            "generated_at": None,
            "slate_date": None,
            "count": 0,
            "players": [],
        }
    try:
        with HR_THREAT_PUBLIC_JSON.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {
            "status": "unavailable",
            "reason": "hr_threats_unavailable",
            "generated_at": None,
            "slate_date": None,
            "count": 0,
            "players": [],
        }

    meta = payload.get("meta") if isinstance(payload, dict) else {}
    threats = payload.get("threats") if isinstance(payload, dict) else []
    if not isinstance(threats, list) or not threats:
        return {
            "status": "unavailable",
            "reason": "hr_threats_unavailable",
            "generated_at": meta.get("generated_at"),
            "slate_date": meta.get("slate_date"),
            "count": 0,
            "players": [],
        }

    players = []
    for row in threats:
        if not isinstance(row, dict):
            continue
        name = (row.get("player_name") or "").strip()
        if not name:
            continue
        players.append(
            {
                "player_name": name,
                "team": row.get("team") or "",
                "opponent": row.get("opponent") or "",
                "probable_pitcher": row.get("probable_pitcher") or "",
                "hr_threat_score": row.get("hr_threat_score"),
                "threat_tier": row.get("threat_tier") or "",
                "confidence": row.get("confidence") or "",
                "drivers": row.get("drivers") or "",
                "availability_status": row.get("availability_status") or "",
                "availability_risk": row.get("availability_risk") or "",
                "data_status": row.get("data_status") or meta.get("data_status") or "",
            }
        )

    players.sort(
        key=lambda p: float(p.get("hr_threat_score") or 0),
        reverse=True,
    )
    return {
        "status": "ok",
        "generated_at": meta.get("generated_at"),
        "slate_date": meta.get("slate_date"),
        "count": len(players),
        "players": players,
    }


def load_under_the_radar():
    """Read the published Under-the-Radar public-safe JSON. Fail closed.

    Never runs any engine. Returns at most UTR_DISPLAY_LIMIT players. Any
    missing/invalid/empty source yields status != 'ok' so the caller renders a
    safe (locked/unavailable) section instead of leaking or erroring."""
    unavailable = {
        "status": "unavailable",
        "reason": "under_the_radar_unavailable",
        "generated_at": None,
        "slate_date": None,
        "count": 0,
        "players": [],
    }
    if not UTR_PUBLIC_JSON.is_file():
        return unavailable
    try:
        with UTR_PUBLIC_JSON.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return unavailable
    if not isinstance(payload, dict):
        return unavailable

    meta = payload.get("meta") or {}
    rows = payload.get("under_the_radar_hr_threats")
    if not isinstance(rows, list) or not rows:
        return {**unavailable, "generated_at": meta.get("generated_at"),
                "slate_date": meta.get("slate_date")}

    players = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = (row.get("player_name") or "").strip()
        if not name:
            continue
        players.append(
            {
                "rank": row.get("rank"),
                "player_name": name,
                "team": row.get("team") or "",
                "opponent": row.get("opponent") or "",
                "probable_pitcher": row.get("probable_pitcher") or "",
                "hr_boost_score": row.get("hr_boost_score"),
                "power_skill_score": row.get("power_skill_score"),
                "hr_environment_score": row.get("hr_environment_score"),
                "confidence": row.get("confidence") or "",
                "drivers": row.get("drivers") or "",
            }
        )
    if not players:
        return {**unavailable, "generated_at": meta.get("generated_at"),
                "slate_date": meta.get("slate_date")}

    # Preserve source rank order; hard cap at the display limit.
    players.sort(key=lambda p: float(p.get("rank") or 1e9))
    players = players[:UTR_DISPLAY_LIMIT]
    return {
        "status": "ok",
        "generated_at": meta.get("generated_at"),
        "slate_date": meta.get("slate_date"),
        "count": len(players),
        "players": players,
    }


def _team_abbrev(team: str) -> str:
    name = (team or "").strip()
    if not name:
        return ""
    return TEAM_ABBREV.get(name, name[:3].upper())


def _matchup_line(team: str, opponent: str) -> str:
    t = _team_abbrev(team)
    o = _team_abbrev(opponent)
    if t and o:
        return f"{t} vs {o}"
    return t or o or ""


def _format_updated_at(raw: str | None) -> str:
    if not raw:
        return ""
    text = str(raw).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        time_label = dt.strftime("%I:%M %p").lstrip("0").replace(" 0", " ")
        return f"Updated {dt.strftime('%b')} {dt.day}, {dt.year} · {time_label} UTC"
    except (ValueError, TypeError):
        return f"Updated {text[:19]} UTC"


def _parse_driver_chips(drivers: str) -> list[str]:
    text = (drivers or "").strip()
    if not text:
        return []
    parts = re.split(r"\s*\|\s*", text)
    return [p.strip() for p in parts if p.strip()]


def _risk_badges(availability_risk: str) -> list[str]:
    risk = (availability_risk or "").strip()
    if not risk:
        return []
    badges = []
    lower = risk.lower()
    if any(tok in lower for tok in ("day-to-day", "day to day", "dtd")):
        badges.append("Day-to-Day")
    if "questionable" in lower:
        badges.append("Questionable")
    if "recently activated" in lower or "activated" in lower:
        badges.append("Recently Activated")
    if "limited" in lower:
        badges.append("Expected Limited Usage")
    if risk and not badges:
        badges.append("Availability Risk")
    return badges


def _render_chips(labels: list[str], *, max_chips: int | None = None, chip_class: str = "hr-threat-chip") -> str:
    shown = labels[:max_chips] if max_chips else labels
    html = "".join(
        f"<span class='{chip_class}'>{escape(label)}</span>" for label in shown
    )
    if max_chips and len(labels) > max_chips:
        html += f"<span class='{chip_class} hr-threat-chip-more'>+{len(labels) - max_chips} more</span>"
    return html


def _render_risk_badges(risks: list[str]) -> str:
    if not risks:
        return ""
    return (
        "<div class='hr-threat-risks'>"
        + "".join(f"<span class='hr-threat-risk'>{escape(r)}</span>" for r in risks)
        + "</div>"
    )


def _render_mobile_card(rank: int, player: dict) -> str:
    chips = _parse_driver_chips(player.get("drivers") or "")
    risks = _risk_badges(player.get("availability_risk") or "")
    score = escape(str(player.get("hr_threat_score") or ""))
    tier = escape(player.get("threat_tier") or "")
    conf = escape(player.get("confidence") or "")
    pitcher = escape(player.get("probable_pitcher") or "—")
    return (
        "<article class='hr-threat-card'>"
        f"<div class='hr-threat-card-top'>"
        f"<span class='hr-threat-rank'>#{rank}</span>"
        f"<strong class='hr-threat-name'>{escape(player.get('player_name') or '')}</strong>"
        f"</div>"
        f"<div class='hr-threat-matchup'>{escape(_matchup_line(player.get('team'), player.get('opponent')))}</div>"
        f"<div class='hr-threat-pitcher'><span class='hr-threat-label'>Probable Pitcher:</span> {pitcher}</div>"
        f"<div class='hr-threat-metrics'>"
        f"Score <strong>{score}</strong> · Tier <strong>{tier}</strong> · "
        f"Confidence <strong>{conf}</strong>"
        f"</div>"
        f"{_render_risk_badges(risks)}"
        f"<div class='hr-threat-drivers'>{_render_chips(chips)}</div>"
        "</article>"
    )


def _render_desktop_row(rank: int, player: dict) -> str:
    chips = _parse_driver_chips(player.get("drivers") or "")
    risks = _risk_badges(player.get("availability_risk") or "")
    risk_html = _render_risk_badges(risks) if risks else ""
    return (
        "<tr>"
        f"<td>{rank}</td>"
        f"<td><strong>{escape(player.get('player_name') or '')}</strong>{risk_html}</td>"
        f"<td>{escape(_team_abbrev(player.get('team')))}</td>"
        f"<td>{escape(_team_abbrev(player.get('opponent')))}</td>"
        f"<td>{escape(player.get('probable_pitcher') or '')}</td>"
        f"<td>{escape(str(player.get('hr_threat_score') or ''))}</td>"
        f"<td>{escape(player.get('threat_tier') or '')}</td>"
        f"<td>{escape(player.get('confidence') or '')}</td>"
        f"<td class='hr-threat-drivers-cell'>{_render_chips(chips, max_chips=3)}</td>"
        "</tr>"
    )


def _render_utr_mobile_card(player: dict) -> str:
    chips = _parse_driver_chips(player.get("drivers") or "")
    rank = escape(str(player.get("rank") or ""))
    boost = escape(str(player.get("hr_boost_score") or ""))
    power = escape(str(player.get("power_skill_score") or ""))
    env = escape(str(player.get("hr_environment_score") or ""))
    conf = escape(player.get("confidence") or "")
    pitcher = escape(player.get("probable_pitcher") or "—")
    return (
        "<article class='hr-threat-card utr-card'>"
        f"<div class='hr-threat-card-top'>"
        f"<span class='hr-threat-rank'>#{rank}</span>"
        f"<strong class='hr-threat-name'>{escape(player.get('player_name') or '')}</strong>"
        f"</div>"
        f"<div class='hr-threat-matchup'>{escape(_matchup_line(player.get('team'), player.get('opponent')))}</div>"
        f"<div class='hr-threat-pitcher'><span class='hr-threat-label'>Probable Pitcher:</span> {pitcher}</div>"
        f"<div class='hr-threat-metrics'>"
        f"HR Boost <strong>{boost}</strong> · Power Skill <strong>{power}</strong> · "
        f"HR Env <strong>{env}</strong> · Confidence <strong>{conf}</strong>"
        f"</div>"
        f"<div class='hr-threat-drivers'>{_render_chips(chips, chip_class='utr-chip')}</div>"
        "</article>"
    )


def _render_utr_desktop_row(player: dict) -> str:
    chips = _parse_driver_chips(player.get("drivers") or "")
    return (
        "<tr>"
        f"<td>{escape(str(player.get('rank') or ''))}</td>"
        f"<td><strong>{escape(player.get('player_name') or '')}</strong></td>"
        f"<td>{escape(_team_abbrev(player.get('team')))}</td>"
        f"<td>{escape(_team_abbrev(player.get('opponent')))}</td>"
        f"<td>{escape(player.get('probable_pitcher') or '')}</td>"
        f"<td>{escape(str(player.get('hr_boost_score') or ''))}</td>"
        f"<td>{escape(str(player.get('power_skill_score') or ''))}</td>"
        f"<td>{escape(str(player.get('hr_environment_score') or ''))}</td>"
        f"<td>{escape(player.get('confidence') or '')}</td>"
        f"<td class='hr-threat-drivers-cell'>{_render_chips(chips, max_chips=3, chip_class='utr-chip')}</td>"
        "</tr>"
    )


# Accent styling so the section is clearly distinct from the main board. Reuses
# the existing hr-threat-* classes for an identical, mobile-friendly layout.
UTR_SECTION_STYLES = """
<style>
  .utr-board { border-left: 3px solid rgba(16, 185, 129, 0.65); }
  .utr-board .eyebrow { color: #34d399; }
  .utr-section-desc {
    margin: 2px 0 14px;
    color: var(--text-muted);
    font-size: 14px;
    line-height: 1.5;
    max-width: 70ch;
  }
  .utr-chip {
    display: inline-block;
    font-size: 11px;
    line-height: 1.3;
    padding: 4px 8px;
    border-radius: 999px;
    background: rgba(16, 185, 129, 0.12);
    border: 1px solid rgba(16, 185, 129, 0.30);
    color: #a7f3d0;
    white-space: normal;
  }
</style>
"""


def _render_under_the_radar_section(data: dict) -> str:
    """Build the additive Under-the-Radar section. Always returns safe HTML;
    fails closed to an 'unavailable' note rather than raising."""
    try:
        header = (
            "<div class='panel-head'>"
            "<div><div class='eyebrow'>MLB · Projection-First</div>"
            "<h2>Under the Radar Home Run Threats</h2></div>"
            "</div>"
            f"<p class='utr-section-desc'>{escape(UTR_DESCRIPTION)}</p>"
        )
        if data.get("status") != "ok" or not data.get("players"):
            return (
                "<section class='panel hr-threat-board utr-board'>"
                f"{UTR_SECTION_STYLES}{header}"
                "<p class='muted'>Today’s Under the Radar board has not been "
                "published yet, or its source failed validation. Check back after "
                "the morning MLB pipeline run.</p>"
                "</section>"
            )
        players = data["players"][:UTR_DISPLAY_LIMIT]
        mobile = "".join(_render_utr_mobile_card(p) for p in players)
        rows = "".join(_render_utr_desktop_row(p) for p in players)
        return (
            "<section class='panel hr-threat-board utr-board'>"
            f"{UTR_SECTION_STYLES}{header}"
            f"<div class='hr-threat-cards'>{mobile}</div>"
            "<div class='hr-threat-desktop'>"
            "<table class='hr-threat-table'>"
            "<thead><tr>"
            "<th>Rank</th><th>Player</th><th>Team</th><th>Opponent</th>"
            "<th>Pitcher</th><th>HR Boost</th><th>Power Skill</th>"
            "<th>HR Env</th><th>Confidence</th><th>Drivers</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody>"
            "</table></div>"
            "</section>"
        )
    except Exception:
        # Fail closed — never break the page because of the additive section.
        return (
            "<section class='panel hr-threat-board utr-board'>"
            "<div class='panel-head'><div><div class='eyebrow'>MLB · Projection-First</div>"
            "<h2>Under the Radar Home Run Threats</h2></div></div>"
            "<p class='muted'>Under the Radar board temporarily unavailable.</p>"
            "</section>"
        )


HR_THREAT_PAGE_STYLES = """
<style>
  .hr-threat-board .hr-threat-meta {
    margin: 0 0 14px;
    color: var(--text-muted);
    font-size: 14px;
  }
  .hr-threat-cards {
    display: none;
    gap: 10px;
  }
  .hr-threat-desktop {
    overflow-x: auto;
  }
  .hr-threat-card {
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 12px 14px;
    background: rgba(255, 255, 255, 0.02);
  }
  .hr-threat-card-top {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 4px;
  }
  .hr-threat-rank {
    color: var(--text-muted);
    font-size: 13px;
    font-weight: 800;
    flex: 0 0 auto;
  }
  .hr-threat-name {
    font-size: 16px;
    line-height: 1.2;
  }
  .hr-threat-matchup {
    color: var(--text-muted);
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 6px;
  }
  .hr-threat-pitcher {
    font-size: 13px;
    margin-bottom: 6px;
    color: var(--text);
  }
  .hr-threat-label {
    color: var(--text-muted);
  }
  .hr-threat-metrics {
    font-size: 13px;
    color: var(--text-muted);
    margin-bottom: 8px;
  }
  .hr-threat-metrics strong {
    color: var(--text);
  }
  .hr-threat-risks {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 8px;
  }
  .hr-threat-risk {
    font-size: 11px;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 999px;
    background: rgba(245, 158, 11, 0.14);
    border: 1px solid rgba(245, 158, 11, 0.35);
    color: #fcd34d;
  }
  .hr-threat-drivers,
  .hr-threat-drivers-cell {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: flex-start;
  }
  .hr-threat-chip {
    display: inline-block;
    font-size: 11px;
    line-height: 1.3;
    padding: 4px 8px;
    border-radius: 999px;
    background: rgba(59, 130, 246, 0.12);
    border: 1px solid rgba(59, 130, 246, 0.28);
    color: #bfdbfe;
    white-space: normal;
  }
  .hr-threat-chip-more {
    background: rgba(255, 255, 255, 0.06);
    border-color: var(--border);
    color: var(--text-muted);
  }
  .hr-threat-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  .hr-threat-table th {
    text-align: left;
    padding: 10px 12px;
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    border-bottom: 1px solid var(--border);
  }
  .hr-threat-table td {
    padding: 12px;
    border-bottom: 1px solid rgba(35, 37, 46, 0.8);
    vertical-align: top;
  }
  .hr-threat-table tbody tr:hover {
    background: rgba(59, 130, 246, 0.05);
  }
  @media (max-width: 720px) {
    .hr-threat-cards {
      display: grid;
    }
    .hr-threat-desktop {
      display: none;
    }
  }
</style>
"""


def register_mlb_hr_threat_routes(
    flask_app,
    render_layout,
    render_mlb_nav,
    render_banner,
    json_ready,
    mlb_premium_wrap=None,
):
    description = (
        "Home Run Threats are generated from a dedicated power-ranking engine that "
        "evaluates batter power, recent form, matchup quality, park factors, pitcher "
        "home-run tendencies, and player availability. This board is separate from the "
        "EdgeRanked simulation engine."
    )

    def _wrap_body(body_html: str) -> str:
        if mlb_premium_wrap:
            return mlb_premium_wrap(body_html)
        return body_html

    @flask_app.get("/api/mlb/home-run-threats")
    def mlb_hr_threats_api():
        return jsonify(json_ready(load_hr_threats()))

    @flask_app.get("/mlb/home-run-threats")
    def mlb_hr_threats_page():
        data = load_hr_threats()
        title = "MLB Home Run Threats"
        subtitle = description
        nav = render_mlb_nav("/mlb/home-run-threats")

        meta_bits = []
        if data.get("slate_date"):
            meta_bits.append(f"Slate {escape(str(data['slate_date']))}")
        updated = _format_updated_at(data.get("generated_at"))
        if updated:
            meta_bits.append(escape(updated))
        meta_html = (
            f"<p class='hr-threat-meta muted'>{' · '.join(meta_bits)}</p>"
            if meta_bits
            else ""
        )

        if data.get("status") != "ok" or not data.get("players"):
            body = (
                render_banner("")
                + "<section class='panel'>"
                "<h2>Home Run Threats unavailable</h2>"
                "<p class='muted'>Today's board has not been published yet, or availability "
                "sources failed validation. Check back after the morning MLB pipeline run.</p>"
                f"{meta_html}"
                "</section>"
            )
            return render_layout(
                title, subtitle, _wrap_body(body), "/mlb/home-run-threats", nav
            )

        display_players = data["players"][:PAGE_DISPLAY_LIMIT]
        mobile_cards = "".join(
            _render_mobile_card(rank, p)
            for rank, p in enumerate(display_players, 1)
        )
        desktop_rows = "".join(
            _render_desktop_row(rank, p)
            for rank, p in enumerate(display_players, 1)
        )

        board = (
            "<section class='panel hr-threat-board'>"
            "<div class='panel-head'>"
            "<div><div class='eyebrow'>MLB</div><h2>Home Run Threat Board</h2></div>"
            "<p class='muted'>Top 30 players ranked by HR Threat Score.</p>"
            "</div>"
            f"{meta_html}"
            f"{HR_THREAT_PAGE_STYLES}"
            f"<div class='hr-threat-cards'>{mobile_cards}</div>"
            "<div class='hr-threat-desktop'>"
            "<table class='hr-threat-table'>"
            "<thead><tr>"
            "<th>Rank</th><th>Player</th><th>Team</th><th>Opponent</th>"
            "<th>Pitcher</th><th>Score</th><th>Tier</th><th>Confidence</th><th>Drivers</th>"
            "</tr></thead>"
            f"<tbody>{desktop_rows}</tbody>"
            "</table></div>"
            "</section>"
        )
        # Additive Under-the-Radar section beneath the main board. Wrapped in the
        # same premium body, so premium-gated access is preserved unchanged.
        utr_section = _render_under_the_radar_section(load_under_the_radar())
        body = render_banner("") + board + utr_section
        return render_layout(
            title, subtitle, _wrap_body(body), "/mlb/home-run-threats", nav
        )
