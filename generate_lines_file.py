import os

import pandas as pd

# Load projections
BASE_DIR = os.environ.get("EDGERANKED_NBA_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
path = os.path.join(BASE_DIR, "projections.csv")
df = pd.read_csv(path)

# Pick players (you can adjust this)
df = df.sort_values("CONFIDENCE", ascending=False).head(40)

# Create blank lines file
lines_df = pd.DataFrame({
    "player": df["PLAYER_NAME"],
    "stat_type": "PTS",
    "line": ""
})

# Save it
lines_df.to_csv(os.path.join(BASE_DIR, "data", "lines_today.csv"), index=False)

print("✅ Created lines_today.csv with players from your model")
