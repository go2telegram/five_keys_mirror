from __future__ import annotations

from app.content import overrides as overrides_module
from app.content.overrides.quiz_merge import apply_quiz_override
from app.quiz.engine import load_quiz


def test_quiz_overlay_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(overrides_module, "QUIZ_OVERRIDES_ROOT", tmp_path)
    overrides_module.ensure_directories()
    base = {
        "title": "Test",
        "questions": [
            {
                "id": "q1",
                "text": "Base",
                "options": [
                    {"key": "a", "text": "A", "score": 0, "tags": []},
                    {"key": "b", "text": "B", "score": 1, "tags": []},
                ],
            }
        ],
        "result": {"thresholds": [{"min": 0, "max": 1, "label": "ok", "advice": "x", "tags": []}]},
    }
    override = {
        "questions": [
            {
                "id": "q1",
                "text": "Changed",
                "options": [
                    {"key": "b", "text": "Better", "score": 2},
                    {"key": "c", "text": "New", "score": 3, "tags": ["n"]},
                ],
            }
        ],
    }
    merged = apply_quiz_override(base, override)
    question = merged["questions"][0]
    assert question["text"] == "Changed"
    assert {opt["key"] for opt in question["options"]} == {"a", "b", "c"}
    opt_b = next(opt for opt in question["options"] if opt["key"] == "b")
    assert opt_b["score"] == 2


def test_quiz_load_with_override(tmp_path, monkeypatch):
    monkeypatch.setattr(overrides_module, "QUIZ_OVERRIDES_ROOT", tmp_path)
    overrides_module.ensure_directories()
    overlay = {
        "questions": [
            {
                "id": "q1",
                "text": "Сколько спишь?",
            }
        ]
    }
    overrides_module.save_quiz_override("sleep", overlay)
    load_quiz.cache_clear()
    quiz = load_quiz("sleep")
    assert quiz.questions[0].text == "Сколько спишь?"
