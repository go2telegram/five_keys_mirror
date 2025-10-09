from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.reco import ai_reasoner


@pytest.mark.asyncio
async def test_ai_plan_prompt_structure_ru(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = {"lang": "ru", "allergies": ["мёд"]}
    reco_items = [
        {
            "id": "t8-extra",
            "title": "T8 EXTRA",
            "utm_category": "energy",
            "why": "Энергия на день",
            "tags": ["energy", "mct"],
        },
        {
            "id": "magnesium-b6",
            "title": "Magnesium + B6",
            "utm_category": "sleep",
            "why": "Спокойный сон",
            "tags": ["sleep_support"],
        },
    ]

    monkeypatch.setattr(ai_reasoner, "get_user_profile", AsyncMock(return_value=profile))
    monkeypatch.setattr(ai_reasoner, "get_user_quiz_results", AsyncMock(return_value=[{"slug": "sleep"}]))
    monkeypatch.setattr(ai_reasoner, "get_user_calcs", AsyncMock(return_value=[{"slug": "bmi"}]))
    monkeypatch.setattr(ai_reasoner, "get_reco", AsyncMock(return_value=reco_items))

    text = await ai_reasoner.build_ai_plan(42)

    assert "## Твой персональный план на 7 дней" in text
    assert text.count("### День") == 7
    assert "## Почему именно так" in text
    assert "## Товары из плана" in text
    assert "utm-category:" in text


@pytest.mark.asyncio
async def test_ai_plan_prompt_structure_en(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = {"lang": "en", "allergies": []}
    reco_items = [
        {
            "id": "omega-3",
            "title": "NASH Omega-3",
            "utm_category": "focus",
            "why": "Support for focus",
            "tags": ["focus"],
        }
    ]

    monkeypatch.setattr(ai_reasoner, "get_user_profile", AsyncMock(return_value=profile))
    monkeypatch.setattr(ai_reasoner, "get_user_quiz_results", AsyncMock(return_value=[]))
    monkeypatch.setattr(ai_reasoner, "get_user_calcs", AsyncMock(return_value=[]))
    monkeypatch.setattr(ai_reasoner, "get_reco", AsyncMock(return_value=reco_items))

    text = await ai_reasoner.build_ai_plan(99)

    assert "## Your personal 7-day plan" in text
    assert text.count("### Day") == 7
    assert "## Why it looks this way" in text
    assert "## Products in the plan" in text
