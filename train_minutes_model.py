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
    "MIN_LAST3",
    "MIN_LAST5",
    "MIN_LAST10",
    "MIN_STD5",
    "MIN_TREND",
    "OPP_PTS_ALLOWED",
    "OPP_REB_ALLOWED",
    "OPP_AST_ALLOWED"
]

X = df[feature_cols]
y = df["MIN"]

model = RandomForestRegressor(
    n_estimators=300,
    max_depth=10,
    random_state=42,
    n_jobs=-1
)

model.fit(X, y)
joblib.dump(model, "MIN_model.pkl")

print("Saved MIN_model.pkl")