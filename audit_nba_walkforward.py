import json
from datetime import datetime

import json
from datetime import datetime

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score

df = pd.read_csv("model_dataset.csv")
df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], errors="coerce")
df = df.dropna(subset=["GAME_DATE"]).sort_values("GAME_DATE").copy()

feature_cols = [
    "HOME", "REST_DAYS", "B2B", "LOW_MIN_ROLE", "VOLATILE_MINUTES",
    "PTS_LAST3", "PTS_LAST5", "PTS_LAST10",
    "REB_LAST3", "REB_LAST5", "REB_LAST10",
    "AST_LAST3", "AST_LAST5", "AST_LAST10",
    "STL_LAST3", "STL_LAST5", "STL_LAST10",
    "BLK_LAST3", "BLK_LAST5", "BLK_LAST10",
    "FG3M_LAST3", "FG3M_LAST5", "FG3M_LAST10",
    "MIN_LAST3", "MIN_LAST5", "MIN_LAST10",
    "MIN_STD5", "PTS_STD5", "REB_STD5", "AST_STD5",
    "PTS_TREND", "MIN_TREND",
    "OPP_PTS_ALLOWED", "OPP_REB_ALLOWED", "OPP_AST_ALLOWED"
]

targets = ["PTS", "REB", "AST", "STL", "BLK", "FG3M", "MIN"]

cutoffs = [
    "2026-03-01",
    "2026-04-01",
    "2026-05-01",
]

rows = []

for target in targets:
    use_cols = feature_cols + [target, "GAME_DATE"]
    target_df = df[use_cols].dropna().copy()

    for cutoff in cutoffs:
        cutoff_ts = pd.Timestamp(cutoff)
        train = target_df[target_df["GAME_DATE"] < cutoff_ts].copy()
        test = target_df[
            (target_df["GAME_DATE"] >= cutoff_ts)
            & (target_df["GAME_DATE"] < cutoff_ts + pd.DateOffset(months=1))
        ].copy()

        if len(train) < 1000 or len(test) < 100:
            continue

        model = RandomForestRegressor(
            n_estimators=50,
            max_depth=12 if target != "MIN" else 10,
            min_samples_leaf=3,
            random_state=42,
            n_jobs=-1,
        )

        model.fit(train[feature_cols], train[target])
        pred = model.predict(test[feature_cols])

        rows.append({
            "target": target,
            "cutoff": cutoff,
            "train_rows": len(train),
            "test_rows": len(test),
            "mae": round(mean_absolute_error(test[target], pred), 4),
            "r2": round(r2_score(test[target], pred), 4),
            "actual_mean": round(float(test[target].mean()), 4),
            "pred_mean": round(float(pd.Series(pred).mean()), 4),
        })

out = pd.DataFrame(rows)
out.to_csv("nba_walkforward_audit.csv", index=False)

summary = {
    "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    "dataset_rows": int(len(df)),
    "dataset_start": str(df["GAME_DATE"].min().date()) if not df.empty else None,
    "dataset_end": str(df["GAME_DATE"].max().date()) if not df.empty else None,
    "windows_evaluated": int(len(out)),
    "targets": sorted(out["target"].unique().tolist()) if not out.empty else [],
    "status": "PASS",
    "warnings": [],
    "by_target": {},
}

# Practical first-pass gates. These are not product promises; they are regression
# tripwires so a future retrain cannot silently collapse.
min_r2 = {
    "PTS": 0.20,
    "REB": 0.20,
    "AST": 0.20,
    "STL": -0.05,
    "BLK": -0.05,
    "FG3M": 0.05,
    "MIN": 0.30,
}

if out.empty:
    summary["status"] = "FAIL"
    summary["warnings"].append("No walk-forward windows evaluated.")
else:
    grouped = out.groupby("target")
    for target, g in grouped:
        avg_mae = float(g["mae"].mean())
        avg_r2 = float(g["r2"].mean())
        summary["by_target"][target] = {
            "windows": int(len(g)),
            "avg_mae": round(avg_mae, 4),
            "avg_r2": round(avg_r2, 4),
            "latest_mae": round(float(g.sort_values("cutoff").iloc[-1]["mae"]), 4),
            "latest_r2": round(float(g.sort_values("cutoff").iloc[-1]["r2"]), 4),
        }
        floor = min_r2.get(target)
        if floor is not None and avg_r2 < floor:
            summary["status"] = "WARN"
            summary["warnings"].append(
                f"{target} avg_r2 {avg_r2:.4f} below regression floor {floor:.4f}"
            )

with open("nba_walkforward_audit_summary.json", "w", encoding="utf-8") as fh:
    json.dump(summary, fh, indent=2)

print(out.to_string(index=False))
print("\nSaved nba_walkforward_audit.csv")
print("Saved nba_walkforward_audit_summary.json")
print("status:", summary["status"])
for warning in summary["warnings"]:
    print("WARNING:", warning)
