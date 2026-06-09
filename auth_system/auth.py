"""
Authentication module using Clerk.
Provides email/password and Google OAuth login.
"""

import logging
import os
import time
from functools import wraps
from urllib.request import urlopen

import jwt
from flask import current_app, jsonify, make_response, request, session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

LOGGER = logging.getLogger(__name__)

# --- EdgeRanked app-session bridge cookie -----------------------------------
# Signed cookie issued by /api/auth/session after we verify a Clerk JWT.
# Subsequent HTML page loads (which cannot send an Authorization header) carry
# this cookie, so the paywall can identify the user without ever trusting
# Clerk's own short-lived __session cookie server-side.
APP_SESSION_COOKIE_NAME = "edgeranked_session"
APP_SESSION_MAX_AGE = 7 * 24 * 60 * 60  # 7 days
_APP_SESSION_SALT = "edgeranked-app-session-v1"


def _app_session_serializer():
    secret = (
        current_app.config.get("SECRET_KEY")
        if current_app
        else None
    ) or os.environ.get("SECRET_KEY", "")
    if not secret:
        raise RuntimeError("SECRET_KEY not configured for app session signing")
    return URLSafeTimedSerializer(secret, salt=_APP_SESSION_SALT)


def _read_app_session_cookie():
    raw = request.cookies.get(APP_SESSION_COOKIE_NAME, "")
    if not raw:
        return None
    try:
        data = _app_session_serializer().loads(raw, max_age=APP_SESSION_MAX_AGE)
    except SignatureExpired:
        LOGGER.info("edgeranked_session: expired")
        return None
    except BadSignature:
        LOGGER.warning("edgeranked_session: bad signature")
        return None
    except Exception as exc:
        LOGGER.warning("edgeranked_session: load error %s", type(exc).__name__)
        return None
    if not isinstance(data, dict):
        return None
    return data


def get_app_session_clerk_user_id():
    """Return clerk_user_id from a valid edgeranked_session cookie, or None."""
    data = _read_app_session_cookie()
    if not data:
        return None
    return data.get("clerk_user_id") or None


def set_app_session_cookie(response, clerk_user_id):
    """Set the signed edgeranked_session cookie on the given response."""
    if not clerk_user_id:
        return response
    payload = {"clerk_user_id": clerk_user_id, "iat": int(time.time())}
    token = _app_session_serializer().dumps(payload)
    response.set_cookie(
        APP_SESSION_COOKIE_NAME,
        token,
        max_age=APP_SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="Lax",
        path="/",
    )
    return response


def create_app_session_cookie_response(clerk_user_id, body=None, status=200):
    """Build a JSON response that also installs the app-session cookie."""
    resp = make_response(jsonify(body if body is not None else {"ok": True}), status)
    set_app_session_cookie(resp, clerk_user_id)
    return resp


def clear_app_session_cookie(response):
    """Expire the edgeranked_session cookie on the given response."""
    response.set_cookie(
        APP_SESSION_COOKIE_NAME,
        "",
        expires=0,
        max_age=0,
        httponly=True,
        secure=True,
        samesite="Lax",
        path="/",
    )
    return response

# Clerk configuration from environment
CLERK_PUBLISHABLE_KEY = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
CLERK_SECRET_KEY = os.environ.get("CLERK_SECRET_KEY", "")
CLERK_API_URL = os.environ.get("CLERK_API_URL", "https://api.clerk.dev/v1")
CLERK_JWT_AUDIENCE = os.environ.get("CLERK_JWT_AUDIENCE", "")  # default empty: no aud check
CLERK_JWT_ISSUER = os.environ.get("CLERK_JWT_ISSUER", "")
CLERK_JWKS_URL = os.environ.get("CLERK_JWKS_URL") or (
    f"{CLERK_JWT_ISSUER.rstrip('/')}/.well-known/jwks.json" if CLERK_JWT_ISSUER else ""
)
_CLERK_AUTHORIZED_PARTIES = {
    p.strip() for p in os.environ.get("CLERK_AUTHORIZED_PARTIES", "").split(",") if p.strip()
}

# JWKS client (PyJWT >=2.x). Constructor does not fetch; first
# get_signing_key_from_jwt() call lazily fetches and caches.
_jwks_client = jwt.PyJWKClient(CLERK_JWKS_URL, cache_keys=True, lifespan=600) if CLERK_JWKS_URL else None

