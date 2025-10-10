"""Unit tests for the catalog link checker utility."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from tools import catalog_linkcheck as linkcheck


def test_extract_targets_groups_duplicates() -> None:
    payload = {
        "products": [
            {
                "id": "alpha",
                "order": {"velavie_link": "https://example.test/order-alpha"},
                "image": "https://cdn.example.test/alpha.jpg",
                "images": [
                    "https://cdn.example.test/alpha.jpg",
                    "https://cdn.example.test/shared.jpg",
                ],
            },
            {
                "id": "beta",
                "order": {"velavie_link": "https://example.test/order-beta"},
                "images": [
                    "https://cdn.example.test/shared.jpg",
                ],
            },
        ]
    }

    targets = linkcheck.extract_targets(payload)
    assert {target.url for target in targets} == {
        "https://example.test/order-alpha",
        "https://example.test/order-beta",
        "https://cdn.example.test/alpha.jpg",
        "https://cdn.example.test/shared.jpg",
    }

    shared = next(target for target in targets if target.url.endswith("shared.jpg"))
    assert shared.contexts == ["alpha:image:1", "beta:image:0"]


def test_append_log_writes_summary_and_problems(tmp_path) -> None:
    summary = {
        "ts": "2024-01-01T00:00:00+00:00",
        "finished": "2024-01-01T00:00:05+00:00",
        "status": "warn",
        "total": 2,
        "broken": 1,
        "duration": 5.0,
        "log": "logs/catalog_linkcheck.log",
    }
    problem = linkcheck.LinkCheckResult(
        url="https://broken.example.test", status=404, detail="not found", contexts=["alpha:order"]
    )

    log_path = tmp_path / "catalog_linkcheck.log"
    linkcheck.append_log(summary, [problem], log_path=log_path)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    summary_entry = json.loads(lines[0])
    assert summary_entry["kind"] == "summary"
    assert summary_entry["status"] == "warn"

    problem_entry = json.loads(lines[1])
    assert problem_entry["kind"] == "problem"
    assert problem_entry["url"] == "https://broken.example.test"
    assert problem_entry["contexts"] == ["alpha:order"]


@pytest.mark.asyncio
async def test_run_checks_uses_custom_requester() -> None:
    targets = [
        linkcheck.LinkTarget(url="https://ok.example", contexts=["alpha:order"]),
        linkcheck.LinkTarget(url="https://bad.example", contexts=["beta:image:0"]),
    ]

    responses = {
        "https://ok.example": (200, None),
        "https://bad.example": (404, "not found"),
    }

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def requester(session, target):  # type: ignore[no-untyped-def]
        return responses[target.url]

    def session_factory() -> DummySession:
        return DummySession()

    results = await linkcheck.run_checks(
        targets,
        session_factory=session_factory,  # type: ignore[arg-type]
        requester=requester,
        concurrency=1,
    )

    assert len(results) == 2
    statuses = {result.url: result.status for result in results}
    assert statuses == {"https://ok.example": 200, "https://bad.example": 404}
    assert not results[0].detail
    assert results[1].detail == "not found"


def test_summarise_marks_problems() -> None:
    started = datetime.now(timezone.utc)
    finished = started
    results = [
        linkcheck.LinkCheckResult(
            url="https://ok.example",
            status=200,
            detail=None,
            contexts=["alpha:order"],
        ),
        linkcheck.LinkCheckResult(
            url="https://bad.example",
            status=500,
            detail="server error",
            contexts=["beta:image:0"],
        ),
    ]

    summary, problems = linkcheck.summarise(results, started_at=started, finished_at=finished)
    assert summary["status"] == "warn"
    assert summary["broken"] == 1
    assert problems and problems[0].url == "https://bad.example"
