import asyncio
import json
from pathlib import Path

from tools import check_partner_links


class _DummyResponse:
    def __init__(self, status: int):
        self.status = status
        self.headers: dict[str, str] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: D401 - parity with aiohttp
        return False


class _DummyRequestManager:
    def __init__(self, status: int, detail: str | None):
        self._status = status
        self._detail = detail

    async def __aenter__(self):
        return _DummyResponse(self._status)

    async def __aexit__(self, exc_type, exc, tb):  # noqa: D401 - parity with aiohttp
        return False


class _DummySession:
    def __init__(self, responses: dict[str, tuple[int, str | None]], **_kwargs):
        self._responses = responses

    async def __aenter__(self):  # noqa: D401 - parity with aiohttp
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: D401 - parity with aiohttp
        return False

    def head(self, url: str, *, allow_redirects: bool = True, headers=None):  # noqa: ARG002
        status, detail = self._responses[url]
        return _DummyRequestManager(status, detail)

    def get(self, url: str, *, allow_redirects: bool = True, headers=None):  # noqa: ARG002
        status, detail = self._responses[url]
        return _DummyRequestManager(status, detail)


def _make_session_factory(responses: dict[str, tuple[int, str | None]]):
    def _factory(**kwargs):  # noqa: ANN001 - mimic aiohttp signature
        return _DummySession(responses, **kwargs)

    return _factory


def test_partner_link_check_report_and_diff(tmp_path, monkeypatch):
    links = [
        check_partner_links.PartnerLink(
            url="https://example.com/ok",
            title="OK",
            source="register",
        ),
        check_partner_links.PartnerLink(
            url="https://example.com/redirect",
            title="Redirect",
            source="register",
        ),
        check_partner_links.PartnerLink(
            url="https://example.com/broken",
            title="Broken",
            source="active",
        ),
    ]

    monkeypatch.setattr(check_partner_links, "collect_all_links", lambda: links)

    responses = {
        links[0].url: (200, None),
        links[1].url: (301, None),
        links[2].url: (404, "not found"),
    }

    report_path = tmp_path / "links_head_report.txt"
    diff_path = tmp_path / "links_head_diff.json"

    outcome = asyncio.run(
        check_partner_links.execute(
            report_path=report_path,
            diff_json_path=diff_path,
            session_factory=_make_session_factory(responses),
        )
    )

    assert outcome.total == 3
    assert len(outcome.problems) == 1
    assert outcome.problems[0].link.url == links[2].url
    assert outcome.new_problems and outcome.new_problems[0].link.url == links[2].url

    report_text = report_path.read_text(encoding="utf-8")
    assert "200" in report_text
    assert "301" in report_text
    assert "404" in report_text

    payload = json.loads(diff_path.read_text(encoding="utf-8"))
    assert payload["new"][0]["url"] == links[2].url
    assert payload["new"][0]["status"] == 404


def test_partner_link_check_diff_skips_existing(tmp_path, monkeypatch):
    links = [
        check_partner_links.PartnerLink(
            url="https://example.com/ok",
            title="OK",
            source="register",
        ),
        check_partner_links.PartnerLink(
            url="https://example.com/broken",
            title="Broken",
            source="register",
        ),
    ]

    monkeypatch.setattr(check_partner_links, "collect_all_links", lambda: links)

    baseline_report = tmp_path / "baseline.txt"

    baseline_outcome = asyncio.run(
        check_partner_links.execute(
            report_path=baseline_report,
            diff_json_path=tmp_path / "baseline_diff.json",
            session_factory=_make_session_factory(
                {
                    links[0].url: (200, None),
                    links[1].url: (404, None),
                }
            ),
        )
    )
    assert baseline_outcome.new_problems and baseline_outcome.new_problems[0].link.url == links[1].url

    second_diff = tmp_path / "second_diff.json"
    outcome = asyncio.run(
        check_partner_links.execute(
            report_path=tmp_path / "second_report.txt",
            previous_report=baseline_report,
            diff_json_path=second_diff,
            session_factory=_make_session_factory(
                {
                    links[0].url: (200, None),
                    links[1].url: (200, None),
                }
            ),
        )
    )

    assert not outcome.new_problems
    assert outcome.resolved == [links[1].url]

    payload = json.loads(second_diff.read_text(encoding="utf-8"))
    assert payload["resolved"] == [links[1].url]
    assert payload["new"] == []
