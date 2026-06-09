"""Public-facing tier mappings for SEO pages.

These helpers convert exact premium model outputs (probabilities, projections,
simulation percentages) into coarse, public-safe outlook tiers. They never
expose the underlying numbers, but keep the public pages useful enough to rank
in search. Premium model outputs stay behind the paywall.

This module has no dependencies on the rest of the webapp so it can be imported
from both ``app.py`` and the per-sport view modules.
"""

from __future__ import annotations

import bisect
from html import escape


# --- Reusable tier mappings -------------------------------------------------

# Probability (0-100) -> outlook tier. Highest threshold first.
PROBABILITY_TIERS = [
    (90.0, "Elite"),
    (75.0, "Strong"),
    (60.0, "Above Average"),
    (45.0, "Neutral"),
    (30.0, "Below Average"),
]
PROBABILITY_FLOOR_TIER = "Difficult"

# Percentile-within-slate (0-1) -> outlook tier for raw projection values.
PERCENTILE_TIERS = [
    (0.90, "Elite"),
    (0.70, "Strong"),
    (0.50, "Above Average"),
    (0.30, "Neutral"),
    (0.15, "Below Average"),
]
PERCENTILE_FLOOR_TIER = "Difficult"

# Premium-only items advertised in the locked sections.
PREMIUM_PLAYER_ITEMS = [
    "Exact probabilities",
    "Full projections",
    "Advanced simulations",
    "Daily premium boards",
    "Top Plays",
]
PREMIUM_GAME_ITEMS = [
    "Exact win probabilities",
    "Projected runs",
    "Simulation distributions",
    "Player projections",
    "Premium matchup analysis",
]
PREMIUM_PGA_ITEMS = [
    "Win probability",
    "Top 5 probability",
    "Top 10 probability",
    "Tournament projections",
    "Advanced simulation outputs",
]

OUTLOOK_CAPTION = "Model outlook tier"
CONTEXT_CAPTION = "Matchup context"

# Value-kind labels that are pure premium model output and must never appear on
# public pages, not even as a tier (raw projections, simulation percentiles,
# fantasy output, projected scores/finishes, etc.).
_PREMIUM_VALUE_TOKENS = (
    " p10", " p50", " p90", " std", "percentile", "sim ", "simulation",
    "floor", "ceiling", "fantasy", "plate appearance", "expected pa",
    "projected ip", " ip", " outs", "walk rate", "best over", "distribution",
    "scoreline", "projected total", "projected score", "projected runs",
    "projected finish", "total score", "round score", "birdies",
)

# Value-kind labels that are public context (not protected model projections):
# rendered with their literal label/value rather than a tier.
_CONTEXT_TOKENS = (
    "lineup spot", "rotation", "position", "status", "confidence", "tier",
)


