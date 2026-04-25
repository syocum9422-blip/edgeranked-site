import os
import pandas as pd
from datetime import datetime

BASE_DIR = os.environ.get("EDGERANKED_NBA_BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

os.makedirs(OUTPUT_DIR, exist_ok=True)

BEST_BETS_PATH = os.path.join(OUTPUT_DIR, "best_bets.csv")
GRADED_OUTPUT_PATH = os.path.join(OUTPUT_DIR, "graded_results.csv")
LOG_PATH = os.path.join(OUTPUT_DIR, "grade_log.txt")

def log(msg):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")

log("Grade script started")

if not os.path.exists(BEST_BETS_PATH):
    log(f"Missing file: {BEST_BETS_PATH}")
    raise FileNotFoundError(BEST_BETS_PATH)

df = pd.read_csv(BEST_BETS_PATH)

# Placeholder grading logic
# Replace RESULT with your real grading rules once the source stats file is connected
if "RESULT" not in df.columns:
    df["RESULT"] = "UNGRADED"

df["GRADED_AT"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

df.to_csv(GRADED_OUTPUT_PATH, index=False)
os.utime(GRADED_OUTPUT_PATH, None)

log(f"Saved graded results to {GRADED_OUTPUT_PATH}")
log("Grade script finished")
