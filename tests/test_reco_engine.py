from __future__ import annotations

from app.reco import RecommendationEngine, RecommendationRequest


def _ids(result) -> list[str]:
    return [card.product_id for card in result.cards]


def test_recommend_energy_profile_returns_top_products() -> None:
    engine = RecommendationEngine()
    request = RecommendationRequest(
        tags=[
            "energy",
            "mitochondria",
            "tonus",
            "recovery",
            "focus",
            "metabolic_reset",
        ],
        audience=["athlete"],
        include_explain=True,
    )
    result = engine.recommend(request)

    assert _ids(result)[:3] == [
        "t8-extra-90",
        "t8-beet-shot",
        "mito-base",
    ]
    assert result.explain is not None
    assert "quiz.energy" in set(result.explain.get("sources", []))


def test_recommend_sleep_flow_uses_audience_boost() -> None:
    engine = RecommendationEngine()
    request = RecommendationRequest(
        tags=[
            "sleep_support",
            "calm_evening",
            "stress_balance",
            "mood",
            "adaptogens",
        ],
        audience=["female"],
    )
    result = engine.recommend(request)
    ids = _ids(result)

    assert ids[:3] == ["manana", "nash-magnii-b6", "t8-feel"]
    mag_card = next(card for card in result.cards if card.product_id == "nash-magnii-b6")
    assert mag_card.audience_boost > 1.0


def test_allergen_exclusion_filters_out_omega_products() -> None:
    engine = RecommendationEngine()
    request = RecommendationRequest(
        tags=["stress_balance", "adaptogens", "mood", "anti_inflammatory", "sleep_focus"],
        allergies=["fish"],
        include_explain=True,
    )
    result = engine.recommend(request)

    assert all("omega" not in pid for pid in _ids(result))
    excluded = {item["product_id"]: item["reason"] for item in result.excluded}
    assert excluded.get("nash-omega-3") == "allergen"
    assert excluded.get("nash-omega-3-150") == "allergen"
