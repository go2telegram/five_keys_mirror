"""Smoke tests for logging configuration."""

from __future__ import annotations

import logging
from pathlib import Path

from app.logging_config import setup_logging


def test_setup_logging_creates_files(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=str(log_dir), level=logging.DEBUG)

    logging.getLogger("testcase").info("hello from test")
    logging.getLogger("testcase").warning("warn message")

    for handler in logging.getLogger().handlers:
        if hasattr(handler, "flush"):
            handler.flush()

    bot_log = Path(log_dir) / "bot.log"
    errors_log = Path(log_dir) / "errors.log"

    assert bot_log.exists(), "bot log file must be created"
    assert errors_log.exists(), "errors log file must be created"

    bot_text = bot_log.read_text(encoding="utf-8")
    errors_text = errors_log.read_text(encoding="utf-8")

    assert "hello from test" in bot_text
    assert "warn message" in errors_text
