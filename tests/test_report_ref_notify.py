from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("aiosqlite")

from app.handlers import notify, referral, report


def _flatten(markup):
    return [btn for row in markup.inline_keyboard for btn in row]


def test_compose_pdf_returns_bytes():
    plan = {
        "title": "План восстановления",
        "context_name": "Калькулятор MSD",
        "level": "норма",
        "actions": ["Шаг 1", "Шаг 2"],
        "lines": ["<b>— Blend</b>: поддержка", "  · Свойство"],
        "notes": "Сфокусируйтесь на сне.",
        "intake": [["Утро", "Blend", "20 мл"]],
        "order_url": "https://example.com/order",
    }
    pdf_bytes = report._compose_pdf(plan)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 500


@pytest.mark.asyncio
async def test_ref_link_and_keyboard_contains_navigation():
    class DummyBot:
        async def get_me(self):
            return SimpleNamespace(username="demo_bot")

    link = await referral._ref_link(DummyBot(), 123)
    assert link == "https://t.me/demo_bot?start=ref_123"

    markup = referral._kb_ref(link)
    callbacks = [getattr(btn, "callback_data", None) for btn in _flatten(markup) if btn.callback_data]
    urls = [btn.url for btn in _flatten(markup) if btn.url]
    assert "ref:menu" in callbacks
    assert "home:main" in callbacks
    assert link in urls


@pytest.mark.asyncio
async def test_notify_toggle_flow(monkeypatch):
    events: dict[str, list[SimpleNamespace]] = {}

    @asynccontextmanager
    async def fake_scope():
        yield object()

    async def fake_log(session, user_id: int, name: str, meta: dict) -> None:
        entries = events.setdefault(name, [])
        entries.append(SimpleNamespace(ts=datetime.now(timezone.utc), user_id=user_id))

    async def fake_last_by(session, user_id: int, name: str):
        items = [item for item in events.get(name, []) if item.user_id == user_id]
        return items[-1] if items else None

    monkeypatch.setattr(notify, "session_scope", fake_scope)
    monkeypatch.setattr(notify.events_repo, "log", fake_log)
    monkeypatch.setattr(notify.events_repo, "last_by", fake_last_by)

    await notify._set_event(42, "notify_on")
    assert await notify._is_enabled(42) is True

    await notify._set_event(42, "notify_off")
    assert await notify._is_enabled(42) is False

    markup = notify._status_keyboard(enabled=False)
    callbacks = [getattr(btn, "callback_data", None) for btn in _flatten(markup) if btn.callback_data]
    assert "notify:on" in callbacks
    assert "home:main" in callbacks
