import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
import joblib

df = pd.read_csv("model_dataset.csv")

features = [
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

target = "PTS"

X = df[features].copy()
y = df[target].copy()

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

model = RandomForestRegressor(
    n_estimators=200,
    max_depth=10,
    random_state=42,
    n_jobs=-1
)

model.fit(X_train, y_train)

score = model.score(X_test, y_test)

joblib.dump(model, "pts_model.pkl")

print("Model trained successfully")
print("R^2 score:", round(score, 4))
print("Saved as pts_model.pkl")
