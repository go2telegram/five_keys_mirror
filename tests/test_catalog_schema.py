import json
from pathlib import Path

import pytest

from tools import catalog_build


def test_catalog_matches_schema() -> None:
    payload = catalog_build.validate_catalog()
    assert isinstance(payload.get("products"), list)
    assert payload["products"]


def test_catalog_schema_requires_mandatory_fields(tmp_path: Path) -> None:
    broken = tmp_path / "catalog.json"
    broken.write_text(
        json.dumps(
            {
                "products": [
                    {
                        "id": "sample",
                        "title": "Sample",
                        "images": ["https://example.com/sample.jpg"],
                        "order": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(catalog_build.CatalogValidationError) as excinfo:
        catalog_build.validate_catalog(broken)

    assert "velavie_link" in str(excinfo.value)
