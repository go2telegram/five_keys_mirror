"""Configuration helpers for analytics ETL."""
from __future__ import annotations

import os
from pathlib import Path

CLICKHOUSE_URL = os.getenv("CLICKHOUSE_URL", "http://localhost:8123")
DATA_DIR = Path(os.getenv("DATA_DIR", "data")).resolve()
LOGS_DIR = Path(os.getenv("LOGS_DIR", "logs")).resolve()

__all__ = ["CLICKHOUSE_URL", "DATA_DIR", "LOGS_DIR"]