# Protected routes that require authentication
PROTECTED_ROUTES = {
    "/mlb",
    "/mlb/best-bets",
    "/mlb/pitcher-strikeouts",
    "/mlb/hitter-board",
    "/mlb/projections",
    "/mlb/two-plus-hits",
    "/mlb/two-plus-bases",
    "/mlb/rbi-targets",
    "/mlb/hr-targets",
    "/mlb/stolen-bases",
    "/mlb/hitter-strikeouts",
    "/mlb/history",
    "/mlb/graded",
    "/mlb/record",
    "/mlb/lines",
    "/mlb/injuries",
    "/nba",
    "/nba/best-bets",
    "/nba/projections",
}


def _verify_clerk_jwt(token):
    """Verify a Clerk session JWT (RS256 + JWKS + issuer + optional aud + azp).

    Returns the user_id (sub claim) on success, or None on any failure. All
    rejection reasons logged at WARNING with exception class only — never the
    token bytes or payload.
    """
    if not token:
        return None
    if not _jwks_client or not CLERK_JWT_ISSUER:
        LOGGER.warning(
            "Clerk JWT verifier not configured (CLERK_JWT_ISSUER/CLERK_JWKS_URL)",
        )
        return None
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=CLERK_JWT_ISSUER,
            audience=CLERK_JWT_AUDIENCE or None,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
        if _CLERK_AUTHORIZED_PARTIES:
            azp = payload.get("azp", "")
            if azp and azp not in _CLERK_AUTHORIZED_PARTIES:
                LOGGER.warning("Clerk JWT azp not authorized: azp=%s", azp)
                return None
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        LOGGER.warning("Clerk JWT rejected: ExpiredSignatureError")
    except jwt.PyJWKClientError as e:
        LOGGER.warning("Clerk JWKS lookup failed: %s", type(e).__name__)
    except jwt.InvalidTokenError as e:
        LOGGER.warning("Clerk JWT rejected: %s", type(e).__name__)
    return None


def get_clerk_user_id():
    """
    Extract and verify the current user's Clerk ID. Sources tried in order:
      1. Flask server-side session (legacy).
      2. EdgeRanked app-session bridge cookie (edgeranked_session). Set by
         /api/auth/session after a successful Clerk JWT verification, this is
         the canonical identifier on HTML page navigations.
      3. Authorization: Bearer header (frontend XHR / fetch).

    Returns user_id if valid, None otherwise.
    """
    # 1. Server-side session (legacy).
    if session.get("user_id"):
        return session.get("user_id")

    # 2. EdgeRanked signed bridge cookie — primary source for HTML page loads.
    bridged = get_app_session_clerk_user_id()
    if bridged:
        return bridged

    # 3. Authorization header (Bearer token) — frontend XHR/fetch flows.
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        sub = _verify_clerk_jwt(auth_header[7:])
        if sub:
            return sub

    return None


def has_clerk_session_cookie():
    """Return True when the request carries a non-empty Clerk __session cookie.

    Used by the paywall to distinguish "anonymous visitor" (no cookie) from
    "browser claims to be signed in but cookie failed verification" (typically
    a transient short-lived token expiry that the frontend Clerk-js will
    refresh on the next page load). Does NOT verify the cookie.
    """
    try:
        return bool(request.cookies.get("__session", ""))
    except Exception:
        return False


def login_required(f):
    """
    Decorator to protect routes requiring authentication.
    Usage:
        @app.get("/mlb")
        @login_required
        def mlb_home():
            return "Protected content"
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = get_clerk_user_id()
        if not user_id:
            # Check if it's an API request or HTML request
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            # Redirect to sign-in for HTML requests
            return _build_sign_in_redirect(request.path)
        return f(*args, **kwargs)
    return decorated_function


def subscription_required(f):
    """
    Decorator to protect routes requiring active subscription.
    Must be used after @login_required.
    Usage:
        @app.get("/mlb/best-bets")
        @login_required
        @subscription_required
        def mlb_best_bets():
            return "Premium content"
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = get_clerk_user_id()
        if not user_id:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return _build_sign_in_redirect(request.path)

        # Check subscription status via Stripe
        from auth_system.stripe_integration import check_subscription_status
        if not check_subscription_status(user_id):
            return _build_upgrade_redirect(request.path)
        return f(*args, **kwargs)
    return decorated_function


