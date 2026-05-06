from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import csv

from flask import redirect, request

CLERK_BASE_URL = "https://accounts.edgerankedai.com"
CLERK_FRONTEND_API = "https://clerk.edgerankedai.com"
CLERK_PUBLISHABLE_KEY = "pk_live_Y2xlcmsuZWRnZXJhbmtlZGFpLmNvbSQ"
SITE_BASE_URL = "https://edgerankedai.com"
X_URL = "https://x.com/EdgerankedAI"

def register_auth_routes(flask_app):

    @flask_app.get("/sign-in")
    def sign_in():
        return redirect(
            f"{CLERK_BASE_URL}/sign-in"
            f"?redirect_url={quote(SITE_BASE_URL + '/account')}"
            f"&after_sign_in_url={quote(SITE_BASE_URL + '/account')}"
        )

    @flask_app.get("/sign-up")
    def sign_up():
        return redirect(
            f"{CLERK_BASE_URL}/sign-up"
            f"?redirect_url={quote(SITE_BASE_URL + '/account')}"
            f"&after_sign_up_url={quote(SITE_BASE_URL + '/account')}"
        )

    @flask_app.get("/account")
    def account():
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
      Premium features are coming soon — including advanced player tracking and deeper projections.
    </div>

  </div>

  <script>
    window.addEventListener("load", async function () {{
      try {{
        await window.Clerk.load();
        const email = window.Clerk.user?.primaryEmailAddress?.emailAddress || "Account verified";
        document.getElementById("user-email").textContent = email;
      }} catch {{
        document.getElementById("user-email").textContent = "Unable to load";
      }}
    }});
  </script>

</body>
</html>
"""
