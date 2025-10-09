"""Recommendation coverage audit."""

from __future__ import annotations

from typing import Any

from app.catalog.loader import load_catalog
from app.reco import CTX, product_lines

from . import AuditContext, SectionResult, section


@section("recommendations")
def run(ctx: AuditContext) -> SectionResult:
    catalog = load_catalog()
    products = catalog.get("products") if isinstance(catalog, dict) else None
    if not isinstance(products, dict) or not products:
        return SectionResult(
            name="recommendations",
            status="error",
            summary="Каталог недоступен, рекомендации не проверены.",
        )

    sample = list(products.keys())[:5]
    context_key = "energy_light" if "energy_light" in CTX else next(iter(CTX), "energy_light")
    lines = product_lines(sample, context_key)

    if not lines:
        status = "warn"
        summary = "Рекомендации не сформированы."
    else:
        status = "ok"
        summary = f"Рекомендации: {len(lines)} записей из {len(sample)} продуктов."

    data: dict[str, Any] = {
        "context": context_key,
        "lines": lines,
        "products_sample": sample,
    }

    return SectionResult(
        name="recommendations",
        status=status,
        summary=summary,
        details=[],
        data=data,
    )
