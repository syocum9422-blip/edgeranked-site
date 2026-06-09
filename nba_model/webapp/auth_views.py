import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
import csv

from flask import redirect, request

# Sourced from environment so the frontend Clerk-js script source, the hosted
# accounts portal redirect target, and the publishable key all point at the
# same Clerk instance as the backend verifier (CLERK_JWT_ISSUER).
CLERK_BASE_URL = os.environ["CLERK_BASE_URL"]
CLERK_FRONTEND_API = os.environ["CLERK_FRONTEND_API"]
CLERK_PUBLISHABLE_KEY = os.environ["CLERK_PUBLISHABLE_KEY"]
# Clerk dev/test instances host the Account Portal at <slug>.accounts.dev
# (no .clerk. subdomain). The frontend API <slug>.clerk.accounts.dev returns
# 404 for /sign-in and /sign-up. Strip the .clerk. segment when present so
# the hosted sign-in/sign-up pages actually resolve. Production custom
# domains (e.g. accounts.example.com) contain no ".clerk.accounts.dev"
# substring and are unaffected.
CLERK_ACCOUNT_PORTAL_URL = CLERK_BASE_URL.replace(
    ".clerk.accounts.dev", ".accounts.dev"
)
SITE_BASE_URL = "https://edgerankedai.com"
X_URL = "https://x.com/EdgerankedAI"

def _safe_next(default="/account"):
    raw = (request.args.get("next") or "").strip()
    if not raw:
        return default
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return default
    if not raw.startswith("/"):
        return default
    if raw.startswith("//"):
        return default
    return raw


