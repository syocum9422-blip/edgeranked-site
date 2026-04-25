import json
import os
from datetime import date
from urllib.request import Request, urlopen

API_KEY = os.getenv("5f4e5a46-0c06-4ff5-82f2-f9a1461a32f7")
if not API_KEY:
    raise ValueError("Missing BALLDONTLIE_API_KEY environment variable")

today = date.today().isoformat()
url = f"https://api.balldontlie.io/v1/games?dates[]={today}&per_page=100"

req = Request(url, headers={"Authorization": API_KEY})

with urlopen(req, timeout=30) as resp:
    data = json.loads(resp.read().decode("utf-8"))

games = data.get("data", [])

teams = set()
for g in games:
    home = g.get("home_team", {})
    visitor = g.get("visitor_team", {})

    if home.get("abbreviation"):
        teams.add(home["abbreviation"].upper())
    if visitor.get("abbreviation"):
        teams.add(visitor["abbreviation"].upper())

with open("teams_today.csv", "w") as f:
    f.write("TEAM_ABBREVIATION\n")
    for team in sorted(teams):
        f.write(f"{team}\n")

print(f"Today: {today}")
print(f"Saved teams_today.csv with {len(teams)} teams")
print(sorted(teams))