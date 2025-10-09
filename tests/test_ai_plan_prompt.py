from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.reco import ai_reasoner


@pytest.mark.asyncio
async def test_build_ai_plan_prompt_contains_structure_ru(monkeypatch):
    monkeypatch.setattr(ai_reasoner, "get_user_profile", AsyncMock(return_value={"lang": "ru", "allergies": ["citrus"]}))
    monkeypatch.setattr(ai_reasoner, "get_user_quiz_results", AsyncMock(return_value=[{"name": "sleep"}]))
    monkeypatch.setattr(ai_reasoner, "get_user_calcs", AsyncMock(return_value=[{"name": "msd"}]))
    monkeypatch.setattr(
        ai_reasoner,
        "get_reco",
        AsyncMock(
            return_value=[
                {
                    "id": "T8_EXTRA",
                    "title": "T8 EXTRA",
                    "utm_category": "energy",
                    "tags": ["energy", "mitochondria"],
                    "why": "Повышение энергии",
                }
            ]
        ),
    )
    monkeypatch.setattr(ai_reasoner, "build_order_link", lambda *_args, **_kwargs: "https://example.com/order")

    text = await ai_reasoner.build_ai_plan(42)

    assert "## Твой персональный план на 7 дней" in text
    for day in range(1, 8):
        assert f"### День {day}" in text
    assert "## Почему именно так" in text
    assert "## Товары из плана" in text
    assert "energy" in text  # tags serialized to JSON


@pytest.mark.asyncio
async def test_build_ai_plan_prompt_contains_structure_en(monkeypatch):
    monkeypatch.setattr(ai_reasoner, "get_user_profile", AsyncMock(return_value={"lang": "en"}))
    monkeypatch.setattr(ai_reasoner, "get_user_quiz_results", AsyncMock(return_value=[]))
    monkeypatch.setattr(ai_reasoner, "get_user_calcs", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        ai_reasoner,
        "get_reco",
        AsyncMock(
            return_value=[
                {
                    "id": "OMEGA3",
                    "title": "Omega 3",
                    "utm_category": "focus",
                    "tags": ["focus", "omega3"],
                    "why": "Support focus",
                }
            ]
        ),
    )
    monkeypatch.setattr(ai_reasoner, "build_order_link", lambda *_args, **_kwargs: "https://example.com/en")

    text = await ai_reasoner.build_ai_plan(101)

    assert "## Your personal 7-day plan" in text
    for day in range(1, 8):
        assert f"### Day {day}" in text
    assert "## Why this approach" in text
    assert "## Products from the plan" in text
    assert "focus" in text