def _build_sign_in_redirect(return_url):
    """Build redirect response to Clerk sign-in page."""
    sign_in_url = f"/sign-in?redirect_url={return_url}"
    from flask import redirect
    return redirect(sign_in_url)


def _build_upgrade_redirect(return_url):
    """Build redirect response to subscription page."""
    from flask import redirect
    return redirect(f"/upgrade?redirect_url={return_url}")


def register_auth_routes(flask_app):
    """
    Register all authentication routes on the Flask app.
    Call this from create_app() after the app is created.

    Routes registered:
    - /sign-in - Clerk sign-in page
    - /sign-up - Clerk sign-up page
    - /sign-out - Sign out handler
    - /api/auth/me - Get current user info
    - /api/auth/session - Verify session
    - /webhooks/clerk - Clerk webhooks (user created/deleted)
    """

    @flask_app.get("/sign-in")
    def sign_in():
        """Render Clerk sign-in component."""
        return _render_clerk_component("SignIn")

    @flask_app.get("/sign-up")
    def sign_up():
        """Render Clerk sign-up component."""
        return _render_clerk_component("SignUp")

    @flask_app.post("/sign-out")
    def sign_out():
        """Clear local session and redirect to Clerk sign-out."""
        session.clear()
        # Redirect to Clerk sign-out URL
        clerk_domain = os.environ.get("CLERK_DOMAIN", "your-app.clerk.accounts.dev")
        from flask import redirect
        return redirect(f"https://{clerk_domain}/sign-out?redirect_url=/")

    @flask_app.get("/api/auth/me")
    def auth_me():
        """Get current authenticated user info."""
        user_id = get_clerk_user_id()
        if not user_id:
            return jsonify({"authenticated": False}), 401

        # Get user details from Clerk
        user_info = _get_clerk_user(user_id)
        if not user_info:
            return jsonify({"error": "User not found"}), 404

        # Get subscription status
        from auth_system.stripe_integration import check_subscription_status
        is_subscribed = check_subscription_status(user_id)

        return jsonify({
            "authenticated": True,
            "user_id": user_id,
            "email": user_info.get("email_addresses", [{}])[0].get("email_address", ""),
            "first_name": user_info.get("first_name", ""),
            "last_name": user_info.get("last_name", ""),
            "subscribed": is_subscribed,
        })

    @flask_app.post("/api/auth/session")
    def auth_session():
        """Verify and refresh session from Clerk."""
        # This endpoint is called by the frontend to sync Clerk session
        clerk_session_token = request.json.get("session_token") if request.is_json else None
        if not clerk_session_token:
            return jsonify({"error": "Session token required"}), 400

        try:
            payload = jwt.decode(
                clerk_session_token,
                CLERK_SECRET_KEY,
                algorithms=["HS256"],
                audience=CLERK_JWT_AUDIENCE,
            )
            user_id = payload.get("sub")
            if user_id:
                session["user_id"] = user_id
                return jsonify({"success": True, "user_id": user_id})
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Session expired"}), 401
        except jwt.InvalidTokenError as e:
            return jsonify({"error": f"Invalid token: {e}"}), 401

        return jsonify({"error": "Invalid session"}), 401

    @flask_app.post("/webhooks/clerk")
    def clerk_webhook():
        """
        Handle Clerk webhooks for user lifecycle events.
        - user.created: Initialize user in database
        - user.deleted: Clean up user data
        """
        import json
        from flask import request

        # Verify webhook signature. Fail closed if the signing secret is absent.
        webhook_secret = os.environ.get("CLERK_WEBHOOK_SECRET", "")
        if not webhook_secret:
            LOGGER.error("Clerk webhook signing secret is not configured")
            return jsonify({"error": "Webhook signing secret not configured"}), 503
        from auth_system.clerk_webhook import verify_clerk_signature
        if not verify_clerk_signature(request, webhook_secret):
            return jsonify({"error": "Invalid signature"}), 401

        payload = request.get_json()
        if not payload:
            return jsonify({"error": "No payload"}), 400

        event_type = payload.get("type", "")
        data = payload.get("data", {})

        if event_type == "user.created":
            _handle_user_created(data)
        elif event_type == "user.deleted":
            _handle_user_deleted(data)

        return jsonify({"received": True})


