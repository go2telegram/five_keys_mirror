import asyncio
import logging
from typing import Any, Dict, List

import pytest
from aiogram.types import TelegramObject

from app.telemetry import TelemetryMiddleware


class ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - simple storage
        self.records.append(record)


@pytest.fixture()
def telemetry_logger() -> logging.Logger:
    logger = logging.getLogger(f"test.telemetry.{id(object())}")
    logger.handlers = []
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def test_fast_update_logs_compact_entry(telemetry_logger: logging.Logger) -> None:
    handler = ListHandler()
    telemetry_logger.addHandler(handler)

    middleware = TelemetryMiddleware(logger=telemetry_logger, debug=False, slow_ms=10_000)

    async def runner() -> None:
        async def dummy_handler(event: TelegramObject, data: Dict[str, Any]) -> str:
            return "ok"

        await middleware(dummy_handler, TelegramObject(), {})

    asyncio.run(runner())

    assert len(handler.records) == 1
    record = handler.records[0]
    assert isinstance(record.msg, dict)
    assert record.msg["kind"] == "u"
    assert "t" in record.msg
    assert "ms" in record.msg


def test_debug_logs_include_audit_entry(telemetry_logger: logging.Logger) -> None:
    handler = ListHandler()
    telemetry_logger.addHandler(handler)

    middleware = TelemetryMiddleware(logger=telemetry_logger, debug=True, slow_ms=10_000)

    async def runner() -> None:
        async def dummy_handler(event: TelegramObject, data: Dict[str, Any]) -> str:
            return "ok"

        await middleware(dummy_handler, TelegramObject(), {})

    asyncio.run(runner())

    kinds = [record.msg.get("kind") for record in handler.records if isinstance(record.msg, dict)]
    assert "u" in kinds
    assert "update_audit" in kinds
