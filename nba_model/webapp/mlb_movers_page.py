"""MLB Biggest Movers — Phase 2 ADMIN-GATED preview page.

Renders /mlb/movers from the precomputed ``mlb_movers_today.json`` artifact
ONLY. Hard constraints (by design, do not relax without a decision):

  * reads one JSON file — no model access, no pandas, no recalculation,
    no network, no writes;
  * the route is registered admin-gated (same ``_internal_is_admin`` gate as
    /admin/qa/mlb/board) and ``noindex, nofollow`` until several slates of
    reason-tag output have been reviewed;
  * missing/absent JSON renders a friendly empty state, never an error.

Filters (All / HR / Hits / Pitchers + reason tags) are pure client-side
show/hide over data attributes — the server renders one static document.
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
    ("hr_prob", "hr", "Top HR Movers", "Home-run probability, percentage points since the morning baseline."),
    ("hit_prob", "hit", "Top Hit Movers", "Hit probability, percentage points since the morning baseline."),
    ("proj_pitcher_k", "pitcher", "Top Pitcher K Movers", "Projected strikeouts since the morning baseline."),
]

_TAG_COLORS = {
    "Lineup Confirmed": ("rgba(34,197,94,.14)", "#4ade80"),
    "Starting Pitcher Change": ("rgba(245,158,11,.16)", "#fbbf24"),
    "Weather Change": ("rgba(56,189,248,.14)", "#7dd3fc"),
    "Model Refresh": ("rgba(168,85,247,.14)", "#c4b5fd"),
    "Unknown": ("rgba(148,163,184,.12)", "#94a3b8"),
}


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


def _fmt_ts(iso: str) -> str:
    """'2026-07-04T13:39:36Z' -> '2026-07-04 13:39 UTC (9:39 AM ET)'."""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        try:
            from zoneinfo import ZoneInfo
            et = dt.astimezone(ZoneInfo("America/New_York"))
            et_txt = et.strftime("%-I:%M %p ET")
        except Exception:
            et_txt = ""
        utc_txt = dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return f"{utc_txt} ({et_txt})" if et_txt else utc_txt
    except Exception:
        return str(iso)


def _fmt_val(value, kind: str) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{v:.1f}%" if kind == "probability" else f"{v:.2f}"


def _tag_pill(tag: str) -> str:
    bg, fg = _TAG_COLORS.get(tag, _TAG_COLORS["Unknown"])
    return (f"<span style='display:inline-block;padding:3px 10px;border-radius:999px;"
            f"background:{bg};color:{fg};font-size:11px;font-weight:800;letter-spacing:.03em;"
            f"white-space:nowrap'>{escape(tag)}</span>")


def _mover_card(m: dict, market_key: str, latest_ts: str, k8_by_pid: dict) -> str:
    up = m.get("direction") == "up"
    color = "#4ade80" if up else "#f87171"
    arrow = "▲" if up else "▼"
    kind = m.get("kind", "probability")
    delta = m.get("abs_change")
    try:
        delta_txt = f"{float(delta):+.1f}{'pp' if kind == 'probability' else ''}"
    except (TypeError, ValueError):
        delta_txt = "—"
    tag = str(m.get("reason_tag") or "Unknown")
    detail = str(m.get("reason_detail") or "")
    detail_html = (f"<div style='font-size:12px;color:#94a3b8;margin-top:5px'>↳ {escape(detail)}</div>"
                   if detail else "")
    k8_html = ""
    if market_key == "proj_pitcher_k":
        k8 = k8_by_pid.get(str(m.get("player_id") or ""))
        if k8:
            k8_html = (f"<div style='font-size:12px;color:#94a3b8;margin-top:5px'>8+ K prob: "
                       f"{_fmt_val(k8.get('morning_value'), 'probability')} → "
                       f"{_fmt_val(k8.get('current_value'), 'probability')}</div>")
    return (
        f"<div class='mv-card' data-market='{escape(market_key)}' data-reason='{escape(tag)}'"
        " style='background:var(--surface,#121929);border:1px solid var(--line,#1e293b);"
        f"border-left:3px solid {color};border-radius:12px;padding:12px 14px'>"
        "<div style='display:flex;justify-content:space-between;align-items:flex-start;gap:10px'>"
        "<div style='min-width:0'>"
        f"<div style='font-weight:800;color:var(--ink,#f8fafc);font-size:15px'>{escape(str(m.get('player_name', '')))}</div>"
        f"<div style='font-size:12px;color:#94a3b8;margin-top:2px'>{escape(str(m.get('team', '')))} vs {escape(str(m.get('opponent', '')))}</div>"
        "</div>"
        f"<div style='flex:0 0 auto;text-align:right;color:{color};font-weight:900;font-size:16px;white-space:nowrap'>{arrow} {escape(delta_txt)}</div>"
        "</div>"
        f"<div style='margin-top:8px;font-size:15px;color:#e2e8f0;font-weight:700'>"
        f"{_fmt_val(m.get('morning_value'), kind)} <span style='color:#64748b'>→</span> "
        f"<span style='color:{color}'>{_fmt_val(m.get('current_value'), kind)}</span></div>"
        f"<div style='margin-top:7px'>{_tag_pill(tag)}</div>"
        + detail_html + k8_html +
        f"<div style='font-size:10px;color:#64748b;margin-top:7px'>refresh {escape(_fmt_ts(latest_ts))}</div>"
        "</div>"
    )


def _section(sec_id: str, title: str, sub: str, inner: str, market_attr: str = "") -> str:
    attr = f" data-market-section='{escape(market_attr)}'" if market_attr else ""
    return (f"<section class='panel mv-section' id='{escape(sec_id)}'{attr}>"
            "<div class='panel-head'><div>"
            f"<div class='eyebrow'>Biggest Movers</div><h2>{escape(title)}</h2></div>"
            f"<p class='muted' style='margin:0;font-size:12px'>{escape(sub)}</p></div>"
            + inner + "</section>")


def _names_list(names: list, empty_msg: str) -> str:
    if not names:
        return f"<p class='muted' style='margin-top:10px'>{escape(empty_msg)}</p>"
    pills = "".join(
        f"<span style='display:inline-block;margin:3px;padding:5px 11px;border-radius:999px;"
        f"background:rgba(148,163,184,.10);border:1px solid var(--line,#1e293b);"
        f"color:#cbd5e1;font-size:12px'>{escape(str(n))}</span>"
        for n in names
    )
    return f"<div style='margin-top:10px'>{pills}</div>"


def _filter_bar(tags_present: list) -> str:
    def btn(label, group, value, active=False):
        cls = "mv-fbtn active" if active else "mv-fbtn"
        return (f"<button class='{cls}' data-fgroup='{group}' data-fval='{escape(value)}'"
                " style='padding:7px 14px;border-radius:999px;border:1px solid var(--line,#1e293b);"
                "background:var(--surface,#121929);color:#cbd5e1;font-size:13px;font-weight:700;"
                "cursor:pointer'>"
                f"{escape(label)}</button>")
    market_btns = (btn("All", "market", "all", True) + btn("HR", "market", "hr_prob")
                   + btn("Hits", "market", "hit_prob") + btn("Pitchers", "market", "proj_pitcher_k"))
    tag_btns = btn("All reasons", "reason", "all", True) + "".join(
        btn(t, "reason", t) for t in tags_present)
    return (
        "<div style='display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 6px'>"
        "<span style='font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;font-weight:800'>Market</span>"
        + market_btns +
        "</div>"
        "<div style='display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0 14px'>"
        "<span style='font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;font-weight:800'>Reason</span>"
        + tag_btns +
        "</div>"
    )


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
      var anyVisible = Array.prototype.some.call(
        s.querySelectorAll(".mv-card"), function (c) { return c.style.display !== "none"; });
      s.style.display = (okM && (anyVisible || state.reason === "all")) ? "" : "none";
      if (okM && !anyVisible) {
        var e = s.querySelector(".mv-noneleft");
        if (e) e.style.display = "";
      } else {
        var e2 = s.querySelector(".mv-noneleft");
        if (e2) e2.style.display = "none";
      }
    });
  }
  document.querySelectorAll(".mv-fbtn").forEach(function (b) {
    b.addEventListener("click", function () {
      state[b.dataset.fgroup] = b.dataset.fval;
      document.querySelectorAll(".mv-fbtn[data-fgroup='" + b.dataset.fgroup + "']").forEach(function (x) {
        x.classList.remove("active");
        x.style.borderColor = "";
        x.style.color = "#cbd5e1";
      });
      b.classList.add("active");
      b.style.borderColor = "#3b82f6";
      b.style.color = "#fff";
      apply();
    });
  });
  document.querySelectorAll(".mv-fbtn.active").forEach(function (b) {
    b.style.borderColor = "#3b82f6"; b.style.color = "#fff";
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

        # header / status strip
        facts = [
            ("Slate", str(meta.get("slate_date") or "—")),
            ("Last updated", _fmt_ts(latest_ts)),
            ("Baseline", f"{_fmt_ts(str(meta.get('baseline_ts') or ''))} ({meta.get('baseline_type', '—')})"),
            ("Snapshots today", str(meta.get("snapshot_count") or "—")),
            ("Latest refresh type", str(meta.get("latest_refresh_type") or "—")),
        ]
        facts_html = "".join(
            "<div style='background:var(--surface,#121929);border:1px solid var(--line,#1e293b);"
            "border-radius:12px;padding:10px 14px'>"
            f"<div style='font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.04em'>{escape(k)}</div>"
            f"<div style='font-size:13px;color:var(--ink,#f8fafc);font-weight:700;margin-top:3px'>{escape(v)}</div></div>"
            for k, v in facts
        )
        integrity = diagnostics.get("frozen_changed_rows", 0)
        integrity_html = ""
        if integrity:
            integrity_html = ("<p style='color:#fca5a5;font-weight:700;margin:10px 0 0'>⚠ frozen-game "
                              f"integrity: {int(integrity)} started-game rows changed — investigate before trusting deltas.</p>")
        header = ("<section class='panel'><div class='panel-head'><div>"
                  "<div class='eyebrow'>Internal Preview</div><h2>MLB Biggest Movers</h2></div>"
                  "<p class='muted' style='margin:0;font-size:12px'>Reads the published movers artifact only — "
                  "no model access, no recalculation.</p></div>"
                  "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-top:6px'>"
                  + facts_html + "</div>" + integrity_html + "</section>")

        # mover sections
        k8_by_pid = {str(m.get("player_id") or ""): m for m in sections.get("pitcher_k_8plus") or []}
        tags_present = sorted(reason_mix.keys(), key=lambda t: -reason_mix[t])
        body_sections = []
        for market_key, _fkey, title, sub in _SECTION_DEFS:
            movers = sections.get(market_key) or []
            if movers:
                cards = "".join(_mover_card(m, market_key, latest_ts, k8_by_pid) for m in movers)
                inner = ("<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));"
                         "gap:10px;margin-top:12px'>" + cards + "</div>"
                         "<p class='mv-noneleft muted' style='display:none;margin-top:10px'>No movers match the current filters.</p>")
            else:
                inner = "<p class='muted' style='margin-top:10px'>No qualifying movers in this market yet.</p>"
            body_sections.append(_section(f"mv-{market_key}", title, sub, inner, market_attr=market_key))

        # new / dropped / reasons
        new_names = diagnostics.get("new_players") or []
        dropped_names = diagnostics.get("dropped_players") or []
        body_sections.append(_section(
            "mv-new", "New Players",
            f"On the board now but not in the morning baseline ({int(diagnostics.get('new_player_count') or 0)}).",
            _names_list(new_names, "No players added since the morning baseline.")))
        body_sections.append(_section(
            "mv-dropped", "Dropped Players",
            f"In the morning baseline but off the board now ({int(diagnostics.get('dropped_player_count') or 0)}) — "
            "usually bench players removed when lineups confirm.",
            _names_list(dropped_names, "No players dropped since the morning baseline.")))

        total = sum(reason_mix.values()) or 1
        mix_rows = "".join(
            "<div style='display:flex;align-items:center;gap:10px;margin-top:8px'>"
            f"<div style='flex:0 0 190px'>{_tag_pill(t)}</div>"
            f"<div style='flex:1;height:8px;border-radius:999px;background:rgba(148,163,184,.14);overflow:hidden'>"
            f"<span style='display:block;height:100%;width:{reason_mix[t] / total * 100:.1f}%;"
            f"background:{_TAG_COLORS.get(t, _TAG_COLORS['Unknown'])[1]}'></span></div>"
            f"<div style='flex:0 0 60px;text-align:right;color:#cbd5e1;font-size:13px;font-weight:700'>{reason_mix[t]}</div>"
            "</div>"
            for t in tags_present
        )
        body_sections.append(_section(
            "mv-reasons", "Reason Summary",
            "Attribution across ALL movers this slate (not just the top lists).",
            mix_rows or "<p class='muted' style='margin-top:10px'>No movers to attribute yet.</p>"))

        note = ("<p class='muted' style='font-size:12px;margin-top:4px'>Internal preview — admin-only, noindex. "
                "Values are the published board's own numbers; \"Unknown\" means no rule matched, never a guess.</p>")
        return (header + _filter_bar(tags_present) + "".join(body_sections) + note + _FILTER_JS)
    except Exception:
        return ("<section class='panel'><div class='panel-head'><div>"
                "<div class='eyebrow'>Biggest Movers</div><h2>Temporarily unavailable</h2></div></div>"
                "<p class='st-prose' style='color:#94a3b8'>The movers artifact could not be rendered. "
                "The data pipeline is unaffected.</p></section>")
