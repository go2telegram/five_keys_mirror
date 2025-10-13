import asyncio
import textwrap
from urllib.parse import parse_qs, urlsplit

import pytest

from app import link_manager
from app.config import settings
from app.utils.cards import build_order_link


@pytest.fixture(autouse=True)
def _isolate_link_manager(tmp_path, monkeypatch):
    base = tmp_path / "links"
    monkeypatch.setattr(link_manager, "SETS_DIR", base / "sets")
    monkeypatch.setattr(link_manager, "ACTIVE_SET_FILE", base / "active_set.txt")
    monkeypatch.setattr(link_manager, "AUDIT_LOG", base / "audit.jsonl")
    monkeypatch.setattr(link_manager, "_CACHE_LOCK", asyncio.Lock())
    monkeypatch.setattr(link_manager, "_ACTIVE_LOCK", asyncio.Lock())
    monkeypatch.setattr(link_manager, "_schedule_ping", lambda url: None)
    link_manager._ACTIVE_SET = None
    link_manager._LOADED_SET = None
    link_manager._REGISTER_LINK = None
    link_manager._PRODUCT_LINKS = {}
    monkeypatch.setattr(settings, "BASE_PRODUCT_URL", "https://example.com/products")
    monkeypatch.setattr(settings, "BASE_REGISTER_URL", "https://example.com/register")
    monkeypatch.setattr(settings, "VELAVIE_URL", "")
    monkeypatch.setattr(settings, "LINK_AUTOBUILD", True)
    yield
    link_manager._ACTIVE_SET = None
    link_manager._LOADED_SET = None
    link_manager._REGISTER_LINK = None
    link_manager._PRODUCT_LINKS = {}


@pytest.mark.asyncio
async def test_register_and_product_overrides(
    monkeypatch, tmp_path, tmp_path_factory, _isolate_link_manager, **_
):
    assert await link_manager.get_register_link() == "https://example.com/register"
    with link_manager.audit_actor(101):
        await link_manager.set_register_link("https://demo.example/reg")
    export_after = await link_manager.export_set()
    assert export_after["register"] == "https://demo.example/reg"
    assert link_manager._REGISTER_LINK == "https://demo.example/reg"
    assert await link_manager.get_register_link() == "https://demo.example/reg"

    with link_manager.audit_actor(101):
        await link_manager.set_product_link("prod-a", "https://shop.example/a")
    assert await link_manager.get_product_link("prod-a") == "https://shop.example/a"

    with link_manager.audit_actor(101):
        await link_manager.delete_product_link("prod-a")
    assert await link_manager.get_product_link("prod-a") == "https://example.com/products/prod-a"

    monkeypatch.setattr(settings, "LINK_AUTOBUILD", False)
    assert await link_manager.get_product_link("prod-a") is None


@pytest.mark.asyncio
async def test_switch_and_export_sets(tmp_path, tmp_path_factory, _isolate_link_manager, **_):
    with link_manager.audit_actor(42):
        await link_manager.set_register_link("https://demo.example/reg-main")
        await link_manager.set_product_link("primary", "https://shop.example/primary")

    export_default = await link_manager.export_set()
    assert export_default["register"] == "https://demo.example/reg-main"
    assert export_default["products"]["primary"] == "https://shop.example/primary"

    await link_manager.switch_set("stage")
    assert await link_manager.active_set_name() == "stage"
    assert await link_manager.get_all_product_links() == {}

    with link_manager.audit_actor(42):
        await link_manager.set_product_link("stage-item", "https://shop.example/stage")

    await link_manager.switch_set("default")
    all_links = await link_manager.get_all_product_links()
    assert "primary" in all_links
    assert all_links["primary"] == "https://shop.example/primary"


@pytest.mark.asyncio
async def test_bulk_links_and_listing(tmp_path, tmp_path_factory, _isolate_link_manager, **_):
    payload = {"alpha": "https://shop.example/alpha", "beta": "https://shop.example/beta"}
    with link_manager.audit_actor(7):
        await link_manager.set_bulk_links(payload)
    stored = await link_manager.get_all_product_links()
    assert stored == payload

    exported = await link_manager.export_set()
    assert exported["products"] == payload

    sets = await link_manager.list_sets()
    assert "default" in sets


@pytest.mark.asyncio
async def test_build_order_link_adds_utms(tmp_path, tmp_path_factory, _isolate_link_manager, **_):
    url = await build_order_link("item-1", "catalog", base_url="https://example.com/buy")
    parsed = urlsplit(url)
    params = parse_qs(parsed.query)
    assert params["utm_source"] == ["tg_bot"]
    assert params["utm_medium"] == ["catalog"]
    assert params["utm_campaign"] == ["catalog"]
    assert params["utm_content"] == ["item-1"]

    existing = await build_order_link(
        "item-2",
        "recommend",
        base_url="https://example.com/go?utm_source=custom",
    )
    params_existing = parse_qs(urlsplit(existing).query)
    assert params_existing["utm_source"] == ["custom"]
    assert params_existing["utm_medium"] == ["recommend"]
    assert params_existing["utm_campaign"] == ["recommend"]
    assert params_existing["utm_content"] == ["item-2"]


@pytest.mark.asyncio
async def test_import_set_json_and_apply(tmp_path, tmp_path_factory, _isolate_link_manager, **_):
    payload = {
        "register": "https://demo.example/reg-new",
        "products": {
            "alpha": "https://shop.example/alpha",
            "beta": "https://shop.example/beta",
        },
    }
    preview = await link_manager.import_set(payload, apply=False)
    assert preview["register"] == payload["register"]
    assert preview["products"] == payload["products"]
    assert preview["warnings"] == []
    assert preview["applied"] is False

    with link_manager.audit_actor(9):
        applied = await link_manager.import_set(payload, apply=True)

    assert applied["applied"] is True
    assert await link_manager.get_register_link() == payload["register"]
    assert await link_manager.get_product_link("alpha") == payload["products"]["alpha"]
    csv_snapshot = await link_manager.export_set_csv()
    assert "register,https://demo.example/reg-new" in csv_snapshot


@pytest.mark.asyncio
async def test_import_set_csv_support(tmp_path, tmp_path_factory, _isolate_link_manager, **_):
    csv_payload = textwrap.dedent(
        """
        product_id,url
        register,https://demo.example/register
        alpha,https://shop.example/alpha
        invalid,not-a-url
        ,https://shop.example/missing
        """
    ).strip()

    preview = await link_manager.import_set(csv_payload, target="stage", apply=False)
    assert preview["set"] == "stage"
    assert preview["register"] == "https://demo.example/register"
    assert "alpha" in preview["products"]
    assert "invalid" not in preview["products"]
    assert preview["applied"] is False
    assert preview["warnings"]

    staged_payload = {
        "register": preview["register"],
        "products": preview["products"],
    }

    with link_manager.audit_actor(11):
        applied = await link_manager.import_set(staged_payload, target="stage", apply=True)

    assert applied["applied"] is True
    assert await link_manager.active_set_name() == "default"

    await link_manager.switch_set("stage")
    assert await link_manager.get_register_link() == "https://demo.example/register"
    assert await link_manager.get_product_link("alpha") == "https://shop.example/alpha"
