from app.catalog.loader import load_catalog, product_by_alias, product_by_id, select_by_goals


def test_catalog_minimum_size():
    data = load_catalog(refresh=True)
    assert len(data["products"]) >= 1


def test_product_lookup_by_alias_and_id():
    catalog = load_catalog()
    any_id = next(iter(catalog["products"]))
    assert product_by_id(any_id)
    assert product_by_alias(any_id.upper())


def test_select_by_goals_returns_results():
    items = select_by_goals(["energy"])
    assert 0 <= len(items) <= 6
    assert all(isinstance(item, dict) for item in items)
