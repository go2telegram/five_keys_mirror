"""Calculator smoke tests for self-audit."""

from __future__ import annotations

from typing import Any, Dict

from app.calculators.engine import CALCULATORS, CalculationContext

from . import AuditContext, SectionResult, section

_SCENARIOS: dict[str, Dict[str, Any]] = {
    "water": {"weight": 70, "activity": "moderate", "climate": "temperate"},
    "kcal": {
        "sex": "m",
        "age": 32,
        "weight": 78.5,
        "height": 178,
        "activity": "155",
        "goal": "maintain",
    },
    "macros": {"weight": 70, "goal": "maintain", "preference": "balanced"},
    "bmi": {"height": 180, "weight": 80},
}


@section("calculators")
def run(ctx: AuditContext) -> SectionResult:
    results: dict[str, Any] = {}
    errors: list[str] = []

    for slug, payload in _SCENARIOS.items():
        definition = CALCULATORS.get(slug)
        if definition is None:
            errors.append(f"Калькулятор {slug} не найден.")
            continue
        context = CalculationContext(data=payload, user_id=0, username=None)
        try:
            result = definition.build_result(context)
        except Exception as exc:  # pragma: no cover - surfaced in audit output
            errors.append(f"{slug}: не удалось построить результат ({exc}).")
            continue
        summary = {
            "headline": result.headline,
            "cards": len(result.cards),
            "bullets": len(result.bullets),
        }
        results[slug] = summary

    if errors:
        status = "error"
        details = errors
    else:
        status = "ok"
        details = [f"Проверено калькуляторов: {len(results)}."]

    summary_text = ", ".join(f"{slug}: {info['cards']} карточек" for slug, info in results.items())
    if not summary_text:
        summary_text = "Калькуляторы не проверены."

    return SectionResult(
        name="calculators",
        status=status,
        summary=summary_text,
        details=details,
        data=results,
    )
