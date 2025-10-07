from app.catalog.report import build_catalog_summary_from_payload


def test_catalog_summary_counts() -> None:
    payload = {
        "products": [
            {
                "id": "p1",
                "available": True,
                "image": "/static/products/p1.jpg",
                "order": {
                    "velavie_link": "https://example.test/?utm_source=a&utm_medium=b&utm_campaign=c&utm_content=p1"
                },
                "goals": ["Energy"],
                "category": "supplements",
            },
            {
                "id": "p2",
                "available": False,
                "images": [],
                "order": {},
                "goals": [],
                "category": None,
            },
        ]
    }

    summary = build_catalog_summary_from_payload(payload)
    assert summary.total == 2
    assert summary.available == 1
    assert summary.with_goals == 1
    assert summary.missing_images == 1
    assert summary.missing_order == 1
    assert summary.categories["supplements"] == 1
    assert summary.categories["(uncategorized)"] == 1

    text = summary.format()
    assert "Всего продуктов: 2" in text
    assert "Категории:" in text
    assert "• supplements: 1" in text
