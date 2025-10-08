import pytest

pytest.importorskip("yaml")

from app.quiz.engine import load_quiz


def test_immunity_quiz_definition_contains_required_tags():
    definition = load_quiz("immunity")

    assert definition.title == "Иммунитет"
    assert len(definition.questions) >= 5

    collected_tags = {tag for threshold in definition.thresholds for tag in threshold.tags}
    assert {"immunity", "vitamin_d3", "probiotic", "fiber"}.issubset(collected_tags)
