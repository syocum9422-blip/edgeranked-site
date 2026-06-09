"""
Shared premium Projection Explorer renderer for NBA + WNBA.

Pure presentation: takes the already-computed record list (one entry per
player-stat combination) that build_*_projection_records() returns and emits
the redesigned HTML. Does NOT call into model code, the projection pipeline,
the sportsbook integration, or any data source — it only re-organizes and
restyles existing rows. NBA and WNBA both call render_projection_explorer()
with their own namespace + sport label so the visual language stays identical.

Record contract (fields read; every field is optional unless marked):
    player                  (str, required)
    team                    (str, required)
    opponent                (str)
    matchup                 (str)
    confidence              (str: "high"/"medium"/"low"/...)
    confidence_rank         (int)
    expected_minutes        (float | None)
    stat_key                (str, required)
    stat_label              (str, required)
    projection              (float | None, required)
    range_display           (str)
    floor_projection        (float | None)
    ceiling_projection      (float | None)
    distribution_std        (float | None)
    threshold               (float | None)
    threshold_label         (str)
    threshold_probability   (float in [0,1] | None)
    sportsbook_line         (float | None)
    sportsbook_delta        (float | None)
    fantasy_projection      (float | None)    # NBA only
"""

from html import escape
from collections import OrderedDict
import re
import unicodedata


def _slugify_player_name(value):
    text = (value or "").strip()
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    ascii_text = ascii_text.replace("'", "").replace("'", "").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def _player_name_html(player, namespace):
    name = (player or "").strip()
    if not name:
        return ""
    if namespace == "nba":
        slug = _slugify_player_name(name)
        if slug:
            return f"<a class='nba-player-link' href='/nba/player/{slug}'>{escape(name)}</a>"
    if namespace == "wnba":
        slug = _slugify_player_name(name)
        if slug:
            return f"<a class='wnba-player-link' href='/wnba/player/{slug}'>{escape(name)}</a>"
    return escape(name)


# --- formatters ------------------------------------------------------------

def _fmt_metric(value, digits=1):
    if value is None:
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{n:.{digits}f}"


def _fmt_pct(value):
    if value is None:
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{n * 100:.0f}%"


def _fmt_signed(value, digits=1):
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n == 0:
        return "0"
    return f"{n:+.{digits}f}"


def _confidence_band(rank):
    """Map confidence_rank to a visual tier."""
    try:
        r = int(rank)
    except (TypeError, ValueError):
        return ("standard", "Standard")
    if r >= 3:
        return ("elite", "Elite")
    if r >= 2:
        return ("strong", "Strong")
    return ("standard", "Standard")


# --- player grouping -------------------------------------------------------

def _group_by_player(rows):
    """Aggregate (player, stat) rows into one entry per player.

    The first row encountered for a player anchors team/matchup/etc.; each
    additional row adds a stat tile. Original sort order is preserved so the
    grouped output mirrors the slate-level priority the source already used.
    """
    players = OrderedDict()
    for row in rows:
        key = (row.get("player") or "").strip()
        if not key:
            continue
        bucket = players.get(key)
        if bucket is None:
            bucket = {
                "player": row.get("player") or "",
                "team": (row.get("team") or "").strip(),
                "opponent": (row.get("opponent") or "").strip(),
                "matchup": row.get("matchup") or "",
                "confidence": row.get("confidence") or "",
                "confidence_rank": row.get("confidence_rank") or 0,
                "expected_minutes": row.get("expected_minutes"),
                "fantasy_projection": row.get("fantasy_projection"),
                "tiles": [],
                "best_probability": 0.0,
                "max_std_ratio": 0.0,
                "max_abs_delta": 0.0,
                "any_high_conf": False,
            }
            players[key] = bucket

        # Stat tile data
        proj = row.get("projection")
        prob = row.get("threshold_probability")
        bucket["tiles"].append({
            "stat_key": row.get("stat_key") or "",
            "stat_label": row.get("stat_label") or "",
            "projection": proj,
            "threshold_probability": prob,
            "range_display": row.get("range_display") or "",
            "floor_projection": row.get("floor_projection"),
            "ceiling_projection": row.get("ceiling_projection"),
            "distribution_std": row.get("distribution_std"),
        })

        # Player-level rollups for tiering + insight detection.
        if prob is not None:
            try:
                pf = float(prob)
                if pf > bucket["best_probability"]:
                    bucket["best_probability"] = pf
            except (TypeError, ValueError):
                pass
        try:
            std = float(row.get("distribution_std")) if row.get("distribution_std") is not None else None
            pj = float(proj) if proj is not None else None
            if std is not None and pj and pj > 0:
                ratio = std / pj
                if ratio > bucket["max_std_ratio"]:
                    bucket["max_std_ratio"] = ratio
        except (TypeError, ValueError):
            pass
        try:
            delta = row.get("sportsbook_delta")
            if delta is not None:
                ad = abs(float(delta))
                if ad > bucket["max_abs_delta"]:
                    bucket["max_abs_delta"] = ad
        except (TypeError, ValueError):
            pass
        if (row.get("confidence") or "").lower() == "high":
            bucket["any_high_conf"] = True

        # Carry minutes/fantasy from any row that has them (some rows may be None).
        if bucket["expected_minutes"] is None and row.get("expected_minutes") is not None:
            bucket["expected_minutes"] = row.get("expected_minutes")
        if bucket["fantasy_projection"] is None and row.get("fantasy_projection") is not None:
            bucket["fantasy_projection"] = row.get("fantasy_projection")

    return list(players.values())