def _render_clerk_component(component_name):
    """Render Clerk component as HTML page."""
    publishable_key = CLERK_PUBLISHABLE_KEY

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>EdgeRanked - Sign In</title>
        <style>
            body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
            #clerk-container {{ padding: 40px 20px; }}
            #loading {{ text-align: center; padding: 40px; color: #666; }}
            #error {{ display: none; color: red; padding: 20px; text-align: center; background: #fee; margin: 20px; border-radius: 8px; }}
        </style>
    </head>
    <body>
        <div id="loading">Loading secure login...</div>
        <div id="error"></div>
        <div id="clerk-container"></div>
        <script src="https://cdn.jsdelivr.net/npm/@clerk/clerk-js@latest/dist/clerk.browser.min.js"></script>
        <script>
            window.addEventListener('load', async function() {{
                try {{
                    await window.Clerk.load({{ publishableKey: '{publishable_key}' }});
                    const container = document.getElementById('clerk-container');
                    document.getElementById('loading').style.display = 'none';
                    if ('{component_name}' === 'SignIn') {{
                        window.Clerk.mountSignIn(container, {{ afterSignInUrl: '/' }});
                    }} else if ('{component_name}' === 'SignUp') {{
                        window.Clerk.mountSignUp(container, {{ afterSignUpUrl: '/' }});
                    }}
                }} catch (err) {{
                    console.error('Clerk error:', err);
                    document.getElementById('loading').style.display = 'none';
                    const errorEl = document.getElementById('error');
                    errorEl.style.display = 'block';
                    errorEl.textContent = 'Failed to load Clerk: ' + err.message;
                }}
            }});
        </script>
    </body>
    </html>
    """
    from flask import Response
    return Response(html, mimetype="text/html")


def _get_clerk_user(user_id):
    """Fetch user details from Clerk API."""
    if not CLERK_SECRET_KEY or not user_id:
        return None

    import urllib.request
    import json

    try:
        req = urllib.request.Request(
            f"{CLERK_API_URL}/users/{user_id}",
            headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"}
        )
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        LOGGER.error(f"Failed to fetch Clerk user {user_id}: {e}")
        return None


def _handle_user_created(data):
    """Handle new user creation from Clerk webhook."""
    user_id = data.get("id")
    email_addresses = data.get("email_addresses") or []
    email = email_addresses[0].get("email_address", "") if email_addresses else ""
    first_name = data.get("first_name", "")
    last_name = data.get("last_name", "")

    LOGGER.info(
        "user.created extract: clerk_user_id=%s has_email=%s email_count=%s",
        user_id, bool(email), len(email_addresses),
    )

    if not user_id:
        LOGGER.warning("user.created skipped: missing data.id")
        return

    # Store user in local database for subscription tracking
    from auth_system.models import db, User
    with flask_app.app_context():
        existing = User.query.filter_by(clerk_user_id=user_id).first()
        if existing:
            LOGGER.info("user.created idempotent: row already exists for clerk_user_id=%s", user_id)
            return
        user = User(
            clerk_user_id=user_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        db.session.add(user)
        db.session.commit()
        LOGGER.info(
            "user.created committed: clerk_user_id=%s db_url=%s",
            user_id, str(db.engine.url),
        )


def _handle_user_deleted(data):
    """Handle user deletion from Clerk webhook."""
    user_id = data.get("id")
    LOGGER.info(f"User deleted: {user_id}")

    from auth_system.models import db, User
    with flask_app.app_context():
        user = User.query.filter_by(clerk_user_id=user_id).first()
        if user:
            db.session.delete(user)
            db.session.commit()


# Import db from models - will be set during registration
flask_app = None


def register_auth_routes_with_db(flask_app_instance, database):
    """
    Register auth routes with database access.
    Use this if you need database access in auth handlers.
    """
    global flask_app, db
    flask_app = flask_app_instance
    db = database
    register_auth_routes(flask_app_instance)


def register_clerk_webhook(flask_app_instance, database):
    """
    Register ONLY POST /webhooks/clerk.

    Used in production to wire the Clerk webhook without colliding with the
    /sign-in, /sign-up, /account routes already owned by
    nba_model/webapp/auth_views.py. Sets the module-level flask_app and db
    globals that _handle_user_created / _handle_user_deleted require.
    """
    global flask_app, db
    flask_app = flask_app_instance
    db = database

    @flask_app_instance.post("/webhooks/clerk")
    def clerk_webhook():
        webhook_secret = os.environ.get("CLERK_WEBHOOK_SECRET", "")
        if not webhook_secret:
            LOGGER.error("Clerk webhook signing secret is not configured")
            return jsonify({"error": "Webhook signing secret not configured"}), 503
        from auth_system.clerk_webhook import verify_clerk_signature
        if not verify_clerk_signature(request, webhook_secret):
            return jsonify({"error": "Invalid signature"}), 401

        payload = request.get_json()
        if not payload:
            return jsonify({"error": "No payload"}), 400

        event_type = payload.get("type", "")
        data = payload.get("data", {})

        LOGGER.info(
            "Clerk webhook received: type=%s data_id=%s data_keys=%s",
            event_type,
            data.get("id") if isinstance(data, dict) else None,
            sorted(data.keys()) if isinstance(data, dict) else None,
        )

        if event_type == "user.created":
            _handle_user_created(data)
        elif event_type == "user.deleted":
            _handle_user_deleted(data)
        else:
            LOGGER.info(
                "Clerk webhook ignored: type=%s not in {user.created,user.deleted}",
                event_type,
            )

        return jsonify({"received": True})


def register_auth_api(flask_app_instance):
    """
    Register ONLY GET /api/auth/me.

    Safe to call alongside register_clerk_webhook; does not register
    /sign-in, /sign-up, /sign-out, or /api/auth/session.
    """

    @flask_app_instance.get("/api/auth/me")
    def auth_me():
        user_id = get_clerk_user_id()
        if not user_id:
            return jsonify({"authenticated": False}), 401

        user_info = _get_clerk_user(user_id)
        if not user_info:
            return jsonify({"error": "User not found"}), 404

        from auth_system.stripe_integration import check_subscription_status
        is_subscribed = check_subscription_status(user_id)

        return jsonify({
            "authenticated": True,
            "user_id": user_id,
            "email": user_info.get("email_addresses", [{}])[0].get("email_address", ""),
            "first_name": user_info.get("first_name", ""),
            "last_name": user_info.get("last_name", ""),
            "subscribed": is_subscribed,
        })


def register_app_session_api(flask_app_instance):
    """Register the app-session bridge endpoints.

    POST /api/auth/session
        Authorization: Bearer <Clerk JWT>
        Verifies the Clerk token via RS256/JWKS, ensures a local users row
        exists, and installs the signed edgeranked_session cookie. Returns
        401 JSON on any verification failure. The cookie payload contains
        only clerk_user_id and an issued-at timestamp.

    POST /sign-out
        Clears the edgeranked_session cookie and the legacy Flask session,
        then redirects (303) to the homepage. Token-only; no body required.
    """

    @flask_app_instance.post("/api/auth/session")
    def auth_session_bridge():
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            LOGGER.info("auth_session: missing bearer")
            return jsonify({"ok": False, "error": "missing_bearer"}), 401

        token = auth_header[7:].strip()
        clerk_user_id = _verify_clerk_jwt(token)
        if not clerk_user_id:
            LOGGER.info("auth_session: clerk verification failed")
            return jsonify({"ok": False, "error": "invalid_token"}), 401

        # Ensure a local users row exists so paywall subscription lookups work.
        try:
            from auth_system.models import User, db as _db
            existing = User.query.filter_by(clerk_user_id=clerk_user_id).first()
            if not existing:
                user_info = _get_clerk_user(clerk_user_id) or {}
                emails = user_info.get("email_addresses") or []
                email = (emails[0].get("email_address") if emails else "") or ""
                row = User(
                    clerk_user_id=clerk_user_id,
                    email=email,
                    first_name=user_info.get("first_name") or "",
                    last_name=user_info.get("last_name") or "",
                )
                _db.session.add(row)
                _db.session.commit()
                LOGGER.info(
                    "auth_session: created local user clerk_user_id=%s",
                    clerk_user_id,
                )
        except Exception:
            LOGGER.exception("auth_session: local user upsert failed (non-fatal)")

        LOGGER.info(
            "auth_session: bridge issued clerk_user_id=%s", clerk_user_id,
        )
        return create_app_session_cookie_response(clerk_user_id, {"ok": True})

    @flask_app_instance.post("/sign-out")
    @flask_app_instance.get("/sign-out")
    def sign_out_clear():
        from flask import redirect
        try:
            session.clear()
        except Exception:
            pass
        resp = make_response(redirect("/", code=303))
        clear_app_session_cookie(resp)
        LOGGER.info("auth_session: signed out (cookie cleared)")
        return resp
