"""Application middleware registry."""
from aiogram import Dispatcher

from app.monitoring.metrics import register_metrics

__all__ = ["register_middlewares"]


def register_middlewares(dp: Dispatcher) -> None:
    """Hook shared middlewares into the dispatcher."""
    register_metrics(dp)
