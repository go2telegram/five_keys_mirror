"""Concurrent smoke test for core API calls."""

from __future__ import annotations

import asyncio
import statistics
import time
from typing import Any, List

from app.catalog.loader import load_catalog
from app.utils.cards import prepare_cards

from . import AuditContext, SectionResult, section

_CONCURRENCY = 50


async def _worker(sample: list[str], ctx_key: str) -> tuple[float, str | None]:
    start = time.perf_counter()
    try:
        load_catalog()
        cards = prepare_cards(sample, ctx_key)
        if not cards:
            raise RuntimeError("prepare_cards вернул пустой список")
    except Exception as exc:  # pragma: no cover - surfaced in audit output
        return time.perf_counter() - start, str(exc)
    return time.perf_counter() - start, None


@section("load_smoke")
def run(ctx: AuditContext) -> SectionResult:
    catalog = load_catalog()
    products = catalog.get("products") if isinstance(catalog, dict) else None
    if not isinstance(products, dict) or not products:
        return SectionResult(
            name="load_smoke",
            status="error",
            summary="Каталог недоступен, нагрузочный тест пропущен.",
        )

    sample = list(products.keys())[:5]
    ctx_key = "energy_light"

    async def _run() -> tuple[List[float], List[str]]:
        tasks = [_worker(sample, ctx_key) for _ in range(_CONCURRENCY)]
        results = await asyncio.gather(*tasks)
        durations = [duration for duration, _ in results]
        errors = [msg for _, msg in results if msg]
        return durations, errors

    durations, errors = asyncio.run(_run())

    if errors:
        status = "warn"
        summary = f"Нагрузочный смоук: ошибки ({len(errors)})."
    else:
        status = "ok"
        summary = "Нагрузочный смоук выполнен без ошибок."

    p50 = statistics.median(durations) if durations else 0.0
    p95 = statistics.quantiles(durations, n=100)[94] if len(durations) >= 2 else p50

    data: dict[str, Any] = {
        "p50": p50,
        "p95": p95,
        "errors": errors,
        "sample": sample,
    }

    details: list[str] = []
    if errors:
        details.extend(errors[:5])

    summary += f" P50={p50 * 1000:.1f}мс, P95={p95 * 1000:.1f}мс."

    return SectionResult(
        name="load_smoke",
        status=status,
        summary=summary,
        details=details,
        data=data,
    )
