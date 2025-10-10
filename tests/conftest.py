"""Test configuration helpers."""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        "asyncio_default_fixture_loop_scope",
        "Default asyncio fixture loop scope",
        default="function",
    )
    parser.addini(
        "plugins",
        "Additional pytest plugins",
        type="linelist",
        default=[],
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the asyncio marker for the lightweight runner below."""

    config.addinivalue_line("markers", "asyncio: execute the test inside an event loop")


def pytest_sessionstart(session: pytest.Session) -> None:  # noqa: ARG001 - hook signature
    """Ensure the SQLite schema exists before the async tests run."""

    try:
        from app.db.models import Base
        from app.db.session import async_engine
    except Exception:
        return

    if async_engine is None:  # pragma: no cover - driver missing in CI sandbox
        return

    async def _create() -> None:
        async with async_engine.begin() as conn:  # type: ignore[union-attr]
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Execute ``@pytest.mark.asyncio`` tests without requiring pytest-asyncio."""

    marker = pyfuncitem.get_closest_marker("asyncio")
    if marker is None:
        return None

    func = pyfuncitem.obj
    if not asyncio.iscoroutinefunction(func):
        return None

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(func(**pyfuncitem.funcargs))
    finally:
        asyncio.set_event_loop(None)
        loop.close()
    return True


if "reportlab" not in sys.modules:
    reportlab = types.ModuleType("reportlab")
    from importlib.machinery import ModuleSpec

    def _set_spec(name: str, module: types.ModuleType) -> None:
        module.__spec__ = ModuleSpec(name, loader=None)

    _set_spec("reportlab", reportlab)
    sys.modules["reportlab"] = reportlab

    lib_mod = types.ModuleType("reportlab.lib")
    _set_spec("reportlab.lib", lib_mod)
    reportlab.lib = lib_mod
    sys.modules["reportlab.lib"] = lib_mod

    colors_mod = types.ModuleType("reportlab.lib.colors")
    _set_spec("reportlab.lib.colors", colors_mod)

    def HexColor(value):  # noqa: N802
        return str(value)

    colors_mod.HexColor = HexColor
    lib_mod.colors = colors_mod
    sys.modules["reportlab.lib.colors"] = colors_mod

    pagesizes_mod = types.ModuleType("reportlab.lib.pagesizes")
    _set_spec("reportlab.lib.pagesizes", pagesizes_mod)
    pagesizes_mod.A4 = (595.0, 842.0)
    lib_mod.pagesizes = pagesizes_mod
    sys.modules["reportlab.lib.pagesizes"] = pagesizes_mod

    styles_mod = types.ModuleType("reportlab.lib.styles")
    _set_spec("reportlab.lib.styles", styles_mod)

    class ParagraphStyle:  # noqa: D401 - stub
        def __init__(self, name: str, **kwargs):
            self.name = name
            self.kwargs = kwargs

    def getSampleStyleSheet():  # noqa: D401 - stub
        base = ParagraphStyle("BodyText")
        return {
            "Title": ParagraphStyle("Title"),
            "Heading2": ParagraphStyle("Heading2"),
            "BodyText": base,
        }

    styles_mod.ParagraphStyle = ParagraphStyle
    styles_mod.getSampleStyleSheet = getSampleStyleSheet
    lib_mod.styles = styles_mod
    sys.modules["reportlab.lib.styles"] = styles_mod

    units_mod = types.ModuleType("reportlab.lib.units")
    _set_spec("reportlab.lib.units", units_mod)
    units_mod.cm = 28.35
    lib_mod.units = units_mod
    sys.modules["reportlab.lib.units"] = units_mod

    pdfbase_mod = types.ModuleType("reportlab.pdfbase")
    _set_spec("reportlab.pdfbase", pdfbase_mod)
    reportlab.pdfbase = pdfbase_mod
    sys.modules["reportlab.pdfbase"] = pdfbase_mod

    pdfmetrics_mod = types.ModuleType("reportlab.pdfbase.pdfmetrics")
    _set_spec("reportlab.pdfbase.pdfmetrics", pdfmetrics_mod)
    _fonts: set[str] = set()

    def registerFont(font):  # noqa: D401 - stub
        name = getattr(font, "name", str(font))
        _fonts.add(name)

    def getRegisteredFontNames():  # noqa: D401 - stub
        return list(_fonts)

    pdfmetrics_mod.registerFont = registerFont
    pdfmetrics_mod.getRegisteredFontNames = getRegisteredFontNames
    pdfbase_mod.pdfmetrics = pdfmetrics_mod
    sys.modules["reportlab.pdfbase.pdfmetrics"] = pdfmetrics_mod

    ttfonts_mod = types.ModuleType("reportlab.pdfbase.ttfonts")
    _set_spec("reportlab.pdfbase.ttfonts", ttfonts_mod)

    class TTFont:  # noqa: D401 - stub
        def __init__(self, name: str, path: str) -> None:
            self.name = name
            self.path = path

    ttfonts_mod.TTFont = TTFont
    pdfbase_mod.ttfonts = ttfonts_mod
    sys.modules["reportlab.pdfbase.ttfonts"] = ttfonts_mod

    graphics_mod = types.ModuleType("reportlab.graphics")
    _set_spec("reportlab.graphics", graphics_mod)
    reportlab.graphics = graphics_mod
    sys.modules["reportlab.graphics"] = graphics_mod

    shapes_mod = types.ModuleType("reportlab.graphics.shapes")
    _set_spec("reportlab.graphics.shapes", shapes_mod)

    class Drawing:  # noqa: D401 - stub
        def __init__(self, width, height, transform=None):  # noqa: ANN001, ANN002
            self.width = width
            self.height = height
            self.transform = transform
            self.children = []

        def add(self, item):  # noqa: ANN001
            self.children.append(item)

    shapes_mod.Drawing = Drawing
    graphics_mod.shapes = shapes_mod
    sys.modules["reportlab.graphics.shapes"] = shapes_mod

    barcode_mod = types.ModuleType("reportlab.graphics.barcode")
    _set_spec("reportlab.graphics.barcode", barcode_mod)
    graphics_mod.barcode = barcode_mod
    sys.modules["reportlab.graphics.barcode"] = barcode_mod

    qr_mod = types.ModuleType("reportlab.graphics.barcode.qr")
    _set_spec("reportlab.graphics.barcode.qr", qr_mod)

    class QrCodeWidget:  # noqa: D401 - stub
        def __init__(self, data: str) -> None:
            self.data = data

        def getBounds(self):  # noqa: D401
            return (0.0, 0.0, 1.0, 1.0)

    qr_mod.QrCodeWidget = QrCodeWidget
    barcode_mod.qr = qr_mod
    sys.modules["reportlab.graphics.barcode.qr"] = qr_mod

    platypus_mod = types.ModuleType("reportlab.platypus")
    _set_spec("reportlab.platypus", platypus_mod)
    sys.modules["reportlab.platypus"] = platypus_mod

    class Paragraph:  # noqa: D401 - stub
        def __init__(self, text: str, style=None) -> None:  # noqa: ANN001
            self.text = text
            self.style = style

        def render(self) -> str:
            return self.text

    class Spacer:  # noqa: D401 - stub
        def __init__(self, *_args, **_kwargs) -> None:  # noqa: ANN001, ANN002
            pass

        def render(self) -> str:
            return ""

    class HRFlowable:  # noqa: D401 - stub
        def __init__(self, **_kwargs) -> None:  # noqa: ANN001
            pass

        def render(self) -> str:
            return "----"

    class ListItem:  # noqa: D401 - stub
        def __init__(self, flowable, **_kwargs) -> None:  # noqa: ANN001, ANN002
            self.flowable = flowable

        def render(self) -> str:
            return getattr(self.flowable, "render", lambda: str(self.flowable))()

    class ListFlowable:  # noqa: D401 - stub
        def __init__(self, items, **_kwargs) -> None:  # noqa: ANN001, ANN002
            self.items = items

        def render(self) -> str:
            return "\n".join(item.render() for item in self.items)

    class Table:  # noqa: D401 - stub
        def __init__(self, data, **_kwargs) -> None:  # noqa: ANN001, ANN002
            self.data = data

        def render(self) -> str:
            return "\n".join(",".join(str(cell) for cell in row) for row in self.data)

        def setStyle(self, *_args, **_kwargs) -> None:  # noqa: ANN001, ANN002
            return None

    class TableStyle:  # noqa: D401 - stub
        def __init__(self, *_args, **_kwargs) -> None:  # noqa: ANN001, ANN002
            pass

    class _Canvas:  # noqa: D401 - stub
        def __init__(self) -> None:
            self.operations: list[tuple[str, tuple, dict]] = []

        def _record(self, name: str, *args, **kwargs) -> None:
            self.operations.append((name, args, kwargs))

        def setFont(self, *args, **kwargs) -> None:  # noqa: ANN001, ANN002
            self._record("setFont", *args, **kwargs)

        def setFillColor(self, *args, **kwargs) -> None:  # noqa: ANN001, ANN002
            self._record("setFillColor", *args, **kwargs)

        def drawRightString(self, *args, **kwargs) -> None:  # noqa: ANN001, ANN002
            self._record("drawRightString", *args, **kwargs)

        # reportlab canvas compat helpers used in some flows
        def saveState(self) -> None:
            self._record("saveState")

        def restoreState(self) -> None:
            self._record("restoreState")

    class SimpleDocTemplate:  # noqa: D401 - stub
        def __init__(self, buffer, **_kwargs) -> None:  # noqa: ANN001, ANN002
            self.buffer = buffer
            self.page = 1

        def build(self, story, onFirstPage=None, onLaterPages=None) -> None:  # noqa: ANN001
            parts = []
            for element in story:
                render = getattr(element, "render", None)
                if callable(render):
                    rendered = render()
                elif hasattr(element, "text"):
                    rendered = str(element.text)
                else:
                    rendered = str(element)
                if rendered:
                    parts.append(rendered)

            canvas = _Canvas()
            if callable(onFirstPage):
                self.page = 1
                onFirstPage(canvas, self)
            if callable(onLaterPages):
                self.page += 1
                onLaterPages(canvas, self)

            body = "\n".join(parts)
            pseudo = "%PDF-FAKE\n" + body
            if len(pseudo) < 1500:
                pseudo = pseudo + "\n" + ("." * (1500 - len(pseudo)))
            pseudo += "\n%%EOF"
            self.buffer.write(pseudo.encode("utf-8"))

    platypus_mod.Paragraph = Paragraph
    platypus_mod.Spacer = Spacer
    platypus_mod.HRFlowable = HRFlowable
    platypus_mod.ListFlowable = ListFlowable
    platypus_mod.ListItem = ListItem
    platypus_mod.Table = Table
    platypus_mod.TableStyle = TableStyle
    platypus_mod.SimpleDocTemplate = SimpleDocTemplate


@pytest.fixture
def anyio_backend() -> str:
    """Force anyio-based tests to run only on the asyncio backend."""

    return "asyncio"