# --- insight strip ---------------------------------------------------------

_POINTS_KEYS = {"PTS", "POINTS", "POINTS_SCORED", "PTS_PROJ", "PTS_PROJECTION"}


def _build_insights(rows):
    """Return up to 4 insight-card dicts drawn from raw row data."""
    out = []

    # 1) Highest Projected Scorer (points-like stat)
    points_rows = [r for r in rows
                   if (r.get("stat_key") or "").upper() in _POINTS_KEYS
                   and r.get("projection") is not None]
    if points_rows:
        top = max(points_rows, key=lambda r: float(r["projection"]))
        out.append({
            "label": "Highest Projected Scorer",
            "player": top.get("player") or "",
            "matchup": top.get("matchup") or "",
            "value": _fmt_metric(top.get("projection")),
            "unit": top.get("stat_label") or "PTS",
            "tone": "primary",
        })

    # 2) Highest Outcome Confidence (high-confidence + best probability)
    conf_pool = [r for r in rows
                 if (r.get("confidence") or "").lower() == "high"
                 and r.get("threshold_probability") is not None]
    if not conf_pool:
        conf_pool = [r for r in rows if r.get("threshold_probability") is not None]
    if conf_pool:
        top = max(conf_pool, key=lambda r: float(r["threshold_probability"]))
        out.append({
            "label": "Highest Outcome Confidence",
            "player": top.get("player") or "",
            "matchup": top.get("matchup") or "",
            "value": _fmt_pct(top.get("threshold_probability")),
            "unit": f"{(top.get('stat_label') or '').strip()} hit rate",
            "tone": "confidence",
        })

    # 3) Strong Matchup (top projection × probability composite across rows
    #    where the model expresses meaningful conviction). No sportsbook line
    #    is referenced — this is a pure simulation-driven opportunity card.
    matchup_pool = []
    for r in rows:
        proj = r.get("projection")
        prob = r.get("threshold_probability")
        if proj is None or prob is None:
            continue
        try:
            pf = float(proj)
            qf = float(prob)
            if pf > 0 and qf >= 0.55:
                matchup_pool.append((pf * qf, r, qf))
        except (TypeError, ValueError):
            continue
    if matchup_pool:
        _, top, qf = max(matchup_pool, key=lambda t: t[0])
        out.append({
            "label": "Strong Matchup",
            "player": top.get("player") or "",
            "matchup": top.get("matchup") or "",
            "value": _fmt_pct(qf),
            "unit": f"{top.get('stat_label') or ''} projection conviction",
            "tone": "matchup",
        })

    # 4) High Variance Projection (highest std/projection ratio — wide
    #    simulation outcome band, useful for tournament/leverage thinking).
    vol_pool = []
    for r in rows:
        proj = r.get("projection")
        std = r.get("distribution_std")
        if proj is None or std is None:
            continue
        try:
            pf = float(proj)
            sf = float(std)
            if pf > 0:
                vol_pool.append((sf / pf, r, sf))
        except (TypeError, ValueError):
            continue
    if vol_pool:
        ratio, top, std_val = max(vol_pool, key=lambda t: t[0])
        out.append({
            "label": "High Variance Projection",
            "player": top.get("player") or "",
            "matchup": top.get("matchup") or "",
            "value": f"±{_fmt_metric(std_val)}",
            "unit": f"{top.get('stat_label') or ''} simulation swing",
            "tone": "volatile",
        })

    return out[:4]


