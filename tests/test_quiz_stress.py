import pytest

pytest.importorskip("yaml")

from app.quiz.engine import load_quiz


def test_stress_quiz_definition():
    quiz = load_quiz("stress")

    assert quiz.title == "Стресс"
    assert quiz.cover == "stress/cover.png"
    assert 5 <= len(quiz.questions) <= 7

    collected_tags = {
        tag for question in quiz.questions for option in question.options for tag in option.tags
    }
    expected_tags = {"stress_support", "theanine", "magnesium", "adaptogens", "reduce_caffeine"}
    assert expected_tags.issubset(collected_tags)

    threshold_tags = {tag for threshold in quiz.thresholds for tag in threshold.tags}
    assert expected_tags - {"stress_support"} <= threshold_tags