def _coerce_float(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return None if number != number else number  # drop NaN
    text = str(value).strip().replace("%", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _as_percent(value):
    number = _coerce_float(value)
    if number is None:
        return None
    if abs(number) <= 1.0:
        number *= 100.0
    return number


def _norm_label(label):
    return " ".join(str(label or "").strip().lower().split())


def probability_tier(value):
    """Map a probability (0-1 or 0-100) to a public outlook tier."""
    pct = _as_percent(value)
    if pct is None:
        return None
    for threshold, tier in PROBABILITY_TIERS:
        if pct >= threshold:
            return tier
    return PROBABILITY_FLOOR_TIER


def team_outlook_tier(value):
    """Map a team win probability to a public team-outlook tier."""
    pct = _as_percent(value)
    if pct is None:
        return None
    if pct >= 65.0:
        return "Commanding"
    if pct >= 55.0:
        return "Favorable"
    if pct >= 48.0:
        return "Even"
    if pct >= 40.0:
        return "Slight Underdog"
    return "Underdog"


def value_distributions(records, group_keys):
    """Collect sorted numeric distributions per value-field label across a slate.

    Used to translate a raw projection into a percentile-based outlook tier
    without ever exposing the number itself.
    """
    distributions = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        for group_key in group_keys:
            for field in record.get(group_key, []) or []:
                if not isinstance(field, dict):
                    continue
                if field.get("kind") == "probability":
                    continue
                label = _norm_label(field.get("label"))
                if not label or is_premium_value(label) or is_context_value(label):
                    continue
                number = _coerce_float(field.get("value"))
                if number is None:
                    continue
                distributions.setdefault(label, []).append(number)
    for label in distributions:
        distributions[label].sort()
    return distributions


def _percentile_tier(rank):
    for threshold, tier in PERCENTILE_TIERS:
        if rank >= threshold:
            return tier
    return PERCENTILE_FLOOR_TIER


def value_tier(label, value, distributions):
    """Map a raw projection to a percentile-based outlook tier within the slate."""
    if not distributions:
        return None
    values = distributions.get(_norm_label(label))
    number = _coerce_float(value)
    if not values or number is None or len(values) < 4:
        return None
    rank = bisect.bisect_right(values, number) / len(values)
    return _percentile_tier(rank)


def is_premium_value(label):
    padded = " " + _norm_label(label) + " "
    return any(token in padded for token in _PREMIUM_VALUE_TOKENS)


def is_context_value(label):
    normalized = _norm_label(label)
    return any(token in normalized for token in _CONTEXT_TOKENS)


def outlook_label(label):
    """Rename an exact metric label to a public outlook label.

    "Hit Probability" -> "Hit Outlook"; "Projected Strikeouts" -> "Strikeouts
    Outlook"; "Win Probability" -> "Win Outlook".
    """
    text = " ".join(str(label or "").strip().split())
    lowered = text.lower()
    for suffix in (" probability", " prob", " %", " pct"):
        if lowered.endswith(suffix):
            text = text[: -len(suffix)]
            break
    for prefix in ("projected ", "model ", "sim "):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.strip().rstrip("%").strip()
    if not text:
        text = "Model"
    if not text.lower().endswith("outlook"):
        text = f"{text} Outlook"
    return text


def public_field(field, distributions=None):
    """Convert one profile field to a public-safe representation.

    Returns a dict with ``label``, ``tier``, ``kind`` and ``caption`` or
    ``None`` when the field is premium-only and must be hidden entirely.
    """
    if not isinstance(field, dict):
        return None
    label = " ".join(str(field.get("label") or "").strip().split())
    if not label:
        return None
    kind = field.get("kind")
    value = field.get("value")
    if kind == "probability":
        tier = probability_tier(value)
        if not tier:
            return None
        return {"label": outlook_label(label), "tier": tier, "kind": "outlook", "caption": OUTLOOK_CAPTION}
    if is_context_value(label):
        number = _coerce_float(value)
        lowered = _norm_label(label)
        # Never expose raw numeric model scores (confidence, etc.) or fractional
        # values. Integer context such as a lineup spot stays public.
        if number is not None and (
            "confidence" in lowered or "score" in lowered or number != int(number)
        ):
            return None
        display = field.get("display")
        text = display if display not in (None, "") else value
        if number is not None and number == int(number):
            text = str(int(number))
        text = " ".join(str(text or "").strip().split())
        if not text:
            return None
        return {"label": label, "tier": text, "kind": "context", "caption": CONTEXT_CAPTION}
    if is_premium_value(label):
        return None
    tier = value_tier(label, value, distributions)
    if not tier:
        return None
    return {"label": outlook_label(label), "tier": tier, "kind": "outlook", "caption": OUTLOOK_CAPTION}


def public_cards(fields, distributions=None):
    """Build (label, tier, caption) card tuples from profile fields, tier-safe."""
    cards = []
    for field in fields or []:
        public = public_field(field, distributions)
        if public:
            cards.append((public["label"], public["tier"], public["caption"]))
    return cards


def render_premium_locked_section(
    items,
    heading="Premium Members Unlock",
    note="Upgrade to EdgeRanked Premium for the exact model outputs behind these public outlooks.",
    cta_label="Unlock Premium",
    cta_href="/pricing",
):
    """Reusable premium-locked panel listing what members unlock."""
    list_items = "".join(f"<li>✓ {escape(str(item))}</li>" for item in items if item)
    return (
        "<section class='panel premium-locked'>"
        "<div class='panel-head'><div><div class='eyebrow'>Premium</div>"
        f"<h2>{escape(heading)}</h2></div>"
        f"<p class='muted'>{escape(note)}</p></div>"
        f"<ul class='premium-unlock-list'>{list_items}</ul>"
        f"<div class='cta-row'><a class='cta-btn primary' href='{escape(cta_href)}'>{escape(cta_label)}</a></div>"
        "</section>"
    )


# Group keys that may hold projection/probability fields across sports.
PROFILE_GROUP_KEYS = (
    "hitter_stats",
    "pitcher_stats",
    "stats",
    "probabilities",
    "confidence_fields",
)


def public_profiles_payload(payload):
    """Return a public-safe copy of a ``build_*_projection_profiles`` payload.

    Exact ``value``/``display`` fields and the ``*_object`` maps are stripped;
    each retained field becomes a coarse outlook tier. Premium-only fields are
    dropped entirely. Route/structure are preserved so the JSON API still
    returns 200 with useful, non-premium content.
    """
    if not isinstance(payload, dict):
        return payload
    records = payload.get("records") or []
    distributions = value_distributions(records, PROFILE_GROUP_KEYS)
    sanitized_records = []
    for record in records:
        if not isinstance(record, dict):
            sanitized_records.append(record)
            continue
        new_record = {}
        for key, value in record.items():
            if key in ("stats_object", "probabilities_object"):
                continue
            if key in PROFILE_GROUP_KEYS:
                continue
            new_record[key] = value
        outlooks = {}
        for group_key in PROFILE_GROUP_KEYS:
            if group_key not in record:
                continue
            public_fields = []
            for field in record.get(group_key) or []:
                public = public_field(field, distributions)
                if not public:
                    continue
                public_fields.append({
                    "label": public["label"],
                    "outlook": public["tier"],
                    "kind": public["kind"],
                })
                outlooks[public["label"]] = public["tier"]
            new_record[group_key] = public_fields
        new_record["outlooks"] = outlooks
        sanitized_records.append(new_record)
    sanitized = dict(payload)
    sanitized["records"] = sanitized_records
    sanitized["public_tiered"] = True
    return sanitized
