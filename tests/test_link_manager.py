import json
import pytest

from app.catalog.loader import load_catalog
from app.links.importer import analyze_payload, parse_payload
from app.links.service import get_register_url
from app.links.storage import LinkSnapshot, export_csv, export_json, load_snapshot, override_storage_path, save_snapshot


@pytest.fixture(autouse=True)
def _reset_links_storage(tmp_path):
    from app.links import storage

    original_path = storage._LINKS_PATH
    override_storage_path(tmp_path / "links.json")

    # Ensure the events table exists for downstream tests that rely on it.
    try:
        from sqlalchemy import create_engine

        from app.config import settings
        from app.db.models import Base

        db_url = settings.DB_URL
        if db_url.startswith("sqlite+"):
            sync_url = db_url.replace("+aiosqlite", "")
        else:
            sync_url = db_url

        engine = create_engine(sync_url)
        try:
            events_table = Base.metadata.tables.get("events")
            if events_table is not None:
                Base.metadata.create_all(engine, tables=[events_table])
        finally:
            engine.dispose()
    except Exception:
        # Table creation is a best-effort precaution; failures should not
        # break tests that do not rely on the database.
        pass

    try:
        yield
    finally:
        override_storage_path(original_path)
        load_catalog(refresh=True)


def _build_full_csv(register_url: str) -> bytes:
    catalog = load_catalog(refresh=True)
    rows = ["type,id,url", f"register,,{register_url}"]
    for product_id in catalog["products"].keys():
        rows.append(f"product,{product_id},https://example.com/{product_id}")
    return "\n".join(rows).encode("utf-8")


def test_csv_import_apply_updates_snapshot():
    data = _build_full_csv("https://example.com/register")
    records = parse_payload(data, filename="links.csv")
    result = analyze_payload(records)

    assert result.can_apply
    assert result.valid_products == result.expected_products
    snapshot = LinkSnapshot(register_url=result.register_url, products=result.product_links)
    save_snapshot(snapshot)

    assert load_snapshot().register_url == "https://example.com/register"
    assert get_register_url(refresh=True) == "https://example.com/register"

    catalog = load_catalog(refresh=True)
    sample_id = next(iter(result.product_links))
    product = catalog["products"][sample_id]
    assert product["order"]["velavie_link"] == result.product_links[sample_id]


def test_json_import_with_unknown_id_warns():
    catalog = load_catalog()
    sample_id = next(iter(catalog["products"].keys()))
    payload = [
        {"type": "register", "url": "https://example.com/register"},
        {"type": "product", "id": sample_id, "url": "https://example.com/valid"},
        {"type": "product", "id": "unknown-product", "url": "https://example.com/bad"},
    ]
    data = json.dumps(payload).encode("utf-8")
    records = parse_payload(data, filename="links.json")
    result = analyze_payload(records)

    assert result.unknown_ids == ["unknown-product"]
    assert not result.can_apply
    assert result.valid_products == 1


def test_export_serializes_snapshot():
    snapshot = LinkSnapshot(
        register_url="https://example.com/reg",
        products={"alpha": "https://example.com/alpha", "beta": "https://example.com/beta"},
    )
    save_snapshot(snapshot)

    json_payload = export_json().decode("utf-8")
    csv_payload = export_csv().decode("utf-8")

    assert "https://example.com/reg" in json_payload
    assert "https://example.com/alpha" in csv_payload
    assert "type,id,url" in csv_payload
