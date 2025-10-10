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

    captured: dict[str, str] = {}

    async def fake_ai_generate(prompt: str, sys: str):  # noqa: ANN001
        captured["prompt"] = prompt
        captured["sys"] = sys
        return "AI RESPONSE RU"

    monkeypatch.setattr(ai_reasoner, "ai_generate", fake_ai_generate)

    text = await ai_reasoner.build_ai_plan(42)

    assert text == "AI RESPONSE RU"
    prompt = captured["prompt"]
    assert "## Твой персональный план на 7 дней" in prompt
    for day in range(1, 8):
        assert f"### День {day}" in prompt
    assert "## Почему именно так" in prompt
    assert "## Товары из плана" in prompt
    assert "energy" in prompt  # tags serialized to JSON
    assert captured["sys"] == ai_reasoner._AI_PLAN_SYSTEM_PROMPT


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

    captured: dict[str, str] = {}

    async def fake_ai_generate(prompt: str, sys: str):  # noqa: ANN001
        captured["prompt"] = prompt
        captured["sys"] = sys
        return "AI RESPONSE EN"

    monkeypatch.setattr(ai_reasoner, "ai_generate", fake_ai_generate)

    text = await ai_reasoner.build_ai_plan(101)

    assert text == "AI RESPONSE EN"
    prompt = captured["prompt"]
    assert "## Your personal 7-day plan" in prompt
    for day in range(1, 8):
        assert f"### Day {day}" in prompt
    assert "## Why this approach" in prompt
    assert "## Products from the plan" in prompt
    assert "focus" in prompt
    assert captured["sys"] == ai_reasoner._AI_PLAN_SYSTEM_PROMPT
