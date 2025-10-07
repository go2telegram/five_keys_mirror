import pytest
from aiogram.types import User

from app.catalog.loader import CatalogError
from app.config import settings
from app.handlers import admin as admin_module


class DummyMessage:
    def __init__(self, user_id: int) -> None:
        self.from_user = User(id=user_id, is_bot=False, first_name="Admin")
        self.text = ""
        self.answers: list[str] = []

    async def answer(self, text: str, **_kwargs) -> None:  # noqa: ANN001
        self.answers.append(text)


@pytest.mark.asyncio
async def test_catalog_report_uses_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    settings.ADMIN_ID = 100
    message = DummyMessage(100)

    class _Summary:
        def format(self) -> str:  # noqa: D401
            return "summary text"

    monkeypatch.setattr(admin_module, "build_catalog_summary", lambda refresh=False: _Summary())

    await admin_module.catalog_report(message)  # type: ignore[arg-type]
    assert message.answers == ["summary text"]


@pytest.mark.asyncio
async def test_catalog_report_handles_error(monkeypatch: pytest.MonkeyPatch) -> None:
    settings.ADMIN_ID = 101
    message = DummyMessage(101)

    def _raise(*, refresh: bool = False) -> None:  # noqa: D401, ANN001, ANN202
        raise CatalogError("broken")

    monkeypatch.setattr(admin_module, "build_catalog_summary", _raise)

    await admin_module.catalog_report(message)  # type: ignore[arg-type]
    assert any("не удалось" in text.lower() for text in message.answers)


@pytest.mark.asyncio
async def test_catalog_reload_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    settings.ADMIN_ID = 200
    message = DummyMessage(200)
    called: dict[str, bool] = {}

    def _load(*, refresh: bool = False):  # noqa: ANN001, ANN202
        called["refresh"] = refresh

    monkeypatch.setattr(admin_module, "load_catalog", _load)

    await admin_module.catalog_reload(message)  # type: ignore[arg-type]
    assert called.get("refresh") is True
    assert any("перезагружен" in text.lower() for text in message.answers)


@pytest.mark.asyncio
async def test_catalog_reload_handles_error(monkeypatch: pytest.MonkeyPatch) -> None:
    settings.ADMIN_ID = 201
    message = DummyMessage(201)

    def _load(*, refresh: bool = False):  # noqa: ANN001, ANN202
        raise CatalogError("oops")

    monkeypatch.setattr(admin_module, "load_catalog", _load)

    await admin_module.catalog_reload(message)  # type: ignore[arg-type]
    assert any("не удалось" in text.lower() for text in message.answers)
