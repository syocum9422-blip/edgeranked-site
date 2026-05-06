import json
from pathlib import Path
from flask import jsonify

WEATHER_PATH = Path("/home/ubuntu/EdgeRanked/site/mlb/outputs/mlb_weather_today.json")

def load_weather():
    if not WEATHER_PATH.exists():
        return {"status": "unavailable", "games": []}
    with WEATHER_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

def weather_score(game):
    label = str(game.get("label", "Neutral"))
    temp = float(game.get("temperature_f") or 0)
    wind = float(game.get("wind_speed_mph") or 0)
    rain = float(game.get("rain_chance") or 0)

    score = 50
    if "Run" in label:
        score += 20
    if "Power" in label:
        score += 25
    if "Pitcher" in label:
        score -= 15
    score += max(min((temp - 60) * 0.8, 15), -10)
    score += min(wind * 0.7, 12)
    score -= min(rain * 0.25, 12)
    return round(score, 1)

def register_mlb_weather_routes(flask_app, render_layout, render_mlb_nav, render_banner, render_meta_strip, json_ready):
    @flask_app.get("/api/mlb/weather")
    def mlb_weather_api():
        return jsonify(json_ready(load_weather()))

    @flask_app.get("/mlb/weather")
    def mlb_weather_page():
        data = load_weather()
        games = data.get("games", []) or []
        title = "MLB Weather Impact"
        subtitle = "Weather, wind, roof, and run-environment context for today's MLB slate."
        nav = render_mlb_nav("/mlb/weather")

        if not games:
            body = render_banner("") + "<section class='panel'><h2>Weather context unavailable</h2></section>"
            return render_layout(title, subtitle, body, "/mlb/weather", nav)

        def is_delay(g):
            return int(g.get("rain_chance") or 0) >= 25 or "delay" in str(g.get("label", "")).lower()

        run_boost = [g for g in games if "Run" in str(g.get("label", "")) or "Power" in str(g.get("label", ""))]
        pitcher = [g for g in games if "Pitcher" in str(g.get("label", ""))]
        delays = [g for g in games if is_delay(g)]
        neutral = [g for g in games if g not in run_boost and g not in pitcher and g not in delays]

        run_boost = sorted(run_boost, key=weather_score, reverse=True)
        pitcher = sorted(pitcher, key=weather_score)
        delays = sorted(delays, key=lambda g: int(g.get("rain_chance") or 0), reverse=True)
        neutral = sorted(neutral, key=weather_score, reverse=True)

        def card(game, emoji):
            matchup = f"{game.get('away_team', '')} @ {game.get('home_team', '')}"
            venue = game.get("venue", "")
            label = game.get("label", "Neutral")
            temp = game.get("temperature_f", "—")
            wind = game.get("wind_speed_mph", "—")
            wind_dir = game.get("wind_direction", "")
            rain = game.get("rain_chance", "—")
            summary = game.get("summary", "")
            score = weather_score(game)

            return f"""
            <article style="border:1px solid var(--border);border-radius:18px;padding:12px;background:rgba(255,255,255,.035);">
              <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
                <div>
                  <div style="font-size:30px;margin-bottom:6px;">{emoji}</div>
                  <h3 style="margin:0 0 5px 0;">{matchup}</h3>
                  <p style="margin:0;color:var(--muted);font-size:13px;">{venue}</p>
                </div>
                <div style="font-size:24px;font-weight:900;">{score}</div>
              </div>
              <div style="display:flex;flex-wrap:wrap;gap:8px;margin:14px 0;">
                <span style="border:1px solid var(--border);border-radius:999px;padding:6px 10px;">{label}</span>
                <span style="border:1px solid var(--border);border-radius:999px;padding:6px 10px;">{temp}°F</span>
                <span style="border:1px solid var(--border);border-radius:999px;padding:6px 10px;">{wind} mph {wind_dir}</span>
                <span style="border:1px solid var(--border);border-radius:999px;padding:6px 10px;">{rain}% rain</span>
              </div>
              <p style="color:var(--muted);margin-bottom:0;">{summary}</p>
            </article>
            """

        def box(title_text, emoji, items, note):
            if not items:
                return ""
            cards = "".join(card(g, emoji) for g in items)
            return f"""
            <section class="panel">
              <h2>{emoji} {title_text}</h2>
              <p style="color:var(--muted);">{note}</p>
              <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:18px;">
                {cards}
              </div>
            </section>
            """

        def scroll_box(title_text, emoji, items, note):
            if not items:
                return ""
            cards = "".join(f"<div style='min-width:280px;max-width:320px;'>{card(g, emoji)}</div>" for g in items)
            return f"""
            <section class="panel">
              <h2>{emoji} {title_text}</h2>
              <p style="color:var(--muted);">{note}</p>
              <div style="display:grid;grid-template-columns:1fr;gap:16px;margin-top:18px;">
                {cards}
              </div>
            </section>
            """

        body = (
            render_banner("")
            + render_meta_strip(data)
            + box("Run Boost", "🔥", run_boost, "Best run-scoring weather spots on the slate.")
            + box("Pitcher Friendly", "❄️", pitcher, "Cooler or suppressive weather environments.")
            + box("Possible Delays", "⚠️", delays, "Rain or delay-risk games to monitor.")
            + scroll_box("Neutral Weather", "☁️", neutral, "Lower-impact games grouped for quick review.")
        )

        return render_layout(title, subtitle, body, "/mlb/weather", nav)
