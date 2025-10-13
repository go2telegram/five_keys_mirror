import pytest

pytest.importorskip("yaml")

from app.quiz import list_quizzes, load_quiz


def test_gut_quiz_definition():
    quizzes = list_quizzes()
    gut_quiz = next(q for q in quizzes if q.name == "gut")

    assert gut_quiz.title == "ЖКТ/Дефициты"

    definition = load_quiz("gut")

    assert definition.cover == "gut/cover.png"
    assert len(definition.questions) == 5
    assert all(
        question.image and question.image.startswith("gut/") for question in definition.questions
    )

    tags = {tag for threshold in definition.thresholds for tag in threshold.tags}
    assert tags == {"gut", "digest_support", "fiber", "probiotic", "collagen", "vitamins"}
