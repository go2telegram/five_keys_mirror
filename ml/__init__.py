"""Utilities for the lightweight self-training loop."""

from .train_daily import (  # noqa: F401
    MODEL_REGISTRY,
    DataLakeClient,
    TrainResult,
    artifact_to_model,
    evaluate_model,
    load_artifact,
    prepare_training_data,
    train_model,
)
