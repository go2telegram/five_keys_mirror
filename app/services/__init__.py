"""Service layer helpers with lazy imports to avoid heavy modules at import time."""

from importlib import import_module
from typing import Any

__all__ = ["catalog_search", "product_get", "get_reco", "premium_metrics"]


def __getattr__(name: str) -> Any:  # pragma: no cover - thin delegation
    if name in {"catalog_search", "product_get", "get_reco"}:
        module = import_module("app.services.catalog_service")
        return getattr(module, name)
    if name == "premium_metrics":
        return import_module("app.services.premium_metrics")
    raise AttributeError(name)
