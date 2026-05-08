from __future__ import annotations

import pandas as pd

from wnba_model_config import DATASET_PATH, MINUTES_MODEL_PATH
from wnba_model_utils import feature_columns, save_model_bundle, setup_logging, train_ensemble_models


def main() -> None:
    logger = setup_logging("train_wnba_minutes_model")
    dataset = pd.read_csv(DATASET_PATH, parse_dates=["game_date"])
    features = [column for column in feature_columns() if column != "minutes"]
    missing_features = [column for column in features if column not in dataset.columns]
    if missing_features:
        raise ValueError(f"Training dataset is missing required minutes features: {missing_features}")

    bundle = train_ensemble_models(dataset, "minutes", features, logger)
    save_model_bundle(bundle, MINUTES_MODEL_PATH)
    logger.info("Saved minutes model to %s", MINUTES_MODEL_PATH)


if __name__ == "__main__":
    main()
