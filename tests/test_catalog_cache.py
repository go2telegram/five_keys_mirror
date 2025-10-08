import asyncio

import pytest

from app import cache as cache_module
from app.services import catalog_service


@pytest.fixture(autouse=True)
def _clear_cache():
    asyncio.run(cache_module.clear_cache())
    yield
    asyncio.run(cache_module.clear_cache())


def test_catalog_search_cache_hit(monkeypatch):
    calls = {"count": 0}
    catalog_payload = {
        "products": {
            "foo": {
                "id": "foo",
                "title": "Foo Bar",
                "short": "Test product",
                "order": {"velavie_link": "https://example.com"},
            }
        },
        "aliases": {},
        "ordered": ["foo"],
        "version": "v1",
    }

    def fake_load_catalog():
        calls["count"] += 1
        return catalog_payload

    monkeypatch.setattr(catalog_service, "load_catalog", fake_load_catalog)
    monkeypatch.setattr(cache_module, "catalog_version", lambda: "v1")

    async def _runner():
        result1 = await catalog_service.catalog_search("foo")
        result2 = await catalog_service.catalog_search("foo")

        assert calls["count"] == 1
        assert result1 == result2
        assert result1[0]["id"] == "foo"

    asyncio.run(_runner())


def test_catalog_cache_invalidation_on_version_change(monkeypatch):
    calls = {"count": 0}
    catalog_payload = {
        "products": {
            "foo": {
                "id": "foo",
                "title": "Foo Bar",
                "short": "Test product",
                "order": {"velavie_link": "https://example.com"},
            }
        },
        "aliases": {},
        "ordered": ["foo"],
        "version": "v1",
    }

    def fake_load_catalog():
        calls["count"] += 1
        return catalog_payload

    monkeypatch.setattr(catalog_service, "load_catalog", fake_load_catalog)

    version_holder = {"value": "v1"}
    monkeypatch.setattr(cache_module, "catalog_version", lambda: version_holder["value"])

    async def _first_call():
        await catalog_service.catalog_search("foo")

    asyncio.run(_first_call())
    assert calls["count"] == 1

    version_holder["value"] = "v2"
    catalog_payload = {
        "products": {
            "foo": {
                "id": "foo",
                "title": "Foo Baz",
                "short": "Updated",
                "order": {"velavie_link": "https://example.com"},
            }
        },
        "aliases": {},
        "ordered": ["foo"],
        "version": "v2",
    }
    async def _second_call():
        await catalog_service.catalog_search("foo")

    asyncio.run(_second_call())
    assert calls["count"] == 2


def test_get_reco_uses_cache(monkeypatch):
    calls = {"count": 0}

    async def fake_loader(user_id: int):
        calls["count"] += 1
        return [f"item-{user_id}"]

    monkeypatch.setattr(catalog_service, "_load_user_plan_products", fake_loader)
    monkeypatch.setattr(cache_module, "catalog_version", lambda: "v1")

    async def _runner():
        result1 = await catalog_service.get_reco(42)
        result2 = await catalog_service.get_reco(42)

        assert calls["count"] == 1
        assert result1 == result2 == ["item-42"]

    asyncio.run(_runner())
