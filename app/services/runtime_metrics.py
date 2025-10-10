"""Runtime metrics for Prometheus scraping."""

from __future__ import annotations

import time
from dataclasses import dataclass

__all__ = ["RuntimeMetrics", "runtime_metrics"]


@dataclass
class _DurationStats:
    """Track aggregated statistics for handler durations."""

    count: int = 0
    total: float = 0.0
    maximum: float = 0.0

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        if value > self.maximum:
            self.maximum = value


class RuntimeMetrics:
    """In-memory container for runtime counters exported over `/metrics`."""

    def __init__(self) -> None:
        self._updates_total = 0
        self._messages_total = 0
        self._callbacks_total = 0
        self._errors_total = 0
        self._last_update_ts = 0.0
        self._update_duration = _DurationStats()
        self._message_duration = _DurationStats()
        self._callback_duration = _DurationStats()

    @staticmethod
    def _format_float(value: float) -> str:
        return f"{value:.6f}"

    def record_update(self) -> None:
        self._updates_total += 1
        self._last_update_ts = time.time()

    def observe_update_duration(self, seconds: float) -> None:
        self._update_duration.observe(max(0.0, seconds))

    def record_message(self) -> None:
        self._messages_total += 1

    def observe_message_duration(self, seconds: float) -> None:
        self._message_duration.observe(max(0.0, seconds))

    def record_callback(self) -> None:
        self._callbacks_total += 1

    def observe_callback_duration(self, seconds: float) -> None:
        self._callback_duration.observe(max(0.0, seconds))

    def record_error(self) -> None:
        self._errors_total += 1

    def snapshot(self) -> dict[str, float | int]:
        """Return a point-in-time snapshot of all counters."""

        now = time.time()
        last_update_ts = self._last_update_ts
        seconds_since_last = max(0.0, now - last_update_ts) if last_update_ts else float("nan")
        return {
            "updates_total": self._updates_total,
            "messages_total": self._messages_total,
            "callbacks_total": self._callbacks_total,
            "errors_total": self._errors_total,
            "last_update_ts": last_update_ts,
            "seconds_since_last_update": seconds_since_last,
            "update_duration_total": self._update_duration.total,
            "update_duration_count": self._update_duration.count,
            "update_duration_max": self._update_duration.maximum,
            "message_duration_total": self._message_duration.total,
            "message_duration_count": self._message_duration.count,
            "message_duration_max": self._message_duration.maximum,
            "callback_duration_total": self._callback_duration.total,
            "callback_duration_count": self._callback_duration.count,
            "callback_duration_max": self._callback_duration.maximum,
        }

    def render_prometheus(self) -> list[str]:
        """Render the metrics snapshot in Prometheus exposition format."""

        data = self.snapshot()
        lines = [
            "# HELP five_keys_bot_updates_total Total Telegram updates processed",
            "# TYPE five_keys_bot_updates_total counter",
            f"five_keys_bot_updates_total {data['updates_total']}",
            "# HELP five_keys_bot_messages_total Total Telegram messages processed",
            "# TYPE five_keys_bot_messages_total counter",
            f"five_keys_bot_messages_total {data['messages_total']}",
            "# HELP five_keys_bot_callbacks_total Total Telegram callback queries processed",
            "# TYPE five_keys_bot_callbacks_total counter",
            f"five_keys_bot_callbacks_total {data['callbacks_total']}",
            "# HELP five_keys_bot_handler_errors_total Total handler errors raised",
            "# TYPE five_keys_bot_handler_errors_total counter",
            f"five_keys_bot_handler_errors_total {data['errors_total']}",
            "# HELP five_keys_bot_last_update_timestamp_seconds Unix timestamp of the last processed update",
            "# TYPE five_keys_bot_last_update_timestamp_seconds gauge",
            f"five_keys_bot_last_update_timestamp_seconds {self._format_float(data['last_update_ts'])}",
            "# HELP five_keys_bot_seconds_since_last_update Seconds elapsed since the last processed update",
            "# TYPE five_keys_bot_seconds_since_last_update gauge",
            f"five_keys_bot_seconds_since_last_update {self._format_float(data['seconds_since_last_update'])}",
            "# HELP five_keys_bot_update_duration_seconds_sum Total seconds spent processing updates",
            "# TYPE five_keys_bot_update_duration_seconds_sum counter",
            f"five_keys_bot_update_duration_seconds_sum {self._format_float(data['update_duration_total'])}",
            "# HELP five_keys_bot_update_duration_seconds_count Total updates measured for duration",
            "# TYPE five_keys_bot_update_duration_seconds_count counter",
            f"five_keys_bot_update_duration_seconds_count {data['update_duration_count']}",
            "# HELP five_keys_bot_update_duration_seconds_max Maximum single update processing time in seconds",
            "# TYPE five_keys_bot_update_duration_seconds_max gauge",
            f"five_keys_bot_update_duration_seconds_max {self._format_float(data['update_duration_max'])}",
            "# HELP five_keys_bot_message_duration_seconds_sum Total seconds spent processing messages",
            "# TYPE five_keys_bot_message_duration_seconds_sum counter",
            f"five_keys_bot_message_duration_seconds_sum {self._format_float(data['message_duration_total'])}",
            "# HELP five_keys_bot_message_duration_seconds_count Total messages measured for duration",
            "# TYPE five_keys_bot_message_duration_seconds_count counter",
            f"five_keys_bot_message_duration_seconds_count {data['message_duration_count']}",
            "# HELP five_keys_bot_message_duration_seconds_max Maximum single message processing time in seconds",
            "# TYPE five_keys_bot_message_duration_seconds_max gauge",
            f"five_keys_bot_message_duration_seconds_max {self._format_float(data['message_duration_max'])}",
            "# HELP five_keys_bot_callback_duration_seconds_sum Total seconds spent processing callback queries",
            "# TYPE five_keys_bot_callback_duration_seconds_sum counter",
            f"five_keys_bot_callback_duration_seconds_sum {self._format_float(data['callback_duration_total'])}",
            "# HELP five_keys_bot_callback_duration_seconds_count Total callback queries measured for duration",
            "# TYPE five_keys_bot_callback_duration_seconds_count counter",
            f"five_keys_bot_callback_duration_seconds_count {data['callback_duration_count']}",
            "# HELP five_keys_bot_callback_duration_seconds_max Maximum single callback processing time in seconds",
            "# TYPE five_keys_bot_callback_duration_seconds_max gauge",
            f"five_keys_bot_callback_duration_seconds_max {self._format_float(data['callback_duration_max'])}",
        ]
        return lines


runtime_metrics = RuntimeMetrics()
