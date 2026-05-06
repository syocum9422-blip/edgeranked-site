"""
Authentication module using Clerk.
Provides email/password and Google OAuth login.
"""

import logging
import os
from functools import wraps
from urllib.request import urlopen

import jwt
from flask import current_app, jsonify, request, session

LOGGER = logging.getLogger(__name__)

# Clerk configuration from environment
CLERK_PUBLISHABLE_KEY = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
CLERK_SECRET_KEY = os.environ.get("CLERK_SECRET_KEY", "")
CLERK_API_URL = os.environ.get("CLERK_API_URL", "https://api.clerk.dev/v1")
CLERK_JWT_AUDIENCE = os.environ.get("CLERK_JWT_AUDIENCE", "edgeranked")

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


def get_clerk_user_id():
    """
    Extract and verify Clerk user ID from session or Authorization header.
    Returns user_id if valid, None otherwise.
    """
    # Check session first
    if session.get("user_id"):
        return session.get("user_id")

    # Check Authorization header (Bearer token)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            # Decode and verify JWT from Clerk
            payload = jwt.decode(
                token,
                CLERK_SECRET_KEY,
                algorithms=["HS256"],
                audience=CLERK_JWT_AUDIENCE,
            )
            return payload.get("sub")
        except jwt.ExpiredSignatureError:
            LOGGER.warning("Clerk JWT has expired")
        except jwt.InvalidTokenError as e:
            LOGGER.warning(f"Invalid Clerk JWT: {e}")

    return None


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
    email = data.get("email_addresses", [{}])[0].get("email_address", "")
    first_name = data.get("first_name", "")
    last_name = data.get("last_name", "")

    LOGGER.info(f"New user created: {user_id} ({email})")

    # Store user in local database for subscription tracking
    from auth_system.models import db, User
    with flask_app.app_context():
        existing = User.query.filter_by(clerk_user_id=user_id).first()
        if not existing:
            user = User(
                clerk_user_id=user_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
            )
            db.session.add(user)
            db.session.commit()


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
