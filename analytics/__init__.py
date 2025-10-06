"""Analytics utilities for predictive planning."""

from .forecast import (
    ForecastResult,
    SUPPORTED_METRICS,
    build_forecast,
    format_metric_name,
)

__all__ = [
    "ForecastResult",
    "SUPPORTED_METRICS",
    "build_forecast",
    "format_metric_name",
]
