from __future__ import annotations

import datetime as dt

import pytest

from app.repo import tracker as tracker_repo
from app.scheduler import jobs as habit_jobs


class _DummySession:
    def __init__(self, collector: list[_DummySession]):
        self.committed = False
        collector.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        self.committed = True


class _DummyBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, user_id: int, text: str):
        self.sent.append((user_id, text))


@pytest.mark.asyncio
async def test_send_habit_reminders(monkeypatch):
    sessions: list[_DummySession] = []

    def _session_scope_stub():
        return _DummySession(sessions)

    profile = tracker_repo.ReminderProfile(
        user_id=42,
        timezone="Europe/Moscow",
        times=["09:00", "12:00"],
        last_sent={},
    )
    sent_updates: list[tuple[int, str, str]] = []

    async def _list_profiles(_session):
        return [profile]

    async def _mark_sent(_session, updates):
        sent_updates.extend(updates)
        for user_id, slot, date_iso in updates:
            if profile.user_id == user_id:
                profile.last_sent[slot] = date_iso

    monkeypatch.setattr(habit_jobs, "session_scope", _session_scope_stub)
    monkeypatch.setattr(habit_jobs.tracker_repo, "list_reminder_profiles", _list_profiles)
    monkeypatch.setattr(habit_jobs.tracker_repo, "mark_reminders_sent", _mark_sent)

    bot = _DummyBot()
    now = dt.datetime(2024, 1, 10, 6, 0, tzinfo=dt.timezone.utc)  # 09:00 MSK

    await habit_jobs.send_habit_reminders(bot, now)

    assert bot.sent
    assert sent_updates == [(42, "09:00", "2024-01-10")]
    assert sessions and sessions[-1].committed

    # second run within window should not duplicate
    await habit_jobs.send_habit_reminders(bot, now)
    assert len(bot.sent) == 1
