from __future__ import annotations

import pandas as pd

from wnba_model_config import DATASET_PATH, MODEL_REPORT_PATH, STAT_TARGETS
from wnba_model_utils import feature_columns, save_model_bundle, setup_logging, train_ensemble_models


STAT_MODEL_OUTPUTS = {
    "points": "wnba_points_model.joblib",
    "rebounds": "wnba_rebounds_model.joblib",
    "assists": "wnba_assists_model.joblib",
    "threes_made": "wnba_threes_made_model.joblib",
    "steals": "wnba_steals_model.joblib",
    "blocks": "wnba_blocks_model.joblib",
}


def main() -> None:
    logger = setup_logging("train_wnba_models")
    dataset = pd.read_csv(DATASET_PATH, parse_dates=["game_date"])
    features = feature_columns()
    missing_features = [column for column in features if column not in dataset.columns]
    if missing_features:
        raise ValueError(f"Training dataset is missing required features: {missing_features}")

    report_rows = []
    for target in STAT_TARGETS:
        bundle = train_ensemble_models(dataset, target, features, logger)
        output_path = DATASET_PATH.parent.parent / "models" / STAT_MODEL_OUTPUTS[target]
        save_model_bundle(bundle, output_path)
        report_rows.append(bundle["metrics"])

    report = pd.DataFrame(report_rows).sort_values("mae")
    report.to_csv(MODEL_REPORT_PATH, index=False)
    logger.info("Saved model report to %s", MODEL_REPORT_PATH)


if __name__ == "__main__":
    main()