# --- main render -----------------------------------------------------------

_TIER_DEFS = [
    ("elite",    "Elite Projections",     "High-confidence projections leading the slate."),
    ("strong",   "Strong Confidence",     "Steady model conviction across the player's stat set."),
    ("standard", "All Projections",       "Every modeled player in the current slate."),
]


def _player_tier(bucket):
    band, _ = _confidence_band(bucket.get("confidence_rank", 0))
    return band


def render_projection_explorer(rows, *, sport_label, namespace):
    """Render the premium projection explorer HTML for `sport_label` (NBA/WNBA).

    `namespace` is a short id-safe slug like "nba" or "wnba" so multiple
    instances on a page (if ever) and the JS selectors stay isolated.
    """
    ns = namespace
    sport_display = escape(sport_label)

    if not rows:
        return (
            f"<section class='pe-shell pe-empty' data-pe-ns='{escape(ns)}'>"
            "  <div class='pe-empty-card'>"
            "    <div class='pe-eyebrow'>Projection Explorer</div>"
            f"    <h2>No {sport_display} projections are available yet.</h2>"
            f"    <p>The latest {sport_display} simulation output has not been"
            "       loaded. Check back shortly — the model refreshes on cron.</p>"
            "  </div>"
            "</section>"
        )

    insights = _build_insights(rows)
    players = _group_by_player(rows)

    # Pre-compute filter option lists from raw rows.
    teams = sorted({(r.get("team") or "").strip() for r in rows if (r.get("team") or "").strip()})
    stat_pairs = OrderedDict()
    for r in rows:
        sk = (r.get("stat_key") or "").strip()
        sl = (r.get("stat_label") or "").strip()
        if sk and sk not in stat_pairs:
            stat_pairs[sk] = sl or sk
    stats = list(stat_pairs.items())

    # ---- HTML build ------------------------------------------------------

    def insight_card(card):
        tone = escape(card.get("tone") or "primary")
        return (
            f"<article class='pe-insight pe-insight-{tone}'>"
            f"  <div class='pe-insight-label'>{escape(card['label'])}</div>"
            f"  <div class='pe-insight-value'>{escape(card['value'])}</div>"
            f"  <div class='pe-insight-unit'>{escape(card['unit'])}</div>"
            f"  <div class='pe-insight-player'>{_player_name_html(card['player'], ns)}</div>"
            f"  <div class='pe-insight-matchup'>{escape(card['matchup'])}</div>"
            "</article>"
        )

    insight_html = ""
    if insights:
        insight_html = (
            "<div class='pe-insights' role='region' aria-label='Top AI insights'>"
            + "".join(insight_card(c) for c in insights)
            + "</div>"
        )

    # Pill filter row
    def pill(name, value, label, group):
        return (
            f"<button type='button' class='pe-pill' data-pe-filter='{group}' "
            f"data-pe-value='{escape(value)}' aria-pressed='false'>"
            f"{escape(label)}</button>"
        )

    team_pills = (
        f"<button type='button' class='pe-pill is-active' data-pe-filter='team' "
        "data-pe-value='ALL' aria-pressed='true'>All Teams</button>"
        + "".join(pill("team", t, t, "team") for t in teams)
    )
    stat_pills = (
        f"<button type='button' class='pe-pill is-active' data-pe-filter='stat' "
        "data-pe-value='ALL' aria-pressed='true'>All Stats</button>"
        + "".join(pill("stat", k, v, "stat") for k, v in stats)
    )
    conf_pills = (
        "<button type='button' class='pe-pill is-active' data-pe-filter='conf' "
        "data-pe-value='ALL' aria-pressed='true'>All Confidence</button>"
        "<button type='button' class='pe-pill' data-pe-filter='conf' "
        "data-pe-value='3' aria-pressed='false'>High</button>"
        "<button type='button' class='pe-pill' data-pe-filter='conf' "
        "data-pe-value='2' aria-pressed='false'>Medium+</button>"
    )

    sort_select = (
        f"<label class='pe-sort'><span>Sort</span>"
        f"<select id='pe-sort-{ns}'>"
        "  <option value='priority'>Slate Priority</option>"
        "  <option value='confidence'>Confidence</option>"
        "  <option value='probability'>Highest Probability</option>"
        "  <option value='minutes'>Expected Minutes</option>"
        "  <option value='player'>Player A→Z</option>"
        "</select></label>"
    )

    filter_html = (
        "<div class='pe-filterbar'>"
        f"  <div class='pe-filter-row'><span class='pe-filter-key'>Team</span>"
        f"    <div class='pe-pillset' role='group' aria-label='Team filter'>{team_pills}</div></div>"
        f"  <div class='pe-filter-row'><span class='pe-filter-key'>Stat</span>"
        f"    <div class='pe-pillset' role='group' aria-label='Stat filter'>{stat_pills}</div></div>"
        f"  <div class='pe-filter-row'><span class='pe-filter-key'>Confidence</span>"
        f"    <div class='pe-pillset' role='group' aria-label='Confidence filter'>{conf_pills}</div></div>"
        f"  <div class='pe-filter-tools'>{sort_select}"
        f"    <button type='button' class='pe-reset' data-pe-reset>Reset</button>"
        "  </div>"
        f"  <p class='pe-summary' id='pe-summary-{ns}'></p>"
        "</div>"
    )

    # Player cards
    def render_tile(tile):
        prob = tile.get("threshold_probability")
        prob_str = _fmt_pct(prob)
        prob_class = ""
        try:
            if prob is not None and float(prob) >= 0.6:
                prob_class = " pe-tile-prob-strong"
            elif prob is not None and float(prob) >= 0.5:
                prob_class = " pe-tile-prob-good"
        except (TypeError, ValueError):
            pass

        # Simulation-style supplementary line. Preferred form is the explicit
        # floor-to-ceiling band from the model's distribution; when that pair
        # isn't available the renderer falls back to the standard-deviation
        # swing so the tile still communicates simulation depth without ever
        # surfacing a sportsbook line. Analytics-first, never sportsbook.
        floor = tile.get("floor_projection")
        ceiling = tile.get("ceiling_projection")
        std = tile.get("distribution_std")
        range_html = ""
        if floor is not None and ceiling is not None:
            range_html = (
                "<div class='pe-tile-range'>"
                "  <span class='pe-tile-range-label'>Sim range</span>"
                f"  <span class='pe-tile-range-value'>{escape(_fmt_metric(floor))} – {escape(_fmt_metric(ceiling))}</span>"
                "</div>"
            )
        elif std is not None:
            range_html = (
                "<div class='pe-tile-range'>"
                "  <span class='pe-tile-range-label'>Sim swing</span>"
                f"  <span class='pe-tile-range-value'>±{escape(_fmt_metric(std))}</span>"
                "</div>"
            )

        prob_block = ""
        if prob is not None:
            prob_block = (
                "<div class='pe-tile-prob'>"
                "  <span class='pe-tile-prob-label'>Projection Confidence</span>"
                f"  <span class='pe-tile-prob-value'>{escape(prob_str)}</span>"
                "</div>"
            )
        return (
            f"<div class='pe-tile{prob_class}' data-pe-stat='{escape(tile['stat_key'])}'>"
            f"  <div class='pe-tile-label'>{escape(tile['stat_label'])}</div>"
            f"  <div class='pe-tile-value'>{escape(_fmt_metric(tile['projection']))}</div>"
            f"  {prob_block}"
            f"  {range_html}"
            "</div>"
        )

    def render_card(bucket):
        band, band_label = _confidence_band(bucket.get("confidence_rank", 0))
        matchup = bucket.get("matchup") or (
            f"{bucket.get('team','')} vs {bucket.get('opponent','')}".strip(" vs")
        )
        minutes = bucket.get("expected_minutes")
        minutes_chip = (
            f"<span class='pe-meta-chip'>{escape(_fmt_metric(minutes))} MIN</span>"
            if minutes is not None else ""
        )
        fantasy = bucket.get("fantasy_projection")
        fantasy_chip = (
            f"<span class='pe-meta-chip pe-meta-chip-accent'>Fantasy {escape(_fmt_metric(fantasy))}</span>"
            if fantasy is not None else ""
        )
        # Each card carries flat data-* attributes for the JS to filter on.
        data_attrs = (
            f"data-pe-card='1' "
            f"data-pe-player='{escape((bucket.get('player') or '').lower())}' "
            f"data-pe-team='{escape((bucket.get('team') or '').upper())}' "
            f"data-pe-stats='{escape(','.join(t['stat_key'] for t in bucket['tiles']))}' "
            f"data-pe-conf-rank='{int(bucket.get('confidence_rank') or 0)}' "
            f"data-pe-band='{escape(band)}' "
            f"data-pe-probability='{bucket.get('best_probability') or 0:.4f}' "
            f"data-pe-minutes='{(_fmt_metric(minutes) if minutes is not None else '')}'"
        )
        tiles_html = "".join(render_tile(t) for t in bucket["tiles"])

        return (
            f"<article class='pe-card pe-card-band-{escape(band)}' {data_attrs}>"
            "  <header class='pe-card-head'>"
            f"   <div class='pe-card-headline'>"
            f"     <div class='pe-card-player'>{_player_name_html(bucket.get('player') or '', ns)}</div>"
            f"     <div class='pe-card-matchup'>{escape(matchup)}</div>"
            "    </div>"
            f"    <div class='pe-card-conf pe-card-conf-{escape(band)}'>"
            f"      <span class='pe-conf-dot'></span>{escape(band_label)}"
            "    </div>"
            "  </header>"
            f"  <div class='pe-card-meta'>{minutes_chip}{fantasy_chip}</div>"
            f"  <div class='pe-tiles'>{tiles_html}</div>"
            "</article>"
        )

    # Tier the player cards.
    by_tier = {"elite": [], "strong": [], "standard": []}
    for bucket in players:
        by_tier[_player_tier(bucket)].append(bucket)

    sections_html = []
    for tier_key, tier_title, tier_desc in _TIER_DEFS:
        bucket_list = by_tier.get(tier_key, [])
        if not bucket_list:
            continue
        cards_html = "".join(render_card(b) for b in bucket_list)
        sections_html.append(
            f"<section class='pe-section pe-section-{escape(tier_key)}' data-pe-tier='{escape(tier_key)}'>"
            f"  <header class='pe-section-head'>"
            f"    <h3>{escape(tier_title)}</h3>"
            f"    <p>{escape(tier_desc)}</p>"
            "  </header>"
            f"  <div class='pe-grid'>{cards_html}</div>"
            "</section>"
        )
    cards_block = "".join(sections_html)

    # JS — namespace embedded as a literal string for selector scoping.
    ns_js = escape(ns)
    script = """
<script>
(() => {
  const NS = "__NS__";
  const root = document.querySelector(".pe-shell[data-pe-ns='" + NS + "']");
  if (!root) return;
  const summary = document.getElementById("pe-summary-" + NS);
  const sortSel = document.getElementById("pe-sort-" + NS);
  const cards = Array.from(root.querySelectorAll("[data-pe-card='1']"));

  const state = { team: "ALL", stat: "ALL", conf: "ALL", sort: "priority" };

  function setPill(group, value) {
    state[group] = value;
    root.querySelectorAll("[data-pe-filter='" + group + "']").forEach((btn) => {
      const active = btn.getAttribute("data-pe-value") === value;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function visible(card) {
    if (state.team !== "ALL" && (card.dataset.peTeam || "").toUpperCase() !== state.team) return false;
    if (state.conf !== "ALL") {
      const r = parseInt(card.dataset.peConfRank || "0", 10);
      const need = parseInt(state.conf, 10) || 0;
      if (r < need) return false;
    }
    if (state.stat !== "ALL") {
      const stats = (card.dataset.peStats || "").split(",");
      if (!stats.includes(state.stat)) return false;
    }
    return true;
  }

  function sortValue(card) {
    if (state.sort === "confidence") return parseFloat(card.dataset.peConfRank || "0");
    if (state.sort === "probability") return parseFloat(card.dataset.peProbability || "0");
    if (state.sort === "minutes") return parseFloat(card.dataset.peMinutes || "0");
    if (state.sort === "player") return (card.dataset.pePlayer || "").toLowerCase();
    return null;
  }

  function apply() {
    let shown = 0;
    cards.forEach((card) => {
      const ok = visible(card);
      card.hidden = !ok;
      if (ok) shown += 1;
      // Per-tile stat hiding: when a stat filter is on, only show that tile.
      const tiles = card.querySelectorAll(".pe-tile");
      tiles.forEach((tile) => {
        if (state.stat === "ALL") {
          tile.hidden = false;
        } else {
          tile.hidden = (tile.dataset.peStat || "") !== state.stat;
        }
      });
    });

    // Re-order cards within each section based on the chosen sort.
    if (state.sort !== "priority") {
      const numeric = state.sort !== "player";
      const dir = numeric ? -1 : 1;
      root.querySelectorAll(".pe-section").forEach((section) => {
        const grid = section.querySelector(".pe-grid");
        if (!grid) return;
        const ordered = Array.from(grid.children).sort((a, b) => {
          const av = sortValue(a);
          const bv = sortValue(b);
          if (typeof av === "string" || typeof bv === "string") {
            return String(av).localeCompare(String(bv)) * dir;
          }
          return ((av || 0) - (bv || 0)) * dir;
        });
        ordered.forEach((node) => grid.appendChild(node));
      });
    }

    // Hide sections with zero visible cards (so empty buckets disappear).
    root.querySelectorAll(".pe-section").forEach((section) => {
      const any = Array.from(section.querySelectorAll("[data-pe-card='1']"))
                       .some((c) => !c.hidden);
      section.hidden = !any;
    });

    if (summary) {
      const bits = [];
      bits.push(shown + " player" + (shown === 1 ? "" : "s") + " shown");
      if (state.team !== "ALL") bits.push("team " + state.team);
      if (state.stat !== "ALL") {
        const lbl = root.querySelector("[data-pe-filter='stat'][data-pe-value='" + state.stat + "']");
        bits.push(lbl ? lbl.textContent.trim() : state.stat);
      }
      if (state.conf !== "ALL") bits.push(state.conf === "3" ? "high confidence" : "medium+ confidence");
      summary.textContent = bits.join(" · ");
    }
  }

  root.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-pe-filter]");
    if (btn) {
      const group = btn.getAttribute("data-pe-filter");
      const value = btn.getAttribute("data-pe-value");
      setPill(group, value);
      apply();
      return;
    }
    if (ev.target.closest("[data-pe-reset]")) {
      setPill("team", "ALL");
      setPill("stat", "ALL");
      setPill("conf", "ALL");
      if (sortSel) sortSel.value = "priority";
      state.sort = "priority";
      apply();
    }
  });
  if (sortSel) sortSel.addEventListener("change", () => {
    state.sort = sortSel.value || "priority";
    apply();
  });
  apply();
})();
</script>
""".replace("__NS__", ns_js)

    css = """
<style>
.pe-shell { display: block; }
.pe-shell *, .pe-shell *::before, .pe-shell *::after { box-sizing: border-box; }
.pe-eyebrow { display:inline-flex; align-items:center; gap:8px; padding:6px 12px;
  border-radius:999px; background:rgba(59,130,246,0.12);
  border:1px solid rgba(59,130,246,0.25); color:#60a5fa;
  font-size:12px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; }

.pe-hero { background:#121929; border:1px solid #1e293b; border-radius:20px;
  padding:24px 24px 18px; margin-bottom:18px; box-shadow:0 16px 48px rgba(0,0,0,.35); }
.pe-hero h2 { margin:14px 0 6px; font-size:clamp(22px, 3.4vw, 28px);
  font-weight:800; color:#fff; letter-spacing:-0.01em; }
.pe-hero p  { margin:0; color:#94a3b8; font-size:14px; line-height:1.55; max-width:62ch; }

.pe-insights { display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));
  gap:12px; margin-top:18px; }
.pe-insight { background:#0f172a; border:1px solid #1e293b; border-radius:16px;
  padding:16px; position:relative; overflow:hidden; }
.pe-insight::before { content:""; position:absolute; left:0; top:0; bottom:0; width:4px;
  background:#3b82f6; }
.pe-insight-primary::before    { background:#3b82f6; }
.pe-insight-confidence::before { background:#22c55e; }
.pe-insight-matchup::before    { background:#f59e0b; }
.pe-insight-volatile::before   { background:#a855f7; }
.pe-insight-label { font-size:11px; font-weight:700; letter-spacing:.12em;
  text-transform:uppercase; color:#94a3b8; }
.pe-insight-value { margin-top:8px; font-size:30px; font-weight:800; color:#fff;
  letter-spacing:-0.02em; line-height:1; }
.pe-insight-unit  { margin-top:6px; font-size:12px; color:#cbd5f5; }
.pe-insight-player  { margin-top:10px; font-size:15px; font-weight:700; color:#e5edf7; }
.pe-insight-matchup { margin-top:2px; font-size:12px; color:#94a3b8; }

.pe-filterbar { display:flex; flex-direction:column; gap:10px;
  background:#0f172a; border:1px solid #1e293b; border-radius:16px;
  padding:14px 14px 10px; margin-bottom:18px; }
.pe-filter-row { display:flex; align-items:center; gap:10px; flex-wrap:nowrap;
  overflow-x:auto; -webkit-overflow-scrolling:touch; padding-bottom:2px; }
.pe-filter-row::-webkit-scrollbar { height:6px; }
.pe-filter-row::-webkit-scrollbar-thumb { background:#1e293b; border-radius:3px; }
.pe-filter-key { font-size:11px; font-weight:700; letter-spacing:.1em;
  text-transform:uppercase; color:#64748b; flex-shrink:0; min-width:74px; }
.pe-pillset { display:flex; gap:6px; flex-wrap:nowrap; }
.pe-pill { appearance:none; border:1px solid #1e293b; background:#121929;
  color:#94a3b8; font-size:13px; font-weight:600; padding:6px 12px; border-radius:999px;
  cursor:pointer; white-space:nowrap; transition: background .15s, color .15s, border-color .15s; }
.pe-pill:hover { color:#e5edf7; border-color:#3b82f6; }
.pe-pill.is-active { background:#3b82f6; color:#fff; border-color:#3b82f6;
  box-shadow:0 6px 18px rgba(59,130,246,.32); }
.pe-filter-tools { display:flex; align-items:center; gap:10px; flex-wrap:wrap;
  border-top:1px solid #1e293b; padding-top:10px; margin-top:4px; }
.pe-sort { display:inline-flex; align-items:center; gap:8px; font-size:12px;
  color:#94a3b8; }
.pe-sort span { letter-spacing:.1em; text-transform:uppercase; font-weight:700; }
.pe-sort select { appearance:none; background:#121929; color:#e5edf7;
  border:1px solid #1e293b; border-radius:10px; padding:6px 28px 6px 10px;
  font-size:13px; font-weight:600; }
.pe-reset { appearance:none; background:transparent; border:1px solid #1e293b;
  color:#94a3b8; padding:6px 12px; border-radius:10px; font-size:12px;
  font-weight:600; cursor:pointer; letter-spacing:.04em; }
.pe-reset:hover { color:#e5edf7; border-color:#3b82f6; }
.pe-summary { margin:0; color:#94a3b8; font-size:12px; }

.pe-section { margin-bottom:20px; }
.pe-section[hidden] { display:none; }
.pe-section-head { display:flex; align-items:baseline; justify-content:space-between;
  margin-bottom:10px; gap:14px; flex-wrap:wrap; }
.pe-section-head h3 { margin:0; font-size:18px; font-weight:800; color:#fff;
  letter-spacing:-0.01em; }
.pe-section-head p  { margin:0; color:#64748b; font-size:13px; }

.pe-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); gap:14px; }

.pe-card { background:#121929; border:1px solid #1e293b; border-radius:18px;
  padding:18px 18px 16px; display:flex; flex-direction:column; gap:14px;
  position:relative; transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease; }
.pe-card[hidden] { display:none; }
.pe-card:hover { transform: translateY(-2px); border-color:#324a76; box-shadow:0 18px 36px rgba(0,0,0,.45); }
.pe-card::before { content:""; position:absolute; left:0; top:14px; bottom:14px;
  width:3px; border-radius:3px; background:#1e293b; }
.pe-card-band-elite::before    { background:linear-gradient(180deg, #60a5fa, #3b82f6); }
.pe-card-band-strong::before   { background:#3b82f6; }
.pe-card-band-standard::before { background:#1e293b; }

.pe-card-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
.pe-card-player { font-size:17px; font-weight:800; color:#fff;
  letter-spacing:-0.01em; line-height:1.2; }
.pe-card-matchup { font-size:12px; color:#94a3b8; margin-top:2px; }
.pe-card-conf { display:inline-flex; align-items:center; gap:6px; font-size:11px;
  font-weight:700; letter-spacing:.1em; text-transform:uppercase; padding:5px 10px;
  border-radius:999px; background:rgba(148,163,184,.1); color:#cbd5f5;
  border:1px solid rgba(148,163,184,.2); white-space:nowrap; flex-shrink:0; }
.pe-card-conf-elite { background:rgba(34,197,94,.12); color:#86efac;
  border-color:rgba(34,197,94,.3); }
.pe-card-conf-strong { background:rgba(59,130,246,.12); color:#93c5fd;
  border-color:rgba(59,130,246,.3); }
.pe-conf-dot { width:7px; height:7px; border-radius:50%; background:currentColor; }

.pe-card-meta { display:flex; gap:8px; flex-wrap:wrap; }
.pe-meta-chip { font-size:11px; font-weight:700; color:#cbd5f5;
  background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08);
  padding:4px 10px; border-radius:999px; letter-spacing:.02em; }
.pe-meta-chip-accent { background:rgba(59,130,246,.1); color:#93c5fd;
  border-color:rgba(59,130,246,.22); }

.pe-tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(120px, 1fr)); gap:10px; }
.pe-tile { background:rgba(15,23,42,.6); border:1px solid #1e293b; border-radius:12px;
  padding:12px 14px; display:flex; flex-direction:column; gap:8px; min-height:96px; }
.pe-tile[hidden] { display:none; }
.pe-tile-label { font-size:10px; font-weight:700; letter-spacing:.12em;
  text-transform:uppercase; color:#64748b; }
.pe-tile-value { font-size:24px; font-weight:800; color:#fff;
  line-height:1; letter-spacing:-0.02em; }
.pe-tile-prob { display:flex; align-items:baseline; justify-content:space-between;
  gap:6px; font-size:11px; font-weight:600; color:#cbd5f5; }
.pe-tile-prob-label { color:#64748b; font-weight:600; letter-spacing:.02em; }
.pe-tile-prob-value { font-weight:800; color:#cbd5f5; font-size:13px; }
.pe-tile-prob-good   .pe-tile-prob-value { color:#fbbf24; }
.pe-tile-prob-strong .pe-tile-prob-value { color:#86efac; }
.pe-tile-range { display:flex; align-items:baseline; justify-content:space-between;
  gap:6px; margin-top:auto; padding-top:6px;
  border-top:1px dashed rgba(148,163,184,.12);
  font-size:10px; font-weight:600; }
.pe-tile-range-label { color:#64748b; letter-spacing:.06em; }
.pe-tile-range-value { color:#93c5fd; font-weight:700; }

@media (max-width: 720px) {
  .pe-hero { padding:18px; border-radius:16px; }
  .pe-insights { grid-template-columns:1fr 1fr; gap:10px; }
  .pe-insight { padding:12px; }
  .pe-insight-value { font-size:24px; }
  .pe-filter-key { min-width:60px; font-size:10px; }
  .pe-filterbar { padding:12px 10px; border-radius:14px; }
  .pe-grid { grid-template-columns:1fr; gap:12px; }
  .pe-card { padding:14px; border-radius:14px; }
  .pe-card-player { font-size:16px; }
  .pe-tiles { grid-template-columns:1fr 1fr; gap:10px; }
  .pe-tile { padding:10px 12px; min-height:84px; gap:6px; }
  .pe-tile-value { font-size:20px; }
  .pe-tile-prob-value { font-size:12px; }
  .pe-tile-range { font-size:9px; padding-top:5px; }
}
@media (max-width: 420px) {
  .pe-insights { grid-template-columns:1fr; }
}
.pe-empty .pe-empty-card { background:#121929; border:1px solid #1e293b;
  border-radius:18px; padding:32px; text-align:center; }
.pe-empty h2 { color:#fff; margin:12px 0 8px; }
.pe-empty p  { color:#94a3b8; margin:0; }
</style>
"""

    hero = (
        "<section class='pe-hero'>"
        f"  <div class='pe-eyebrow'>{sport_display} · Projection Explorer</div>"
        "  <h2>Premium player intelligence, simulated daily.</h2>"
        f"  <p>Top AI-driven insights, grouped by player so each name appears "
        "     once with every modeled stat, confidence band, and matchup edge "
        "     in view. Filter by team or market to narrow the slate.</p>"
        f"  {insight_html}"
        "</section>"
    )

    return (
        css
        + f"<section class='pe-shell' data-pe-ns='{escape(ns)}'>"
        + hero
        + filter_html
        + cards_block
        + "</section>"
        + script
    )
