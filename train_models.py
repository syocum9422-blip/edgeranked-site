import joblib
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

df = pd.read_csv("model_dataset.csv")

feature_cols = [
    "HOME",
    "REST_DAYS",
    "B2B",
    "LOW_MIN_ROLE",
    "VOLATILE_MINUTES",
    "PTS_LAST3",
    "PTS_LAST5",
    "PTS_LAST10",
    "REB_LAST3",
    "REB_LAST5",
    "REB_LAST10",
    "AST_LAST3",
    "AST_LAST5",
    "AST_LAST10",
    "STL_LAST3",
    "STL_LAST5",
    "STL_LAST10",
    "BLK_LAST3",
    "BLK_LAST5",
    "BLK_LAST10",
    "FG3M_LAST3",
    "FG3M_LAST5",
    "FG3M_LAST10",
    "MIN_LAST3",
    "MIN_LAST5",
    "MIN_LAST10",
    "MIN_STD5",
    "PTS_STD5",
    "REB_STD5",
    "AST_STD5",
    "PTS_TREND",
    "MIN_TREND",
    "OPP_PTS_ALLOWED",
    "OPP_REB_ALLOWED",
    "OPP_AST_ALLOWED"
]

targets = ["PTS", "REB", "AST", "STL", "BLK", "FG3M"]

for target in targets:
    train_df = df[feature_cols + [target]].dropna().copy()

    X = train_df[feature_cols]
    y = train_df[target]

    model = RandomForestRegressor(
        n_estimators=300,
        max_depth=12,
        min_samples_leaf=3,
        random_state=42,
        n_jobs=-1
    )

    model.fit(X, y)
    joblib.dump(model, f"{target}_model.pkl")
    print(f"Saved {target}_model.pkl")

print("All stat models trained.")