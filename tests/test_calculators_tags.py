from __future__ import annotations

from reco.engine import DEFAULT_TAG_TTL_SECONDS, DerivedTagStore, derive_calculator_tags


class _Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def now(self) -> float:
        return self.value

    def advance(self, delta: float) -> None:
        self.value += delta


def _store(ttl: int = DEFAULT_TAG_TTL_SECONDS) -> tuple[DerivedTagStore, _Clock]:
    clock = _Clock()
    return DerivedTagStore(ttl_seconds=ttl, now=clock.now), clock


def test_water_calculator_tags_are_persisted_and_expire() -> None:
    store, clock = _store(ttl=10)
    user_id = 101

    tags = derive_calculator_tags(user_id, {"calc": "water", "weight": 68}, store=store)
    assert tags == {"dehydration", "electrolytes"}
    assert store.get(user_id) == {"dehydration", "electrolytes"}

    clock.advance(9)
    assert store.get(user_id) == {"dehydration", "electrolytes"}

    clock.advance(2)
    assert store.get(user_id) == set()


def test_macros_protein_and_sugar_tags() -> None:
    store, _ = _store()
    user_id = 202

    tags = derive_calculator_tags(
        user_id,
        {
            "calc": "macros",
            "weight": 60,
            "protein": 70,  # < 1.5 g/kg → protein_low + collagen
            "carbs": 240,  # > 3.5 g/kg → sugar_free
        },
        store=store,
    )

    assert {"protein_low", "collagen", "sugar_free"}.issubset(tags)
    assert store.get(user_id) == tags


def test_bmi_out_of_range_tags() -> None:
    store, _ = _store()

    high_bmi_tags = derive_calculator_tags(
        303,
        {"calc": "bmi", "bmi": 31.2, "category": "ожирение"},
        store=store,
    )
    assert high_bmi_tags == {"weight_management", "omega3", "sport"}

    normal_bmi_tags = derive_calculator_tags(
        404,
        {"calc": "bmi", "bmi": 22.0, "category": "норма"},
        store=store,
    )
    assert normal_bmi_tags == set()
