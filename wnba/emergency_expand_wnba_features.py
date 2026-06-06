import pandas as pd
from pathlib import Path

features_p = Path("data/processed/wnba_today_features.csv")
lines_p = Path("data/raw/wnba_sportsbook_lines_raw.csv")
schedule_p = Path("data/raw/wnba_schedule_today.csv")
audit_p = Path("data/processed/wnba_feature_player_audit.csv")

features = pd.read_csv(features_p)
lines = pd.read_csv(lines_p)
schedule = pd.read_csv(schedule_p)

def key(name):
    return str(name).strip().lower()

# slate teams/opponents
slate_teams = set()
for c in ["home_team", "away_team", "team", "opponent"]:
    if c in schedule.columns:
        slate_teams |= set(schedule[c].dropna().astype(str).str.strip())

# Emergency opening-day slate fallback:
# ESPN schedule is missing one game, so force only tonight's known slate teams.
slate_teams = {"CON", "NYL", "TOR", "WAS", "GSV", "SEA"}
live = lines[lines["team"].isin(slate_teams)].copy()
live_players = live[["player_name", "team"]].drop_duplicates()

existing_keys = set(features["player_name"].map(key))

# numeric baseline from current supportable rows
base = features.median(numeric_only=True).to_dict()
template = features.iloc[0].copy()

rows = []
audit = []

for _, r in live_players.iterrows():
    player = r["player_name"]
    team = r["team"]

    player_lines = live[(live["player_name"] == player) & (live["team"] == team)]
    opponent = ""
    if "opponent" in player_lines.columns:
        vals = player_lines["opponent"].dropna().astype(str)
        if len(vals):
            opponent = vals.iloc[0]

    if not opponent:
        # infer opponent from schedule
        for _, g in schedule.iterrows():
            home = str(g.get("home_team", ""))
            away = str(g.get("away_team", ""))
            if team == home:
                opponent = away
            elif team == away:
                opponent = home

    has_hist = key(player) in existing_keys

    if has_hist:
        audit.append({
            "player_name": player, "team": team, "opponent": opponent,
            "has_live_line": True, "has_player_history": True,
            "kept": True, "reason": "already_in_features"
        })
        continue

    new = template.copy()

    for col, val in base.items():
        if col in new.index:
            new[col] = val

    new["player_name"] = player
    new["player_key"] = key(player)
    new["team"] = team
    new["opponent"] = opponent
    new["game_date"] = str(schedule["game_date"].iloc[0]) if "game_date" in schedule.columns and len(schedule) else str(features["game_date"].iloc[0])
    new["_data_source"] = "baseline_live_line"
    if "confidence" in new.index:
        new["confidence"] = "low"
    if "position" in new.index:
        new["position"] = new.get("position", "UNK") or "UNK"

    rows.append(new)
    audit.append({
        "player_name": player, "team": team, "opponent": opponent,
        "has_live_line": True, "has_player_history": False,
        "kept": True, "reason": "baseline_live_line_no_history"
    })

if rows:
    features = pd.concat([features, pd.DataFrame(rows)], ignore_index=True)

features.to_csv(features_p, index=False)
pd.DataFrame(audit).to_csv(audit_p, index=False)

print("updated features:", features.shape)
print("teams:", sorted(features["team"].dropna().unique()))
print("added baseline rows:", len(rows))
print("audit:", audit_p)
