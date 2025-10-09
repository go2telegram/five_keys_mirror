import datetime as dt
from zoneinfo import ZoneInfo

from app.services import retention_logic, retention_messages


def test_should_send_tip_first_time():
    tz = ZoneInfo("UTC")
    now = dt.datetime(2024, 1, 1, 10, 0, tzinfo=tz)
    send_time = dt.time(10, 0)
    assert retention_logic.should_send_tip(now, send_time, None)


def test_should_not_send_before_time():
    tz = ZoneInfo("UTC")
    now = dt.datetime(2024, 1, 1, 9, 0, tzinfo=tz)
    send_time = dt.time(10, 0)
    assert not retention_logic.should_send_tip(now, send_time, None)


def test_should_send_once_per_day():
    tz = ZoneInfo("UTC")
    now = dt.datetime(2024, 1, 2, 10, 0, tzinfo=tz)
    send_time = dt.time(9, 0)
    same_day = dt.datetime(2024, 1, 2, 8, 0, tzinfo=tz)
    assert not retention_logic.should_send_tip(now, send_time, same_day)
    previous_day = dt.datetime(2024, 1, 1, 12, 0, tzinfo=tz)
    assert retention_logic.should_send_tip(now, send_time, previous_day)


def test_water_goal_from_weight():
    assert retention_logic.water_goal_from_weight(70) == 2100
    assert retention_logic.water_goal_from_weight(None) == 2000


def test_water_reminders_from_weight():
    assert retention_logic.water_reminders_from_weight(60) == 3
    assert retention_logic.water_reminders_from_weight(80) == 4


def test_format_tip_message():
    text = retention_messages.format_tip_message("  Пей воду  ")
    assert text.startswith("💡 ")
    assert "Пей воду" in text


def test_sleep_journey_message_mentions_tracker():
    text = retention_messages.format_sleep_journey_message()
    assert "трекер" in text.lower()


def test_tip_click_ack_message():
    text = retention_messages.format_tip_click_ack()
    assert "спасибо" in text.lower()
