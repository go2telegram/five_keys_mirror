from tools.audit_sections.check_quizzes import validate_quiz_payload


def test_quiz_validator_requires_minimum_questions():
    payload = {
        "questions": [{"id": "q1"}, {"id": "q2"}, {"id": "q3"}, {"id": "q4"}],
        "result": {"thresholds": [{"min": 0, "max": 10}]},
    }
    issues = validate_quiz_payload("demo", payload, image_mode="remote")
    assert any(issue.level == "error" for issue in issues)


def test_quiz_validator_requires_thresholds():
    payload = {
        "questions": [{"id": "q1"}] * 5,
        "result": {},
    }
    issues = validate_quiz_payload("demo", payload, image_mode="remote")
    assert any("thresholds" in issue.message for issue in issues)


def test_quiz_validator_rejects_absolute_images():
    payload = {
        "questions": [{"id": "q1", "image": "/tmp/image.png"}] * 5,
        "result": {"thresholds": [{"min": 0, "max": 10}]},
    }
    issues = validate_quiz_payload("demo", payload, image_mode="remote")
    assert any("Абсолютный путь" in issue.message for issue in issues)
