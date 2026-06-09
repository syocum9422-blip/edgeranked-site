"""
Scheduled paywall — soft gate (no silent sign-in redirect).

Activates only when ALL of the following are true:
  - PAYWALL_ENABLED env var is exactly "true" (case-insensitive).
  - PAYWALL_START_AT env var parses as ISO-8601 with timezone, AND now >= start.
  - request.path matches one of PAYWALL_GATED_PATTERNS regexes (CSV).
  - request.path is NOT in the hardcoded public allowlist.

When active for a gated request:
  - Anonymous users (HTML)             → 200 + premium gate page rendered by
                                          render_premium_gate(is_logged_in=False)
                                          with CTA "Create Account & Unlock
                                          Premium" -> /sign-up?next=<path>.
  - Anonymous users (/api/* paths)     → JSON 401 {"error":"Authentication
                                          required", "code":"unauthenticated"}.
  - Authenticated, no subscription (HTML) → 200 + premium gate page rendered
                                          by render_premium_gate(is_logged_in
                                          =True) with CTA "Upgrade to Premium"
                                          -> /start-checkout?next=<path>, which
                                          launches Stripe checkout and returns
                                          to <path> on success.
  - Authenticated, no subscription (/api/*) → JSON 402 {"error":"Subscription
                                          required", "code":"not_subscribed"}.
  - Active subscriber                  → allowed (return None).

The gate is served inline at the original URL (HTTP 200, no redirect) so the
user can refresh after subscribing and land back on the same premium page.
API contracts (401/402 JSON) are unchanged from the redirect era.

Fail-open on any internal exception so the paywall can never bring the site
down. Every decision logged at INFO/WARNING with the path and reason; never
logs tokens, payloads, or secrets.

Killswitch order: PAYWALL_ENABLED=false  →  paywall fully off, even if start
time has elapsed. Set PAYWALL_GATED_PATTERNS empty to gate nothing while
keeping the hook running for log visibility.
"""

import logging
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote

from flask import Response, jsonify, request

LOGGER = logging.getLogger(__name__)


# --- Configuration parsed once at import time --------------------------------

def _parse_bool(value):
    return str(value or "").strip().lower() in ("true", "1", "yes", "on")


def _parse_iso_dt(value):
    s = (value or "").strip()
    if not s:
        return None
    # datetime.fromisoformat handles offsets and "Z" since Python 3.11.
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError) as exc:
        LOGGER.warning(
            "PAYWALL_START_AT could not be parsed (%s); treating as unset",
            type(exc).__name__,
        )
        return None


def _compile_patterns(value):
    patterns = []
    for raw in (value or "").split(","):
        s = raw.strip()
        if not s:
            continue
        try:
            patterns.append(re.compile(s))
        except re.error as exc:
            LOGGER.warning(
                "PAYWALL_GATED_PATTERNS skipping bad regex %r (%s)",
                s, type(exc).__name__,
            )
    return patterns


PAYWALL_ENABLED = _parse_bool(os.environ.get("PAYWALL_ENABLED"))
PAYWALL_START_AT = _parse_iso_dt(os.environ.get("PAYWALL_START_AT"))
_GATED_PATTERNS = _compile_patterns(os.environ.get("PAYWALL_GATED_PATTERNS"))


# Public always — never gated regardless of activation state. Exact paths and
# directory prefixes only; no regex to keep the hot path obvious and fast.
_PUBLIC_EXACT = frozenset({
    "/", "/about",
    "/pricing", "/plans", "/subscribe", "/membership", "/waitlist",
    "/account", "/sign-in", "/sign-up", "/sign-out",
    "/privacy-policy", "/privacy", "/terms", "/disclaimer",
    "/results", "/results/raw",
    "/homepage-preview",
    "/mlb", "/nba", "/wnba", "/pga", "/ufc", "/soccer",
    "/mlb-preview", "/nba-preview", "/wnba-preview",
    "/mlb/weather", "/api/mlb/weather",
    "/mlb/intel", "/mlb/intel-preview", "/mlb/matchup-history",
    "/mlb/results", "/mlb/stadiums",
    "/sitemap.xml", "/robots.txt",
    "/sitemap_mlb_players.xml",
    "/sitemap_mlb_games.xml",
    "/sitemap_nba_players.xml",
    "/sitemap_wnba_players.xml",
    "/sitemap_pga_golfers.xml",
    "/api/health",
    "/api/stripe/config",
    "/api/stripe/create-checkout",
    "/api/stripe/create-portal",
    "/api/stripe/subscription",
    "/api/auth/me",
    "/webhooks/stripe", "/webhooks/clerk",
})

