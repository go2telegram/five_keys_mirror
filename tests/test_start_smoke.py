"""Smoke tests for the /start flow and home navigation."""

import asyncio
import os
import sys
from contextlib import ExitStack
from importlib import import_module
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram import Dispatcher

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///:memory:")


def _load_start_module():
    """Import the start handler with database constructs patched out."""

    sys.modules.pop("app.handlers.start", None)
    sys.modules.pop("app.db.session", None)

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
        module = import_module("app.handlers.start")

    return module


h_start = _load_start_module()


def _reportlab_stubs() -> dict[str, ModuleType]:
    modules: dict[str, ModuleType] = {}

    # Base packages
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

    def _hex(color: str):  # pragma: no cover - trivial lambda
        return color

    colors.HexColor = _hex
    modules["reportlab.lib.colors"] = colors

    pagesizes = ModuleType("reportlab.lib.pagesizes")
    pagesizes.A4 = (595, 842)
    modules["reportlab.lib.pagesizes"] = pagesizes

    styles = ModuleType("reportlab.lib.styles")
    styles.ParagraphStyle = MagicMock(return_value=MagicMock(name="ParagraphStyle"))

    def _sample_styles():  # pragma: no cover - deterministic return
        return {
            "Title": MagicMock(name="TitleStyle"),
            "Heading2": MagicMock(name="Heading2Style"),
            "BodyText": MagicMock(name="BodyTextStyle"),
        }

    styles.getSampleStyleSheet = _sample_styles
    modules["reportlab.lib.styles"] = styles

    units = ModuleType("reportlab.lib.units")
    units.cm = 28.3
    modules["reportlab.lib.units"] = units

    pdfmetrics = ModuleType("reportlab.pdfbase.pdfmetrics")
    pdfmetrics.registerFont = MagicMock(name="registerFont")
    modules["reportlab.pdfbase.pdfmetrics"] = pdfmetrics

    ttfonts = ModuleType("reportlab.pdfbase.ttfonts")
    ttfonts.TTFont = MagicMock(name="TTFont")
    modules["reportlab.pdfbase.ttfonts"] = ttfonts

    platypus = ModuleType("reportlab.platypus")
    for name in [
        "HRFlowable",
        "ListFlowable",
        "ListItem",
        "Paragraph",
        "SimpleDocTemplate",
        "Spacer",
        "Table",
        "TableStyle",
    ]:
        setattr(platypus, name, MagicMock(name=name))
    modules["reportlab.platypus"] = platypus

    return modules


with patch.dict(sys.modules, _reportlab_stubs(), clear=False):
    main_module = import_module("app.main")


def test_resolve_used_update_types_contains_message_and_callback() -> None:
    """Dispatcher must subscribe to message and callback updates for /start and menus."""

    dp = Dispatcher()
    dp.include_router(h_start.router)

    updates = set(dp.resolve_used_update_types())

    assert "message" in updates
    assert "callback_query" in updates


def test_start_safe_sends_greeting_even_if_full_logic_fails() -> None:
    """The /start safe handler must reply even when the heavy logic errors out."""

    class FailingScope:
        async def __aenter__(self):  # pragma: no cover - exercised in test runtime
            raise RuntimeError("db down")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _run() -> None:
        message = MagicMock()
        message.answer = AsyncMock()
        message.from_user = MagicMock(id=123, username="tester")
        message.text = "/start"

        with patch("app.handlers.start.session_scope", return_value=FailingScope()):
            await h_start.start_safe(message)
            await asyncio.sleep(0)

        message.answer.assert_called()

    asyncio.run(_run())


def test_home_callback_edits_message() -> None:
    """home:main should edit the message and acknowledge the callback."""

    async def _run() -> None:
        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.from_user = MagicMock(id=777, username="tester")
        callback.message = MagicMock()
        callback.message.edit_text = AsyncMock()
        callback.message.answer = AsyncMock()

        await main_module.home_main(callback)

        callback.message.edit_text.assert_awaited()
        callback.answer.assert_awaited()

    asyncio.run(_run())
