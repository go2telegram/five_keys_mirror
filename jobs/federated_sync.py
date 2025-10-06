"""Daily federated learning synchronisation job."""
from __future__ import annotations

import logging
import socket
from pathlib import Path

from app.config import settings
from ml import FederatedLearningClient

logger = logging.getLogger(__name__)


def _default_client_id() -> str:
    try:
        host = socket.gethostname()
    except Exception:  # pragma: no cover
        host = "unknown"
    return f"bot-{host}"


def _resolve_path(setting_name: str, fallback: str) -> Path:
    value = getattr(settings, setting_name, None)
    if value:
        return Path(value)
    return Path(fallback)


async def sync_federated_model() -> None:
    """Push local weights to the federated server and fetch the aggregated model."""
    if not getattr(settings, "ENABLE_FED_LEARNING", False):
        logger.debug("Federated learning disabled; skipping sync job")
        return

    server_url = getattr(settings, "FED_SERVER_URL", "")
    if not server_url:
        logger.warning("FED_SERVER_URL is not configured; unable to run federated sync")
        return

    local_path = _resolve_path("FED_LOCAL_MODEL_PATH", "models/local.pkl")
    merged_path = _resolve_path("FED_MERGED_MODEL_PATH", "models/_merged.pkl")

    client_id = getattr(settings, "FED_CLIENT_ID", None) or _default_client_id()

    client = FederatedLearningClient(
        server_url=server_url,
        client_id=client_id,
        local_model_path=local_path,
        merged_model_path=merged_path,
    )

    try:
        result = await client.sync()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Federated sync failed: %s", exc)
        return

    aggregated_accuracy = result.get("aggregated_accuracy")
    local_accuracy = result.get("local_accuracy")
    if aggregated_accuracy is not None and local_accuracy is not None:
        if aggregated_accuracy >= local_accuracy:
            logger.info(
                "Global model accuracy improved from %.4f to %.4f",
                local_accuracy,
                aggregated_accuracy,
            )
        else:
            logger.warning(
                "Aggregated accuracy %.4f is below local accuracy %.4f",
                aggregated_accuracy,
                local_accuracy,
            )
    elif aggregated_accuracy is not None:
        logger.info("Aggregated model accuracy: %.4f", aggregated_accuracy)

    logger.info("Aggregated model saved to %s", result.get("saved_path"))