_PUBLIC_PREFIXES = (
    "/static/",
    "/brand/",
    "/mlb/results/",
    "/mlb/stadium/",
    "/mlb/player/",
    "/mlb/game/",
    "/nba/player/",
    "/wnba/player/",
    "/pga/golfer/",
)


def _is_public(path):
    if path in _PUBLIC_EXACT:
        return True
    for pref in _PUBLIC_PREFIXES:
        if path.startswith(pref):
            return True
    return False


def _is_gated(path):
    return any(p.search(path) for p in _GATED_PATTERNS)


def _paywall_active(now=None):
    if not PAYWALL_ENABLED:
        return False
    if PAYWALL_START_AT is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    return now >= PAYWALL_START_AT


# --- Subscription check (per request) ----------------------------------------

def _has_active_subscription(clerk_user_id):
    """Check users.subscription_status='active' with optional period_end guard."""
    try:
        from auth_system.models import User  # local import to avoid cycles
    except Exception:
        LOGGER.warning("paywall: could not import User model")
        return False
    user = User.query.filter_by(clerk_user_id=clerk_user_id).first()
    if not user:
        return False
    # "trialing" grants the same premium access as "active" (3-day free trial).
    if user.subscription_status not in ("active", "trialing"):
        return False
    end = user.subscription_current_period_end
    if end is not None:
        # Match stripe_integration.check_subscription_status semantics.
        try:
            now = datetime.now(end.tzinfo) if end.tzinfo else datetime.now(timezone.utc)
            if end < now:
                return False
        except Exception:
            pass
    return True


# --- Hook registration -------------------------------------------------------

_SPORT_PREVIEW_MAP = (
    ("/mlb", "/mlb-preview", "MLB"),
    ("/nba", "/nba-preview", "NBA"),
    ("/wnba", "/wnba-preview", "WNBA"),
)


def _preview_link_for(path):
    """Return (href, label) for the public preview that matches `path`, or None."""
    for prefix, preview_path, sport_label in _SPORT_PREVIEW_MAP:
        if path == prefix or path.startswith(prefix + "/"):
            return preview_path, f"View Free {sport_label} Preview"
    return None


