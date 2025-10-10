from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import link_manager


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://example.com", "https://example.com"),
        (" https://example.com/path ", "https://example.com/path"),
        (None, None),
        ("", None),
        ("   ", None),
    ],
)
def test_validate_url_normalizes_whitespace(raw, expected):
    assert link_manager.validate_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "ftp://example.com",
        "https://",
        "https:// example.com",
        "https://exa mple.com",
    ],
)
def test_validate_url_rejects_invalid(raw):
    with pytest.raises(link_manager.LinkValidationError):
        link_manager.validate_url(raw)


@pytest.mark.asyncio
async def test_save_product_link_normalizes_and_calls_repo(monkeypatch):
    entry = SimpleNamespace(id=7, product_id="p1", url="https://example.com/item")
    mock_upsert = AsyncMock(return_value=entry)
    monkeypatch.setattr(link_manager.link_repo, "upsert_product_link", mock_upsert)
    monkeypatch.setattr(link_manager, "allowed_product_ids", lambda: ["p1"])

    session = AsyncMock()
    result = await link_manager.save_product_link(session, 3, "p1", " https://example.com/item ")

    assert result == {"id": 7, "product_id": "p1", "url": "https://example.com/item"}
    mock_upsert.assert_awaited_once()
    called_session, set_id, product_id, url = mock_upsert.await_args.args
    assert called_session is session
    assert set_id == 3
    assert product_id == "p1"
    assert url == "https://example.com/item"


@pytest.mark.asyncio
async def test_save_product_link_rejects_unknown_product(monkeypatch):
    monkeypatch.setattr(link_manager, "allowed_product_ids", lambda: ["known"])
    with pytest.raises(link_manager.LinkValidationError):
        await link_manager.save_product_link(AsyncMock(), 1, "missing", "https://example.com")


@pytest.mark.asyncio
async def test_prepare_link_preview_returns_payload(monkeypatch):
    descriptor = link_manager.ProductDescriptor(product_id="p1", title="Product 1")
    monkeypatch.setattr(link_manager, "_catalog_products", lambda: [descriptor])

    link_set = SimpleNamespace(id=10, title="Test Set")
    monkeypatch.setattr(link_manager.link_repo, "get_set", AsyncMock(return_value=link_set))
    monkeypatch.setattr(
        link_manager.link_repo,
        "load_entries_map",
        AsyncMock(return_value={"p1": "https://example.com"}),
    )

    result = await link_manager.prepare_link_preview(AsyncMock(), 10, "p1")

    assert result == {
        "set": {"id": 10, "title": "Test Set"},
        "product": {"id": "p1", "title": "Product 1"},
        "url": "https://example.com",
    }


@pytest.mark.asyncio
async def test_prepare_link_preview_requires_known_product(monkeypatch):
    monkeypatch.setattr(
        link_manager,
        "_catalog_products",
        lambda: [link_manager.ProductDescriptor(product_id="known", title="Known")],
    )

    with pytest.raises(link_manager.LinkValidationError):
        await link_manager.prepare_link_preview(AsyncMock(), 10, "missing")


@pytest.mark.asyncio
async def test_prepare_link_preview_returns_none_for_missing_set(monkeypatch):
    descriptor = link_manager.ProductDescriptor(product_id="p1", title="Product 1")
    monkeypatch.setattr(link_manager, "_catalog_products", lambda: [descriptor])
    monkeypatch.setattr(link_manager.link_repo, "get_set", AsyncMock(return_value=None))

    result = await link_manager.prepare_link_preview(AsyncMock(), 10, "p1")

    assert result is None


@pytest.mark.asyncio
async def test_prepare_link_preview_requires_filled_url(monkeypatch):
    descriptor = link_manager.ProductDescriptor(product_id="p1", title="Product 1")
    monkeypatch.setattr(link_manager, "_catalog_products", lambda: [descriptor])
    link_set = SimpleNamespace(id=10, title="Test Set")
    monkeypatch.setattr(link_manager.link_repo, "get_set", AsyncMock(return_value=link_set))
    monkeypatch.setattr(
        link_manager.link_repo,
        "load_entries_map",
        AsyncMock(return_value={"p1": None}),
    )

    with pytest.raises(link_manager.LinkValidationError):
        await link_manager.prepare_link_preview(AsyncMock(), 10, "p1")
