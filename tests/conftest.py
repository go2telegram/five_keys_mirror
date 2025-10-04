"""Test configuration helpers."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def anyio_backend() -> str:
    """Force anyio-based tests to run only on the asyncio backend."""

    return "asyncio"
