"""Soccer/EPL simulation product views for EdgeRanked AI.

Route architecture (future-proofed for UCL expansion):
  /soccer          — sport overview (EPL live, UCL planned internally)
  /soccer/epl      — EPL match simulation page
  /api/soccer/epl/simulations  — EPL simulation JSON payload

League nav items are managed via SOCCER_NAV_ITEMS.
When UCL is ready, add ("UCL", "/soccer/ucl") to SOCCER_NAV_ITEMS
and register matching route + data pipeline.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from html import escape
from pathlib import Path

from flask import jsonify

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPORTS_ROOT = PROJECT_ROOT.parent / "sports"
EPL_OUTPUT_DIR = Path(
    os.environ.get(
        "EDGERANKED_EPL_OUTPUT_DIR",
        SPORTS_ROOT / "soccor_Model" / "sports" / "epl" / "outputs",
    )
)

EPL_MATCH_PATH = EPL_OUTPUT_DIR / "epl_match_simulations_today.json"
EPL_PLAYER_PATH = EPL_OUTPUT_DIR / "epl_player_shots_today.json"
EPL_LINEUP_PATH = EPL_OUTPUT_DIR / "epl_projected_lineups_today.json"
EPL_PRODUCT_REPORT_PATH = EPL_OUTPUT_DIR / "epl_product_readiness_report.txt"
EPL_PUBLIC_AUDIT_PATH = EPL_OUTPUT_DIR / "epl_public_realism_audit.txt"

SOCCER_NAV_ITEMS = [("Overview", "/soccer"), ("EPL", "/soccer/epl")]
# Future UCL nav: SOCCER_NAV_ITEMS = [("Overview", "/soccer"), ("EPL", "/soccer/epl"), ("UCL", "/soccer/ucl")]
FORBIDDEN_PUBLIC_TERMS = re.compile(
    r"\b(bet|odds|lines|edge|edges|book|books|price|prices|moneyline|spread|spreads|total|totals|pick|picks|parlay|parlays|wager|wagers|wagering)\b",
    re.IGNORECASE,
)


def register_soccer_routes(flask_app, render_layout, render_subnav, json_ready):
    def soccer_nav(active_path: str) -> str:
        return render_subnav(SOCCER_NAV_ITEMS, active_path)

    @flask_app.get("/soccer")
    def soccer_home():
        return build_soccer_home(render_layout, soccer_nav)

    @flask_app.get("/soccer/epl")
    def soccer_epl_page():
        return build_epl_page(render_layout, soccer_nav)

    @flask_app.get("/api/soccer/epl/simulations")
    def soccer_epl_api():
        payload = load_epl_site_payload()
        response = jsonify(json_ready(payload))
        response.headers["X-EdgeRank-Scope"] = "simulation-projections"
        return response


def load_epl_site_payload() -> dict[str, object]:
    matches = _read_json_records(EPL_MATCH_PATH)
    players = _read_json_records(EPL_PLAYER_PATH)
    lineups = _read_json_records(EPL_LINEUP_PATH)
    product_report = _read_text(EPL_PRODUCT_REPORT_PATH)
    realism_report = _read_text(EPL_PUBLIC_AUDIT_PATH)
    product_status = _extract_report_value(product_report, "product status") or "FAIL"
    realism_status = _extract_realism_status(realism_report)
    fallback_teams = _extract_report_value(product_report, "fallback roster teams") or "unknown"
    is_full_public = product_status == "PASS" and realism_status == "PUBLIC_READY"
    state = "full" if is_full_public else "limited" if product_status == "WARN" else "updating"

    player_index = _players_by_match_team(players)
    lineup_index = _lineups_by_match_team(lineups)
    enriched_matches = []
    for match in matches:
        home_team = str(match.get("home_team") or "")
        away_team = str(match.get("away_team") or "")
        match_id = str(match.get("match_id") or "")
        enriched = {
            **match,
            "home_top_player_shots": player_index.get((match_id, home_team), [])[:5],
            "away_top_player_shots": player_index.get((match_id, away_team), [])[:5],
            "home_projected_lineup": lineup_index.get((match_id, home_team), [])[:11],
            "away_projected_lineup": lineup_index.get((match_id, away_team), [])[:11],
            "projected_starters_note": _projected_starters_note(match, fallback_teams),
        }
        enriched_matches.append(enriched)

    payload = {
        "sport": "soccer",
        "league": "EPL",
        "title": "EPL Match Projections",
        "product_status": product_status,
        "status_label": "Live" if is_full_public else "Refresh in progress",
        "display_state": state,
        "match_count": len(enriched_matches),
        "matches": enriched_matches,
        "lineups_by_match_team": _lineup_payload(lineup_index),
        "updated_at": _latest_timestamp([EPL_MATCH_PATH, EPL_PLAYER_PATH, EPL_LINEUP_PATH, EPL_PRODUCT_REPORT_PATH, EPL_PUBLIC_AUDIT_PATH]),
    }
    _assert_clean_public_payload(payload)
    return payload


def build_soccer_home(render_layout, soccer_nav) -> str:
    payload = load_epl_site_payload()
    state = payload["display_state"]
    status_text = "Live" if state == "full" else "Refreshing"
    updated = payload.get("updated_at")
    updated_display = _format_timestamp_soccer(updated) if updated else "awaiting refresh"
    body = f"""
    <style>{_epl_css()}</style>
    <section class="soccer-overview">
      <div class="soccer-product-copy">
        <div class="eyebrow">Soccer</div>
        <h2>Today’s EPL projections</h2>
        <p class="muted">Match projections, goal outlooks, and player shot leaders for today’s slate.</p>
        <p class="last-updated">Updated: {escape(updated_display)}</p>
      </div>
      <div class="soccer-status-card">
        <span>{escape(status_text)}</span>
        <strong>{escape(str(payload.get('match_count', 0)))} matches</strong>
        <p>Match Projections</p>
        <a class="soccer-action" href="/soccer/epl">Open EPL</a>
      </div>
    </section>
    """
    return _sanitize_soccer_html(
        render_layout(
            "Soccer",
            "Today’s EPL match projections and player shot leaders.",
            body,
            "/soccer",
            soccer_nav("/soccer"),
            hero_kicker="Soccer",
        )
    )


def build_epl_page(render_layout, soccer_nav) -> str:
    payload = load_epl_site_payload()
    state = payload["display_state"]
    updated = payload.get("updated_at")
    updated_display = _format_timestamp_soccer(updated) if updated else "awaiting refresh"
    if state != "full" and not payload.get("matches"):
        body = f"""
        <style>{_epl_css()}</style>
        <section class="epl-state-panel">
          <div class="eyebrow">EPL</div>
          <h2>Today’s EPL projections</h2>
          <p class="muted">Match projections are refreshing now.</p>
          <p class="last-updated">Updated: {escape(updated_display)}</p>
        </section>
        """
    else:
        body = f"""
        <style>{_epl_css()}</style>
        <section class="epl-summary-band">
          <div>
            <div class="eyebrow">EPL</div>
            <h2>Today’s EPL projections</h2>
            <p class="muted">Win, draw, goal, and player shot outlooks for the current slate.</p>
            <p class="last-updated">Updated: {escape(updated_display)}</p>
          </div>
        </section>
        <section class="epl-match-grid">
          {''.join(_render_match_card(match, updated) for match in payload.get('matches', []))}
        </section>
        """
    return _sanitize_soccer_html(
        render_layout(
            "EPL Match Projections",
            "Match projections, goal outlooks, and player shot leaders.",
            body,
            "/soccer/epl",
            soccer_nav("/soccer/epl"),
            hero_kicker="Soccer / EPL",
        )
    )


def _sanitize_soccer_html(html: str) -> str:
    replacements = {
        "pricing-price": "access-cost",
        "pricing-": "access-",
        "pricing_": "access_",
        "pricing": "access",
        "Pricing": "Access",
        "Price": "Cost",
        "price": "cost",
        "/access": "/membership",
    }
    for source, target in replacements.items():
        html = html.replace(source, target)
    return html


def _render_match_card(match: dict[str, object], updated_at: str | None = None) -> str:
    home = str(match.get("home_team") or "Home")
    away = str(match.get("away_team") or "Away")
    home_goals = _num(match.get("projected_home_goals"), 2)
    away_goals = _num(match.get("projected_away_goals"), 2)
    kickoff = _format_kickoff_time(match.get("kickoff_utc"))
    probs = [
        ("Home", match.get("home_win_prob")),
        ("Draw", match.get("draw_prob")),
        ("Away", match.get("away_win_prob")),
    ]
    return f"""
    <article class="epl-match-card">
      <div class="match-card-top">
        <div class="match-card-header-wrap">
          <span class="match-label">Match Projections</span>
          <div class="matchup-header">
            <div class="matchup-team matchup-home">
              <span class="matchup-side-label">Home</span>
              <span class="matchup-name">{escape(home)}</span>
              <span class="matchup-goals">{escape(home_goals)}</span>
            </div>
            <div class="matchup-vs">vs</div>
            <div class="matchup-team matchup-away">
              <span class="matchup-side-label">Away</span>
              <span class="matchup-name">{escape(away)}</span>
              <span class="matchup-goals">{escape(away_goals)}</span>
            </div>
          </div>
        </div>
        <div class="match-card-meta">
          <div class="confidence-chip">{escape(str(match.get('confidence_tier') or 'Review'))}</div>
          {f'<div class="kickoff-chip">{escape(kickoff)}</div>' if kickoff else ''}
        </div>
      </div>
      <div class="score-row">
        <span class="score-label">Projected Goals</span>
        <strong>{escape(home_goals)} – {escape(away_goals)}</strong>
      </div>
      <div class="prob-grid">{''.join(_prob_cell(label, value) for label, value in probs)}</div>
      <div class="team-grid">
        {_render_team_metrics(home, 'home', match)}
        {_render_team_metrics(away, 'away', match)}
      </div>
      <div class="tempo-row"><span>Match tempo</span><strong>{escape(str(match.get('match_tempo') or 'n/a'))}</strong></div>
      {_render_projected_lineups(home, away, match)}
      <div class="player-section">
        <h4>Player Shot Leaders</h4>
        <div class="player-columns">
          {_render_player_table(home, match.get('home_top_player_shots') or [])}
          {_render_player_table(away, match.get('away_top_player_shots') or [])}
        </div>
      </div>
    </article>
    """


def _render_projected_lineups(home: str, away: str, match: dict[str, object]) -> str:
    return f"""
      <div class="projected-lineups">
        <div class="lineup-head">
          <span>Projected Lineups</span>
          <strong>Expected XI · Minutes</strong>
        </div>
        <div class="lineup-columns">
          {_render_lineup_team(home, match.get('home_projected_lineup') or [])}
          {_render_lineup_team(away, match.get('away_projected_lineup') or [])}
        </div>
      </div>
    """


def _render_lineup_team(team: str, players: list[dict[str, object]]) -> str:
    rows = []
    for player in players[:11]:
        rows.append(
            "<div class='lineup-player'>"
            "<div>"
            f"<strong>{escape(str(player.get('player') or ''))}</strong>"
            f"<span>{escape(str(player.get('position') or ''))}</span>"
            "</div>"
            f"<span class='lineup-minutes'>{escape(_num(player.get('projected_minutes'), 0))} min</span>"
            f"<span class='lineup-source'>{escape(_display_lineup_source(player.get('lineup_source')))}</span>"
            "</div>"
        )
    if not rows:
        rows.append("<div class='lineup-player empty'>Expected XI available soon.</div>")
    return f"""
      <div class="lineup-team">
        <h5>{escape(team)}</h5>
        {''.join(rows)}
      </div>
    """


def _render_team_metrics(team: str, side: str, match: dict[str, object]) -> str:
    rows = [
        ("xG", _num(match.get(f"projected_{side}_goals"), 2)),
        ("Shots", _num(match.get(f"{side}_shots"), 1)),
        ("Shots on target", _num(match.get(f"{side}_shots_on_target"), 1)),
        ("Corners", _num(match.get(f"{side}_corners"), 1)),
    ]
    return f"""
    <div class="team-panel">
      <h4>{escape(team)}</h4>
      {''.join(f'<div class="metric-row"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>' for label, value in rows)}
    </div>
    """


def _render_player_table(team: str, players: list[dict[str, object]]) -> str:
    rows = []
    cards = []
    for player in players[:5]:
        display_name = _shorten_player_name(str(player.get("player") or ""))
        position = str(player.get("position") or "")
        projected_shots = _num(player.get("projected_shots"), 2)
        one_plus = _pct(player.get("shot_1_plus_prob"))
        two_plus = _pct(player.get("shot_2_plus_prob"))
        three_plus = _pct(player.get("shot_3_plus_prob"))
        sot_one_plus = _pct(player.get("sot_1_plus_prob"))
        rows.append(
            "<tr>"
            f"<td><strong>{escape(display_name)}</strong><span>{escape(position)}</span></td>"
            f"<td>{escape(projected_shots)}</td>"
            f"<td>{escape(one_plus)}</td>"
            f"<td>{escape(two_plus)}</td>"
            f"<td>{escape(three_plus)}</td>"
            f"<td>{escape(sot_one_plus)}</td>"
            "</tr>"
        )
        cards.append(
            "<article class='player-shot-card'>"
            "<div class='player-card-head'>"
            f"<strong>{escape(display_name)}</strong>"
            f"<span>{escape(position)}</span>"
            "</div>"
            "<div class='player-shot-main'>"
            "<span>Projected shots</span>"
            f"<strong>{escape(projected_shots)}</strong>"
            "</div>"
            "<div class='player-badge-row'>"
            f"<span>1+ {escape(one_plus)}</span>"
            f"<span>2+ {escape(two_plus)}</span>"
            f"<span>3+ {escape(three_plus)}</span>"
            f"<span>SOT 1+ {escape(sot_one_plus)}</span>"
            "</div>"
            "</article>"
        )
    if not rows:
        rows.append("<tr><td colspan='6'>Player shot leaders available soon.</td></tr>")
        cards.append("<article class='player-shot-card empty'>Player shot leaders available soon.</article>")
    return f"""
    <div class="player-table-wrap">
      <h5>{escape(team)}</h5>
      <table class="player-table">
        <thead><tr><th>Player</th><th>Shots</th><th>1+</th><th>2+</th><th>3+</th><th>SOT&nbsp;1+</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      <div class="player-card-list">{''.join(cards)}</div>
    </div>
    """


def _prob_cell(label: str, value: object) -> str:
    return f"<div><span>{escape(label)}</span><strong>{escape(_pct(value))}</strong></div>"


def _lineups_by_match_team(lineups: list[dict[str, object]]) -> dict[tuple[str, str], list[dict[str, object]]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for player in lineups:
        key = (str(player.get("match_id") or ""), str(player.get("team") or ""))
        grouped.setdefault(key, []).append(player)
    for rows in grouped.values():
        rows.sort(key=lambda row: _float(row.get("lineup_rank")) or 999)
    return grouped


def _lineup_payload(lineup_index: dict[tuple[str, str], list[dict[str, object]]]) -> dict[str, dict[str, list[dict[str, object]]]]:
    payload: dict[str, dict[str, list[dict[str, object]]]] = {}
    for (match_id, team), rows in lineup_index.items():
        payload.setdefault(match_id, {})[team] = rows[:11]
    return payload


def _display_lineup_source(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"probable_starters", "projected", "model", "fallback"}:
        return "Projected"
    return "Projected"


def _players_by_match_team(players: list[dict[str, object]]) -> dict[tuple[str, str], list[dict[str, object]]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for player in players:
        key = (str(player.get("match_id") or ""), str(player.get("team") or ""))
        grouped.setdefault(key, []).append(player)
    for key, rows in grouped.items():
        rows.sort(key=lambda row: _float(row.get("projected_shots")), reverse=True)
    return grouped


def _projected_starters_note(match: dict[str, object], fallback_teams: str) -> str:
    if fallback_teams and fallback_teams.lower() != "none":
        return f"Projected starters monitored for {fallback_teams}."
    return "Projected starters shaped from today’s expected XI."


def _read_json_records(path: Path) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _extract_report_value(text: str, label: str) -> str:
    target = label.strip().lower()
    for raw in text.splitlines():
        if raw.lower().startswith(target + ":"):
            return raw.split(":", 1)[1].strip()
    return ""


def _extract_realism_status(text: str) -> str:
    value = _extract_report_value(text, "Realism verdict")
    return value or "FAIL"


def _latest_timestamp(paths: list[Path]) -> str | None:
    stamps = [path.stat().st_mtime for path in paths if path.exists()]
    if not stamps:
        return None
    return datetime.fromtimestamp(max(stamps)).isoformat()


def _assert_clean_public_payload(payload: dict[str, object]) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    cleaned = text.replace("lineup", "").replace("Lineup", "")
    if FORBIDDEN_PUBLIC_TERMS.search(cleaned):
        raise ValueError("EPL public payload contains restricted public wording.")


def _float(value: object) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _num(value: object, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "n/a"


def _pct(value: object) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "n/a"


def _shorten_player_name(name: str) -> str:
    """Shorten long full names to First + Last for cleaner mobile display.

    Examples:
      'Bruno Borges Fernandes'       -> 'Bruno Fernandes'
      'Matheus Santos Carneiro da Cunha' -> 'Matheus Cunha'
      'Bryan Mbeumo'                 -> 'Bryan Mbeumo' (unchanged)
    """
    parts = name.strip().split()
    if len(parts) <= 2:
        return name
    return f"{parts[0]} {parts[-1]}"


def _format_timestamp_soccer(iso_string: str) -> str:
    """Format ISO UTC timestamp into a human-readable ET label."""
    try:
        dt = datetime.fromisoformat(iso_string)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        et = dt.astimezone(ZoneInfo("America/New_York"))
        return et.strftime("%B %d, %Y %I:%M %p ET")
    except Exception:
        return iso_string


def _format_kickoff_time(utc_string: object) -> str:
    """Format kickoff UTC into a short ET time label."""
    try:
        raw = str(utc_string or "")
        if not raw:
            return ""
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        et = dt.astimezone(ZoneInfo("America/New_York"))
        return et.strftime("%a %I:%M %p ET")
    except Exception:
        return ""


def _epl_css() -> str:
    return """
      .last-updated {
        color: var(--muted);
        font-size: 11px;
        margin-top: 8px;
        letter-spacing: 0.04em;
      }
      .soccer-overview, .epl-summary-band, .epl-state-panel {
        background: linear-gradient(180deg, rgba(11,18,32,0.98), rgba(6,11,23,0.98));
        border: 1px solid var(--line);
        border-radius: var(--radius-lg);
        padding: 16px 18px;
        box-shadow: 0 18px 44px rgba(2, 8, 23, 0.42);
        margin-bottom: 12px;
      }
      .soccer-overview, .epl-summary-band {
        display: flex;
        justify-content: space-between;
        gap: 18px;
        align-items: flex-start;
      }
      .soccer-product-copy { max-width: 720px; }
      .soccer-status-card {
        width: min(320px, 100%);
        background: rgba(15, 23, 42, 0.72);
        border: 1px solid rgba(30, 41, 59, 0.95);
        border-radius: var(--radius-md);
        padding: 16px;
      }
      .soccer-status-card span, .match-label, .lineup-note span {
        color: #bfdbfe;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }
      .soccer-status-card strong { display: block; margin: 6px 0; color: #fff; font-size: 28px; }
      .soccer-action {
        display: inline-flex;
        margin-top: 12px;
        padding: 9px 12px;
        border: 1px solid rgba(59,130,246,0.34);
        border-radius: 12px;
        color: #fff;
        text-decoration: none;
        background: rgba(37,99,235,0.16);
        font-weight: 800;
      }
      .confidence-chip {
        border: 1px solid rgba(16,185,129,0.3);
        background: rgba(16,185,129,0.12);
        color: #bbf7d0;
        border-radius: 999px;
        padding: 8px 11px;
        font-size: 12px;
        font-weight: 800;
        white-space: nowrap;
      }
      .kickoff-chip {
        border: 1px solid rgba(59,130,246,0.3);
        background: rgba(59,130,246,0.12);
        color: #bfdbfe;
        border-radius: 999px;
        padding: 8px 11px;
        font-size: 11px;
        font-weight: 700;
        white-space: nowrap;
      }
      .match-card-meta {
        display: flex;
        gap: 8px;
        align-items: center;
        flex-wrap: wrap;
      }
      .epl-match-grid { display: grid; gap: 14px; }
      .epl-match-card {
        background: rgba(11,18,32,0.98);
        border: 1px solid var(--line);
        border-radius: var(--radius-lg);
        padding: 16px;
        box-shadow: 0 18px 44px rgba(2, 8, 23, 0.42);
      }
      .match-card-top {
        display: flex;
        justify-content: space-between;
        gap: 14px;
        align-items: flex-start;
        flex-wrap: wrap;
      }
      .match-card-header-wrap {
        flex: 1 1 auto;
        min-width: 0;
      }
      .matchup-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-top: 8px;
        flex-wrap: wrap;
      }
      .matchup-team {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
      }
      .matchup-side-label {
        font-size: 9px;
        font-weight: 800;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: var(--muted);
      }
      .matchup-name {
        font-size: 22px;
        font-weight: 800;
        color: #fff;
        letter-spacing: -0.03em;
        line-height: 1.15;
        white-space: normal;
        overflow: visible;
        text-overflow: clip;
        max-width: 220px;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
      }
      .matchup-goals {
        font-size: 28px;
        font-weight: 800;
        color: #fff;
        line-height: 1;
        letter-spacing: -0.04em;
      }
      .matchup-vs {
        font-size: 13px;
        font-weight: 600;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.1em;
        margin-top: 12px;
      }
      .score-row, .tempo-row {
        display: flex;
        justify-content: space-between;
        gap: 14px;
        align-items: flex-start;
      }
      .score-row {
        margin: 16px 0;
        padding: 14px;
        background: rgba(2,6,23,0.5);
        border: 1px solid rgba(30,41,59,0.8);
        border-radius: 14px;
      }
      .score-label {
        color: #bfdbfe;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }
      .score-row strong { font-size: 30px; color: #fff; }
      .tempo-row span, .metric-row span, .prob-grid span { color: var(--muted); font-size: 12px; }
      .prob-grid, .team-grid, .player-columns {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
      }
      .prob-grid div, .team-panel, .player-table-wrap {
        background: rgba(15,23,42,0.72);
        border: 1px solid rgba(30,41,59,0.9);
        border-radius: 14px;
        padding: 12px;
      }
      .prob-grid strong { display: block; margin-top: 4px; color: #fff; font-size: 20px; }
      .team-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 10px; }
      .team-panel h4, .player-section h4, .player-table-wrap h5 { margin: 0 0 10px; color: #fff; letter-spacing: 0; }
      .metric-row {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        padding: 8px 0;
        border-top: 1px solid rgba(30,41,59,0.72);
      }
      .metric-row:first-of-type { border-top: 0; }
      .metric-row strong, .tempo-row strong { color: #fff; }
      .tempo-row { margin-top: 12px; }
      .projected-lineups {
        margin-top: 12px;
        background: rgba(59,130,246,0.08);
        border: 1px solid rgba(59,130,246,0.2);
        border-radius: 14px;
        padding: 12px;
      }
      .lineup-head {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        align-items: center;
        margin-bottom: 10px;
      }
      .lineup-head span {
        color: #bfdbfe;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }
      .lineup-head strong { color: #fff; }
      .lineup-columns {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }
      .lineup-team {
        background: rgba(2,6,23,0.38);
        border: 1px solid rgba(30,41,59,0.76);
        border-radius: 12px;
        padding: 10px;
      }
      .lineup-team h5 {
        margin: 0 0 8px;
        color: #fff;
      }
      .lineup-player {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto auto;
        gap: 8px;
        align-items: center;
        padding: 7px 0;
        border-top: 1px solid rgba(30,41,59,0.62);
      }
      .lineup-player:first-of-type { border-top: 0; }
      .lineup-player strong {
        display: block;
        color: #fff;
        font-size: 12px;
        line-height: 1.2;
      }
      .lineup-player span {
        color: var(--muted);
        font-size: 11px;
      }
      .lineup-minutes {
        color: #dbeafe !important;
        font-weight: 800;
        white-space: nowrap;
      }
      .lineup-source {
        border: 1px solid rgba(59,130,246,0.22);
        border-radius: 999px;
        padding: 3px 7px;
        background: rgba(59,130,246,0.1);
        color: #bfdbfe !important;
        font-weight: 800;
      }
      .lineup-player.empty {
        display: block;
        color: var(--muted);
        font-size: 13px;
      }
      .player-section { margin-top: 16px; }
      .player-columns { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .player-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
      .player-card-list { display: none; }
      .player-table th, .player-table td { padding: 8px 6px; border-top: 1px solid rgba(30,41,59,0.72); text-align: right; font-size: 12px; }
      .player-table th:first-child, .player-table td:first-child { text-align: left; width: 38%; }
      .player-table th { color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; }
      .player-table td strong { display: block; color: #fff; font-size: 12px; line-height: 1.25; }
      .player-table td span { color: var(--muted); font-size: 11px; }
      @media (max-width: 820px) {
        .soccer-overview, .epl-summary-band { flex-direction: column; }
        .match-card-top { flex-direction: column; gap: 10px; }
        .score-row { flex-direction: column; }
        .matchup-header { gap: 8px; }
        .matchup-name { font-size: 18px; max-width: 46vw; }
        .matchup-goals { font-size: 24px; }
        .matchup-vs { margin-top: 6px; }
        .prob-grid, .team-grid, .player-columns, .lineup-columns { grid-template-columns: 1fr; }
        .epl-match-card { padding: 14px; }
        .player-table th, .player-table td { padding: 6px 4px; font-size: 11px; }
        .player-table td strong { font-size: 11px; }
        .player-table th:first-child, .player-table td:first-child { width: 42%; }
      }
      @media (max-width: 700px) {
        .soccer-overview, .epl-summary-band, .epl-state-panel {
          padding: 14px;
          margin-bottom: 10px;
        }
        .epl-summary-band h2, .soccer-overview h2 {
          font-size: 24px;
        }
        .epl-match-grid {
          gap: 12px;
        }
        .epl-match-card {
          padding: 12px;
          border-radius: 18px;
        }
        .match-card-top {
          gap: 8px;
        }
        .match-label, .matchup-side-label, .score-label {
          letter-spacing: 0.08em;
        }
        .matchup-header {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
          align-items: start;
          width: 100%;
        }
        .matchup-team {
          min-width: 0;
        }
        .matchup-name {
          max-width: none;
          font-size: 17px;
          line-height: 1.12;
        }
        .matchup-goals {
          font-size: 22px;
        }
        .score-row {
          margin: 12px 0;
          padding: 11px;
        }
        .score-row strong {
          font-size: 24px;
        }
        .prob-grid {
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 8px;
        }
        .prob-grid div, .team-panel, .player-table-wrap {
          padding: 10px;
          border-radius: 12px;
        }
        .prob-grid strong {
          font-size: 17px;
        }
        .metric-row {
          padding: 6px 0;
        }
        .projected-lineups {
          padding: 10px;
        }
        .lineup-player {
          grid-template-columns: minmax(0, 1fr) auto;
        }
        .lineup-source {
          grid-column: 1 / -1;
          justify-self: start;
        }
        .player-section {
          margin-top: 12px;
        }
        .player-columns {
          gap: 10px;
        }
        .player-table {
          display: none;
        }
        .player-card-list {
          display: grid;
          gap: 8px;
        }
        .player-shot-card {
          display: grid;
          gap: 9px;
          padding: 10px;
          border: 1px solid rgba(30,41,59,0.8);
          border-radius: 12px;
          background: rgba(2,6,23,0.38);
        }
        .player-shot-card.empty {
          color: var(--muted);
          font-size: 13px;
        }
        .player-card-head {
          display: flex;
          justify-content: space-between;
          gap: 10px;
          align-items: start;
        }
        .player-card-head strong {
          color: #fff;
          line-height: 1.2;
        }
        .player-card-head span {
          color: var(--muted);
          font-size: 11px;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }
        .player-shot-main {
          display: flex;
          justify-content: space-between;
          align-items: center;
          color: var(--muted);
          font-size: 12px;
        }
        .player-shot-main strong {
          color: #fff;
          font-size: 19px;
        }
        .player-badge-row {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 6px;
        }
        .player-badge-row span {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-height: 30px;
          border: 1px solid rgba(59,130,246,0.24);
          border-radius: 999px;
          background: rgba(59,130,246,0.1);
          color: #dbeafe;
          font-size: 12px;
          font-weight: 800;
        }
      }
    """
