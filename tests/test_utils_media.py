from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Iterable
from pathlib import Path

import pytest
from aiogram.types import BufferedInputFile
from aiohttp import ClientError

_UTILS_STUB: types.ModuleType | None = None
if "app.utils" not in sys.modules:
    _UTILS_STUB = types.ModuleType("app.utils")
    _UTILS_STUB.__path__ = [str(Path(__file__).resolve().parents[1] / "app" / "utils")]
    sys.modules["app.utils"] = _UTILS_STUB

import app.utils_media as utils_media  # noqa: E402
from app.utils_media import fetch_image_as_file  # noqa: E402

if _UTILS_STUB is not None:
    sys.modules.pop("app.utils", None)
    importlib.invalidate_caches()


class _DummyResponse:
    def __init__(self, *, status: int = 200, headers: dict[str, str] | None = None, body: bytes = b""):
        self.status = status
        self.headers = headers or {}
        self._body = body

    async def __aenter__(self) -> "_DummyResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401 - signature required by context manager
        return None

    async def read(self) -> bytes:
        return self._body


class _DummyRequestManager:
    def __init__(self, outcome: _DummyResponse | Exception):
        self._outcome = outcome

    async def __aenter__(self) -> _DummyResponse:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        return None


class _DummySession:
    def __init__(self, outcomes: Iterable[_DummyResponse | Exception]):
        self._outcomes = list(outcomes)

    async def __aenter__(self) -> "_DummySession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        return None

    def get(self, url: str, *, allow_redirects: bool = True) -> _DummyRequestManager:  # noqa: ARG002 - parity with aiohttp
        if not self._outcomes:
            raise AssertionError("No configured outcomes for DummySession")
        outcome = self._outcomes.pop(0)
        return _DummyRequestManager(outcome)


def _patch_session(monkeypatch: pytest.MonkeyPatch, outcomes: Iterable[_DummyResponse | Exception]) -> None:
    def _factory(*args, **kwargs) -> _DummySession:  # noqa: ARG001 - signature parity with aiohttp
        return _DummySession(outcomes)

    monkeypatch.setattr(utils_media.aiohttp, "ClientSession", _factory)


@pytest.mark.asyncio
async def test_fetch_image_as_file_success(monkeypatch: pytest.MonkeyPatch) -> None:
    utils_media._IMAGE_CACHE.clear()  # type: ignore[attr-defined]

    async def _noop(_: float) -> None:
        return None

    monkeypatch.setattr(utils_media.asyncio, "sleep", _noop)
    _patch_session(
        monkeypatch,
        [_DummyResponse(headers={"Content-Type": "image/jpeg"}, body=b"raw-bytes")],
    )

    result = await fetch_image_as_file("https://example.com/path/photo.jpg")

    assert isinstance(result, BufferedInputFile)
    assert result.filename == "photo.jpg"
    assert result.data == b"raw-bytes"


@pytest.mark.asyncio
async def test_fetch_image_as_file_content_type_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    utils_media._IMAGE_CACHE.clear()  # type: ignore[attr-defined]

    async def _noop(_: float) -> None:
        return None

    monkeypatch.setattr(utils_media.asyncio, "sleep", _noop)
    _patch_session(
        monkeypatch,
        [_DummyResponse(headers={"Content-Type": "text/html"}, body=b"<html>")],
    )

    result = await fetch_image_as_file("https://example.com/image.png")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_image_as_file_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    utils_media._IMAGE_CACHE.clear()  # type: ignore[attr-defined]

    async def _noop(_: float) -> None:
        return None

    monkeypatch.setattr(utils_media.asyncio, "sleep", _noop)
    _patch_session(
        monkeypatch,
        [ClientError("boom"), ClientError("boom"), ClientError("boom")],
    )

    result = await fetch_image_as_file("https://example.com/image.png", retries=2)

    assert result is None
