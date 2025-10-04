"""Smoke tests ensuring /start and home navigation emit log records."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import ExitStack, suppress
from importlib import import_module
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///:memory:")


def _reportlab_stubs() -> dict[str, ModuleType]:
    modules: dict[str, ModuleType] = {}

    modules["reportlab"] = ModuleType("reportlab")
    modules["reportlab.graphics"] = ModuleType("reportlab.graphics")
    modules["reportlab.lib"] = ModuleType("reportlab.lib")
    modules["reportlab.pdfbase"] = ModuleType("reportlab.pdfbase")

    barcode = ModuleType("reportlab.graphics.barcode")
    barcode.qr = MagicMock(name="qr")
    modules["reportlab.graphics.barcode"] = barcode

    shapes = ModuleType("reportlab.graphics.shapes")
    shapes.Drawing = MagicMock(name="Drawing")
    modules["reportlab.graphics.shapes"] = shapes

    colors = ModuleType("reportlab.lib.colors")

    def _hex(color: str):  # pragma: no cover - deterministic mapping
        return color

    colors.HexColor = _hex
    modules["reportlab.lib.colors"] = colors

    pagesizes = ModuleType("reportlab.lib.pagesizes")
    pagesizes.A4 = (595, 842)
    modules["reportlab.lib.pagesizes"] = pagesizes

    units = ModuleType("reportlab.lib.units")
    units.cm = 1
    modules["reportlab.lib.units"] = units

    styles = ModuleType("reportlab.lib.styles")
    styles.ParagraphStyle = MagicMock(name="ParagraphStyle")

    def _sample_styles():  # pragma: no cover - deterministic structure
        return {"Normal": MagicMock(name="NormalStyle")}

    styles.getSampleStyleSheet = _sample_styles
    modules["reportlab.lib.styles"] = styles

    platypus = ModuleType("reportlab.platypus")
    platypus.SimpleDocTemplate = MagicMock(name="SimpleDocTemplate")
    platypus.Paragraph = MagicMock(name="Paragraph")
    platypus.Spacer = MagicMock(name="Spacer")
    platypus.HRFlowable = MagicMock(name="HRFlowable")
    platypus.ListFlowable = MagicMock(name="ListFlowable")
    platypus.ListItem = MagicMock(name="ListItem")
    platypus.Table = MagicMock(name="Table")
    platypus.TableStyle = MagicMock(name="TableStyle")
    modules["reportlab.platypus"] = platypus

    pdfbase = ModuleType("reportlab.pdfbase.pdfmetrics")
    pdfbase.registerFont = MagicMock(name="registerFont")
    modules["reportlab.pdfbase.pdfmetrics"] = pdfbase

    ttfonts = ModuleType("reportlab.pdfbase.ttfonts")
    ttfonts.TTFont = MagicMock(name="TTFont")
    modules["reportlab.pdfbase.ttfonts"] = ttfonts

    return modules


def _load_module(name: str):
    """Import a module with the async SQLAlchemy engine patched out."""

    for module in ["app.handlers.start", "app.db.session", "app.main"]:
        if module != name:
            sys.modules.pop(module, None)
    sys.modules.pop(name, None)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sqlalchemy.ext.asyncio.create_async_engine",
                return_value=MagicMock(name="async_engine"),
            )
        )
        stack.enter_context(
            patch(
                "sqlalchemy.ext.asyncio.async_sessionmaker",
                return_value=MagicMock(name="async_session_factory"),
            )
        )
        stack.enter_context(patch.dict(sys.modules, _reportlab_stubs(), clear=False))
        module = import_module(name)

    return module


h_start = _load_module("app.handlers.start")
home_module = _load_module("app.main")
home_main = home_module.home_main


@pytest.mark.anyio("asyncio")
async def test_start_logs_and_answers(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    message = SimpleNamespace()
    message.text = "/start"
    message.from_user = SimpleNamespace(id=555, username="tester")

    recorded: dict[str, object] = {}

    async def fake_answer(text, reply_markup=None):  # pragma: no cover - simple stub
        recorded["answer"] = (text, reply_markup)

    message.answer = fake_answer

    loop = asyncio.get_running_loop()

    def _fake_create_task(coro):
        with suppress(Exception):  # pragma: no cover - best effort cleanup
            coro.close()
        fut = loop.create_future()
        fut.set_result(None)
        return fut

    monkeypatch.setattr(asyncio, "create_task", _fake_create_task)

    with caplog.at_level(logging.INFO, logger="start"):
        await h_start.start_safe(message)

    assert "START uid=555" in caplog.text
    assert "answer" in recorded


class _DummyMessage:
    def __init__(self) -> None:
        self.answer_called = False

    async def edit_text(self, *args, **kwargs):  # pragma: no cover - forced failure path
        raise RuntimeError("cannot edit")

    async def answer(self, *args, **kwargs):
        self.answer_called = True


class _DummyCallback:
    def __init__(self) -> None:
        self.message = _DummyMessage()
        self.data = "home:main"
        self.from_user = SimpleNamespace(id=777, username="navigator")
        self._answered = False

    async def answer(self):
        self._answered = True


@pytest.mark.anyio("asyncio")
async def test_home_main_logs_and_falls_back(caplog: pytest.LogCaptureFixture) -> None:
    callback = _DummyCallback()

    with caplog.at_level(logging.INFO, logger="home"):
        await home_main(callback)

    assert "HOME pressed uid=777" in caplog.text
    assert callback.message.answer_called is True
    assert callback._answered is True