def register_auth_routes(flask_app):

    @flask_app.get("/sign-in")
    def sign_in():
        # Always return from Clerk to /account?next=<safe>; the /account page
        # exchanges the Clerk session token for the EdgeRanked bridge cookie
        # and then forwards the browser to <safe> (or /account if missing).
        next_path = _safe_next()
        bridge = f"/account?next={quote(next_path)}"
        return redirect(
            f"{CLERK_ACCOUNT_PORTAL_URL}/sign-in"
            f"?redirect_url={quote(SITE_BASE_URL + bridge)}"
            f"&after_sign_in_url={quote(SITE_BASE_URL + bridge)}"
        )

    @flask_app.get("/sign-up")
    def sign_up():
        next_path = _safe_next()
        bridge = f"/account?next={quote(next_path)}"
        return redirect(
            f"{CLERK_ACCOUNT_PORTAL_URL}/sign-up"
            f"?redirect_url={quote(SITE_BASE_URL + bridge)}"
            f"&after_sign_up_url={quote(SITE_BASE_URL + bridge)}"
        )

    @flask_app.get("/account")
    def account():
        # Sanitize ?next on the server before embedding into JS, so an attacker
        # cannot smuggle an external redirect through the bridge page.
        # json.dumps gives a properly-escaped JS string literal.
        next_path_js = json.dumps(_safe_next(default="/"))
        return f"""
<!doctype html>
<html>
<head>
  <title>EdgeRanked Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <script
    async
    crossorigin="anonymous"
    data-clerk-publishable-key="{CLERK_PUBLISHABLE_KEY}"
    src="{CLERK_FRONTEND_API}/npm/@clerk/clerk-js@latest/dist/clerk.browser.js">
  </script>

  <style>
    body {{
      margin: 0;
      background: #020617;
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif;
    }}

    .wrap {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 50px 20px;
    }}

    .header {{
      margin-bottom: 30px;
    }}

    .title {{
      font-size: 38px;
      font-weight: 700;
    }}

    .subtitle {{
      color: #94a3b8;
      margin-top: 8px;
    }}

    .userbox {{
      margin-top: 18px;
      padding: 14px 18px;
      border-radius: 12px;
      background: rgba(59,130,246,0.1);
      border: 1px solid rgba(59,130,246,0.3);
      font-size: 14px;
    }}

    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 18px;
      margin-top: 40px;
    }}

    .card {{
      padding: 20px;
      border-radius: 16px;
      background: rgba(15,23,42,0.9);
      border: 1px solid rgba(148,163,184,0.2);
      text-decoration: none;
      color: white;
      transition: 0.2s;
    }}

    .card:hover {{
      transform: translateY(-4px);
      border-color: #3b82f6;
    }}

    .card h3 {{
      margin: 0 0 6px;
      font-size: 18px;
    }}

    .card p {{
      margin: 0;
      color: #94a3b8;
      font-size: 14px;
    }}

    .cta {{
      margin-top: 40px;
      padding: 22px;
      border-radius: 18px;
      background: linear-gradient(135deg, #1e3a8a, #0ea5e9);
      text-align: center;
    }}

    .cta a {{
      color: white;
      font-weight: 600;
      text-decoration: none;
    }}
  </style>
</head>

<body>
  <div class="wrap">

    <div class="header">
      <div class="title">Welcome to EdgeRanked</div>
      <div class="subtitle">
        Daily projections, trends, and model-driven insights across sports.
      </div>

      <div class="userbox">
        Logged in as: <span id="user-email">Loading...</span>
      </div>
    </div>

    <div class="grid">
      <a href="/mlb" class="card">
        <h3>MLB Projection Center</h3>
        <p>Hitter and pitcher projections updated daily.</p>
      </a>

      <a href="/mlb?view=top_plays" class="card">
        <h3>Top MLB Plays</h3>
        <p>Highest edge opportunities from the model.</p>
      </a>

      <a href="/mlb/pitcher-strikeouts" class="card">
        <h3>Pitcher Projections</h3>
        <p>Pitcher board with strikeout and workload context.</p>
      </a>

      <a href="/mlb/weather" class="card">
        <h3>Weather Impact</h3>
        <p>Ballpark and weather influence on performance.</p>
      </a>

      <a href="/nba" class="card">
        <h3>NBA Projections</h3>
        <p>Player projections and playoff modeling.</p>
      </a>

      <a href="{X_URL}" class="card" target="_blank">
        <h3>Follow Updates on X</h3>
        <p>@EdgerankedAI daily trends and model insights.</p>
      </a>
    </div>

    <div class="cta">
      <div style="margin-bottom:14px;">Premium membership unlocks advanced player tracking and deeper projections.</div>
      <button id="subscribe-btn" type="button" style="background:white;color:#0ea5e9;border:none;padding:12px 28px;border-radius:999px;font-weight:700;cursor:pointer;font-size:15px;">Start membership</button>
      <div id="subscribe-msg" style="margin-top:10px;font-size:13px;color:rgba(255,255,255,0.85);"></div>
    </div>

  </div>

  <script>
    // Server-sanitized next path embedded by Flask. Falls back to "/" when
    // none was provided. Never trust window.location.search here — the server
    // already validated this value against external redirect attempts.
    const ER_NEXT_PATH = {next_path_js};

    async function erBridgeSession() {{
      // Call /api/auth/session with a Clerk Bearer token to install the
      // edgeranked_session cookie. Returns true on success.
      try {{
        if (!window.Clerk || !window.Clerk.session) return false;
        const token = await window.Clerk.session.getToken();
        if (!token) return false;
        const r = await fetch("/api/auth/session", {{
          method: "POST",
          credentials: "same-origin",
          headers: {{
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
          }},
          body: "{{}}",
        }});
        return r.ok;
      }} catch (err) {{
        console.error("[bridge] error", err);
        return false;
      }}
    }}

    window.addEventListener("load", async function () {{
      try {{
        await window.Clerk.load();
      }} catch {{
        document.getElementById("user-email").textContent = "Unable to load";
        return;
      }}

      if (!window.Clerk.user) {{
        // No active Clerk session — user landed on /account directly. Send
        // them to /sign-in preserving the intended destination so they end
        // up back here after authenticating.
        const target = "/sign-in?next=" + encodeURIComponent(ER_NEXT_PATH || "/account");
        window.location.replace(target);
        return;
      }}

      const bridged = await erBridgeSession();
      if (!bridged) {{
        const errBox = document.getElementById("user-email");
        if (errBox) errBox.textContent = "Could not establish session. Please sign in again.";
        console.error("[bridge] /api/auth/session failed");
        return;
      }}

      // If /sign-in routed us here with a real destination, forward there.
      // Treat /account, empty, or "/" as "stay on dashboard".
      if (ER_NEXT_PATH && ER_NEXT_PATH !== "/account" && ER_NEXT_PATH !== "/") {{
        window.location.replace(ER_NEXT_PATH);
        return;
      }}

      try {{
        const email = window.Clerk.user.primaryEmailAddress?.emailAddress || "Account verified";
        document.getElementById("user-email").textContent = email;
      }} catch {{
        document.getElementById("user-email").textContent = "Account verified";
      }}

      const btn = document.getElementById("subscribe-btn");
      const msg = document.getElementById("subscribe-msg");
      if (btn) {{
        btn.addEventListener("click", async function (e) {{
          if (e && typeof e.preventDefault === "function") e.preventDefault();
          if (e && typeof e.stopPropagation === "function") e.stopPropagation();
          try {{
            if (!window.Clerk) {{
              msg.textContent = "Clerk not loaded. Refresh the page and try again.";
              console.error("[subscribe] window.Clerk is undefined");
              return;
            }}
            await window.Clerk.load();
            if (!window.Clerk.user) {{
              console.warn("[subscribe] no Clerk user; redirecting to /sign-in");
              window.location = "/sign-in";
              return;
            }}
            if (!window.Clerk.session) {{
              msg.textContent = "Session not ready. Please sign in again.";
              console.error("[subscribe] window.Clerk.session is null after load");
              return;
            }}
            btn.disabled = true; msg.textContent = "Opening secure checkout...";
            const token = await window.Clerk.session.getToken();
            if (!token) {{
              msg.textContent = "Could not obtain session token. Please sign in again.";
              console.error("[subscribe] getToken() returned empty");
              btn.disabled = false;
              return;
            }}
            console.log("[subscribe] POST /api/stripe/create-checkout");
            const r = await fetch("/api/stripe/create-checkout", {{
              method: "POST",
              headers: {{ "Authorization": "Bearer " + token, "Content-Type": "application/json" }},
              body: "{{}}",
            }});
            console.log("[subscribe] response status", r.status);
            if (!r.ok) {{
              let detail = "";
              try {{ detail = (await r.json()).error || ""; }} catch {{ detail = await r.text().catch(() => ""); }}
              msg.textContent = "Checkout unavailable (HTTP " + r.status + "). " + (detail || "Please try again.");
              console.error("[subscribe] non-OK response", r.status, detail);
              btn.disabled = false;
              return;
            }}
            const data = await r.json();
            console.log("[subscribe] got session", data && data.session_id);
            if (data && data.url) {{
              window.location.assign(data.url);
            }} else {{
              msg.textContent = "No checkout URL returned.";
              console.error("[subscribe] response missing url", data);
              btn.disabled = false;
            }}
          }} catch (err) {{
            msg.textContent = "Checkout error: " + (err && err.message ? err.message : "unknown");
            console.error("[subscribe] exception", err);
            btn.disabled = false;
          }}
        }});
      }}
    }});
  </script>

</body>
</html>
"""

    @flask_app.get("/start-checkout")
    def start_checkout():
        # Minimal launcher used by the premium soft gate for logged-in,
        # unsubscribed users. Loads Clerk, POSTs to /api/stripe/create-checkout
        # carrying `next` so the post-payment success_url returns the user to
        # the original premium destination instead of the generic dashboard.
        next_path = _safe_next(default="/")
        next_path_js = json.dumps(next_path)
        return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>Opening secure checkout · EdgeRankedSportsAI</title>
  <script
    async
    crossorigin="anonymous"
    data-clerk-publishable-key="{CLERK_PUBLISHABLE_KEY}"
    src="{CLERK_FRONTEND_API}/npm/@clerk/clerk-js@latest/dist/clerk.browser.js">
  </script>
  <style>
    html,body{{margin:0;background:#0a0f1c;color:#e5edf7;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}}
    .wrap{{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;}}
    .card{{width:min(440px,100%);background:#121929;border:1px solid #1e293b;border-radius:18px;padding:32px;text-align:center;box-shadow:0 24px 60px rgba(0,0,0,.45);}}
    h1{{margin:0 0 10px;font-size:22px;color:#fff;letter-spacing:-.01em;}}
    p{{margin:0 0 18px;color:#94a3b8;font-size:14px;line-height:1.5;}}
    .spinner{{width:32px;height:32px;border-radius:50%;border:3px solid rgba(255,255,255,.12);border-top-color:#3b82f6;margin:8px auto 18px;animation:spin 1s linear infinite;}}
    @keyframes spin{{to{{transform:rotate(360deg);}}}}
    .err{{margin-top:12px;color:#fda4af;font-size:13px;}}
    a{{color:#60a5fa;}}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div class="spinner" aria-hidden="true"></div>
      <h1>Opening secure checkout…</h1>
      <p id="status">Connecting to Stripe. Don’t close this tab.</p>
      <div class="err" id="err" hidden></div>
    </div>
  </div>
  <script>
    const ER_NEXT_PATH = {next_path_js};
    function showError(msg) {{
      const e = document.getElementById("err");
      const s = document.getElementById("status");
      if (s) s.textContent = "We couldn’t open checkout automatically.";
      if (e) {{ e.hidden = false; e.textContent = msg; }}
    }}
    async function bridgeSession() {{
      try {{
        if (!window.Clerk || !window.Clerk.session) return false;
        const token = await window.Clerk.session.getToken();
        if (!token) return false;
        const r = await fetch("/api/auth/session", {{
          method: "POST",
          credentials: "same-origin",
          headers: {{ "Authorization": "Bearer " + token, "Content-Type": "application/json" }},
          body: "{{}}",
        }});
        return r.ok;
      }} catch (err) {{
        console.error("[start-checkout] bridge error", err);
        return false;
      }}
    }}
    window.addEventListener("load", async function () {{
      try {{ await window.Clerk.load(); }}
      catch (err) {{ showError("Could not load auth. Refresh and try again."); return; }}

      if (!window.Clerk.user) {{
        // Not signed in. Send through sign-in, then return here with the
        // same next path so the launcher fires after authentication.
        const back = "/start-checkout?next=" + encodeURIComponent(ER_NEXT_PATH || "/");
        window.location.replace("/sign-in?next=" + encodeURIComponent(back));
        return;
      }}

      // Ensure the edgeranked_session bridge cookie is fresh; harmless if
      // it's already valid. Subsequent API calls then succeed on first try.
      await bridgeSession();

      try {{
        const token = await window.Clerk.session.getToken();
        if (!token) {{ showError("Could not obtain a session token."); return; }}
        const r = await fetch("/api/stripe/create-checkout", {{
          method: "POST",
          credentials: "same-origin",
          headers: {{ "Authorization": "Bearer " + token, "Content-Type": "application/json" }},
          body: JSON.stringify({{ next: ER_NEXT_PATH }}),
        }});
        if (!r.ok) {{
          let detail = "";
          try {{ detail = (await r.json()).error || ""; }} catch {{ detail = ""; }}
          showError("Checkout unavailable (HTTP " + r.status + ")." + (detail ? " " + detail : ""));
          return;
        }}
        const data = await r.json();
        if (data && data.url) {{
          window.location.assign(data.url);
        }} else {{
          showError("No checkout URL returned.");
        }}
      }} catch (err) {{
        showError(err && err.message ? err.message : "Unknown error.");
      }}
    }});
  </script>
</body>
</html>
"""
