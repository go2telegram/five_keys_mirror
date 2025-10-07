"""Logging configuration helpers."""

from __future__ import annotations

import logging
from contextlib import suppress
from logging import Handler
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable


def _close_handlers(handlers: Iterable[Handler]) -> None:
    for handler in handlers:
        logging.getLogger().removeHandler(handler)
        with suppress(Exception):  # pragma: no cover - best effort cleanup
            handler.close()


def setup_logging(log_dir: str = "logs", level: int = logging.INFO) -> None:
    """Configure console and rotating file handlers for the application."""

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    if root.handlers:
        _close_handlers(list(root.handlers))

    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        log_path / "bot.log",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    error_handler = RotatingFileHandler(
        log_path / "errors.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(formatter)
    root.addHandler(error_handler)

    logging.getLogger("aiogram.event").setLevel(logging.INFO)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.INFO)

    resolved_level = logging.getLevelName(level)
    root.info("logging initialized, level=%s", resolved_level)
    root.info("cwd=%s", Path.cwd())
    root.info(
        "log_paths dir=%s bot=%s errors=%s",
        log_path.resolve(),
        (log_path / "bot.log").resolve(),
        (log_path / "errors.log").resolve(),
    )
    root.info("log_config dir_param=%s resolved_dir=%s level_param=%s", log_dir, log_path.resolve(), resolved_level)
    try:
        aiogram_version = __import__("aiogram").__version__
    except Exception:  # pragma: no cover - aiogram should always be importable
        aiogram_version = "unknown"
    root.info("aiogram=%s", aiogram_version)