def _html_escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def render_premium_gate(path, *, is_logged_in, has_active_subscription=False,
                        premium_required=True):
    """Render the reusable premium-gate HTML page.

    Exposed as a helper so other parts of the Flask webapp can render the same
    soft-gate card without going through the paywall hook. Subscribed users
    short-circuit to `None` so callers can fall through to real content.
    """
    if has_active_subscription and premium_required:
        return None

    safe_next = quote(path or "/")
    if is_logged_in:
        # Drop the logged-in unsubscribed user straight into the Stripe
        # checkout launcher so the original premium destination survives the
        # round-trip; success_url brings them back to <path> via /account.
        cta_href = f"/start-checkout?next={safe_next}"
        cta_label = "Upgrade to Premium"
        secondary_href = "/pricing"
        secondary_label = "See Pricing Details"
    else:
        cta_href = f"/sign-up?next={safe_next}"
        cta_label = "Create Account &amp; Unlock Premium"
        secondary_href = f"/sign-in?next={safe_next}"
        secondary_label = "I already have an account"

    preview = _preview_link_for(path or "")
    preview_html = ""
    if preview:
        preview_href, preview_label = preview
        preview_html = (
            f'<a class="er-gate-link" href="{_html_escape(preview_href)}">'
            f'{_html_escape(preview_label)} &rarr;</a>'
        )

    path_label = _html_escape(path or "/")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>Premium Access Required · EdgeRankedSportsAI</title>
  <style>
    *,*::before,*::after {{ box-sizing: border-box; }}
    html,body {{ margin: 0; padding: 0; background: #0a0f1c; color: #e5edf7;
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont,
      "Segoe UI", sans-serif; min-height: 100%; }}
    body {{ min-height: 100vh; display: flex; flex-direction: column; }}
    .er-gate-topbar {{ padding: 18px 24px; border-bottom: 1px solid #1e293b;
      display: flex; align-items: center; justify-content: space-between; }}
    .er-gate-brand {{ font-weight: 800; letter-spacing: -0.01em; color: #fff;
      text-decoration: none; font-size: 16px; }}
    .er-gate-brand span {{ color: #60a5fa; }}
    .er-gate-topnav a {{ color: #94a3b8; text-decoration: none; font-size: 14px;
      margin-left: 18px; }}
    .er-gate-topnav a:hover {{ color: #e5edf7; }}
    .er-gate-shell {{ flex: 1; display: flex; align-items: center;
      justify-content: center; padding: 48px 20px; }}
    .er-gate-card {{ width: min(560px, 100%); background: #121929;
      border: 1px solid #1e293b; border-radius: 20px; padding: 40px;
      box-shadow: 0 24px 60px rgba(0,0,0,0.45); text-align: center; }}
    .er-gate-kicker {{ display: inline-flex; align-items: center; gap: 8px;
      padding: 6px 14px; border-radius: 999px;
      background: rgba(59, 130, 246, 0.12);
      border: 1px solid rgba(59, 130, 246, 0.25); color: #60a5fa;
      font-size: 12px; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.1em; }}
    .er-gate-lock {{ width: 18px; height: 18px; }}
    .er-gate-headline {{ margin: 18px 0 12px; font-size: clamp(26px, 4vw, 32px);
      font-weight: 800; color: #fff; letter-spacing: -0.02em; }}
    .er-gate-copy {{ margin: 0 0 24px; color: #94a3b8; font-size: 16px;
      line-height: 1.55; }}
    .er-gate-price {{ background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08); border-radius: 14px;
      padding: 18px 16px; margin-bottom: 28px; }}
    .er-gate-price-amount {{ font-size: 28px; font-weight: 800; color: #fff;
      letter-spacing: -0.01em; }}
    .er-gate-price-amount small {{ font-size: 14px; font-weight: 600;
      color: #94a3b8; margin-left: 4px; }}
    .er-gate-price-note {{ display: block; margin-top: 6px; color: #cbd5f5;
      font-size: 13px; font-weight: 600; letter-spacing: 0.02em; }}
    .er-gate-actions {{ display: flex; flex-direction: column; gap: 12px; }}
    .er-gate-primary, .er-gate-secondary {{ display: inline-flex;
      align-items: center; justify-content: center; height: 48px;
      padding: 0 22px; border-radius: 12px; font-weight: 700; font-size: 15px;
      text-decoration: none; transition: transform .15s ease, background .15s ease,
      color .15s ease, border-color .15s ease; }}
    .er-gate-primary {{ background: #3b82f6; color: #fff;
      box-shadow: 0 12px 28px rgba(59, 130, 246, 0.32); }}
    .er-gate-primary:hover {{ background: #2563eb; transform: translateY(-1px); }}
    .er-gate-secondary {{ background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.10); color: #cbd5f5; }}
    .er-gate-secondary:hover {{ background: rgba(255,255,255,0.08);
      color: #fff; }}
    .er-gate-link {{ display: inline-block; margin-top: 18px; color: #60a5fa;
      text-decoration: none; font-size: 14px; font-weight: 600; }}
    .er-gate-link:hover {{ color: #93c5fd; }}
    .er-gate-meta {{ margin-top: 22px; color: #64748b; font-size: 12px;
      letter-spacing: 0.02em; }}
    .er-gate-meta code {{ background: rgba(255,255,255,0.05); padding: 2px 6px;
      border-radius: 6px; color: #cbd5f5; }}
  </style>
</head>
<body>
  <header class="er-gate-topbar">
    <a class="er-gate-brand" href="/">EdgeRanked<span>SportsAI</span></a>
    <nav class="er-gate-topnav">
      <a href="/pricing">Pricing</a>
      <a href="/about">About</a>
    </nav>
  </header>
  <main class="er-gate-shell">
    <section class="er-gate-card" role="dialog" aria-labelledby="er-gate-title">
      <div class="er-gate-kicker">
        <svg class="er-gate-lock" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2" stroke-linecap="round"
             stroke-linejoin="round" aria-hidden="true">
          <rect x="3" y="11" width="18" height="11" rx="2"/>
          <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
        </svg>
        Premium Members Only
      </div>
      <h1 id="er-gate-title" class="er-gate-headline">Premium Access Required</h1>
      <p class="er-gate-copy">
        Full projections, simulations, matchup breakdowns, and daily model
        updates require an active EdgeRanked Premium subscription.
      </p>
      <div class="er-gate-price" aria-label="Subscription pricing">
        <div class="er-gate-price-amount">$19.99<small>/month</small></div>
        <span class="er-gate-price-note">Cancel anytime.</span>
      </div>
      <div class="er-gate-actions">
        <a class="er-gate-primary" href="{_html_escape(cta_href)}">{cta_label}</a>
        <a class="er-gate-secondary" href="{_html_escape(secondary_href)}">{_html_escape(secondary_label)}</a>
      </div>
      {preview_html}
      <div class="er-gate-meta">
        Requested page: <code>{path_label}</code>
      </div>
    </section>
  </main>
</body>
</html>"""


def _gate_response(path, reason):
    is_api = path.startswith("/api/")
    if reason == "unauthenticated":
        if is_api:
            LOGGER.info("paywall: 401 path=%s reason=%s", path, reason)
            return jsonify({"error": "Authentication required",
                            "code": "unauthenticated"}), 401
        LOGGER.info("paywall: soft-gate path=%s reason=%s", path, reason)
        html = render_premium_gate(path, is_logged_in=False,
                                   has_active_subscription=False)
        return Response(html, status=200, mimetype="text/html")
    if reason == "not_subscribed":
        if is_api:
            LOGGER.info("paywall: 402 path=%s reason=%s", path, reason)
            return jsonify({"error": "Subscription required",
                            "code": "not_subscribed"}), 402
        LOGGER.info("paywall: soft-gate path=%s reason=%s", path, reason)
        html = render_premium_gate(path, is_logged_in=True,
                                   has_active_subscription=False)
        return Response(html, status=200, mimetype="text/html")
    return None


def register_paywall(flask_app, _db_unused=None):
    """Install the before_request paywall hook on the given Flask app.

    The _db_unused arg is accepted for symmetry with register_clerk_webhook,
    so callers can wire all auth_system hooks the same way. The paywall does
    not need a db handle — it queries via the SQLAlchemy session inside the
    User model.
    """
    LOGGER.info(
        "paywall: registering hook (enabled=%s start_at=%s patterns=%d)",
        PAYWALL_ENABLED,
        PAYWALL_START_AT.isoformat() if PAYWALL_START_AT else "<unset>",
        len(_GATED_PATTERNS),
    )

    @flask_app.before_request
    def _paywall_before_request():
        # Hard fail-open envelope: any internal error allows the request.
        try:
            method = request.method
            if method == "OPTIONS":
                return None
            if not _paywall_active():
                return None
            path = request.path
            if _is_public(path):
                return None
            if not _is_gated(path):
                return None

            # Gated path + paywall active: identify the user. get_clerk_user_id
            # checks the signed edgeranked_session bridge cookie (HTML) and
            # the Authorization header (API XHR/fetch) — no fail-open paths.
            from auth_system.auth import get_clerk_user_id
            user_id = get_clerk_user_id()
            if not user_id:
                LOGGER.info(
                    "paywall: deny path=%s has_user=no has_authorization_header=%s "
                    "has_edgeranked_session=%s",
                    path,
                    bool(request.headers.get("Authorization", "")),
                    bool(request.cookies.get("edgeranked_session", "")),
                )
                return _gate_response(path, "unauthenticated")
            if not _has_active_subscription(user_id):
                LOGGER.info(
                    "paywall: deny path=%s has_user=yes reason=not_subscribed "
                    "clerk_user_id=%s", path, user_id,
                )
                return _gate_response(path, "not_subscribed")

            LOGGER.info("paywall: allow path=%s clerk_user_id=%s", path, user_id)
            return None
        except Exception:
            LOGGER.exception("paywall: hook error — failing open")
            return None
