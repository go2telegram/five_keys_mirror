"""Habit tracker commands and reminder configuration."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.session import compat_session, session_scope
from app.repo import tracker as tracker_repo
from app.repo import users as users_repo
from app.services.habit_tracker import (
    HabitAggregator,
    DailyReport,
    WeeklyReport,
    day_bounds,
    is_valid_timezone,
    normalise_times,
    resolve_timezone,
)
from app.storage import commit_safely

router = Router(name="habit_tracker")
LOG = logging.getLogger(__name__)

_HABIT_ORDER = ("water", "sleep", "stress", "steps")
_HABIT_LABELS = {
    "water": "Вода",
    "sleep": "Сон",
    "stress": "Стресс",
    "steps": "Шаги",
}
_HABIT_UNITS = {
    "water": "мл",
    "sleep": "ч",
    "stress": "баллов",
    "steps": "шагов",
}
_HABIT_ICONS = {
    "water": "💧",
    "sleep": "😴",
    "stress": "🧘",
    "steps": "👣",
}
_PER_DAY_AVG = {"water", "sleep", "steps"}

_MIN_VALUES = {"water": 10, "sleep": 1, "stress": 0, "steps": 10}
_MAX_VALUES = {"water": 10000, "sleep": 24, "stress": 10, "steps": 150000}


@dataclass(slots=True)
class TrackerSnapshot:
    tz: str
    local_today: dt.date
    daily: DailyReport
    weekly: WeeklyReport
    streaks: dict[str, int]


def _format_entry(kind: str, value: int) -> str:
    unit = _HABIT_UNITS.get(kind)
    if unit:
        return f"{value} {unit}"
    return str(value)


def _format_total(kind: str, value: int) -> str:
    if value <= 0:
        return "—"
    return _format_entry(kind, value)


def _format_weekly_value(kind: str, total: int, avg: float) -> str:
    if total <= 0:
        return "—"
    base = _format_entry(kind, total)
    if avg <= 0:
        return base
    avg_value = round(avg, 1)
    if abs(avg_value - round(avg_value)) < 0.1:
        avg_value = round(avg_value)
    unit = _HABIT_UNITS.get(kind)
    if kind in _PER_DAY_AVG:
        suffix = f"{unit}/день" if unit else "/день"
    else:
        suffix = unit or ""
    suffix = suffix.strip()
    avg_display = f"ср. {avg_value} {suffix}".strip()
    return f"{base} ({avg_display})"


def _format_streak(value: int) -> str:
    if value <= 0:
        return "—"
    if value == 1:
        return "1 день"
    if 2 <= value <= 4:
        return f"{value} дня"
    return f"{value} дней"


def _water_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💧 +250 мл", callback_data="track:water:250")
    kb.button(text="💧 +500 мл", callback_data="track:water:500")
    return kb.as_markup()


def _parse_amount(text: str | None, *, default: int | None = None) -> tuple[int | None, str | None]:
    if not text:
        if default is None:
            return None, "Укажи число, например /track_water 250"
        return default, None
    parts = text.split(maxsplit=1)
    if len(parts) == 1:
        if default is None:
            return None, "Укажи число, например /track_sleep 7"
        return default, None
    raw = parts[1].strip().replace(",", ".")
    if not raw:
        if default is None:
            return None, "Укажи число после команды"
        return default, None
    if raw.startswith("+"):
        raw = raw[1:]
    try:
        value = int(float(raw))
    except ValueError:
        return None, "Не понял число. Пример: /track_water 250"
    return value, None


def _validate_amount(kind: str, value: int) -> str | None:
    minimum = _MIN_VALUES.get(kind, 0)
    maximum = _MAX_VALUES.get(kind, 1_000_000)
    if value < minimum:
        return f"Слишком мало для {kind}: минимум {minimum}"
    if value > maximum:
        return f"Слишком много для {kind}: максимум {maximum}"
    if kind == "stress" and not (0 <= value <= 10):
        return "Стресс измеряем по шкале 0–10"
    return None


async def _snapshot(
    user_id: int,
    username: str | None,
    *,
    new_event: tuple[str, int] | None = None,
) -> TrackerSnapshot:
    async with compat_session(session_scope) as session:
        user = await users_repo.get_or_create_user(session, user_id, username)
        tracker_repo.ensure_profile_defaults(user)
        reference_ts = dt.datetime.now(dt.timezone.utc)
        if new_event is not None:
            kind, value = new_event
            event = await tracker_repo.add_event(session, user.id, kind, value)
            reference_ts = event.ts
        tz = resolve_timezone(user.timezone)
        local_reference = reference_ts.astimezone(tz)
        today = local_reference.date()
        _, end_utc = day_bounds(today, tz)
        events = await tracker_repo.fetch_events(session, user.id, until=end_utc)
        aggregator = HabitAggregator(events, tz)
        daily = aggregator.daily_report(today)
        weekly = aggregator.weekly_report(today)
        streaks = aggregator.streaks(today, kinds=_HABIT_ORDER)
        await commit_safely(session)
    tz_name = getattr(tz, "key", str(tz))
    return TrackerSnapshot(
        tz=tz_name,
        local_today=today,
        daily=daily,
        weekly=weekly,
        streaks=streaks,
    )


def _format_daily_section(daily: DailyReport) -> list[str]:
    lines: list[str] = []
    for kind in _HABIT_ORDER:
        label = _HABIT_LABELS[kind]
        value = _format_total(kind, int(daily.totals.get(kind, 0)))
        lines.append(f"• {label}: {value}")
    return lines


def _format_weekly_section(weekly: WeeklyReport) -> list[str]:
    lines: list[str] = []
    for kind in _HABIT_ORDER:
        label = _HABIT_LABELS[kind]
        total = int(weekly.totals.get(kind, 0))
        avg = float(weekly.averages.get(kind, 0.0))
        value = _format_weekly_value(kind, total, avg)
        lines.append(f"• {label}: {value}")
    return lines


def _format_streaks_section(streaks: dict[str, int]) -> list[str]:
    lines: list[str] = []
    for kind in _HABIT_ORDER:
        label = _HABIT_LABELS[kind]
        value = _format_streak(int(streaks.get(kind, 0)))
        lines.append(f"• {label}: {value}")
    return lines


def _format_tracking_message(kind: str, delta: int, snapshot: TrackerSnapshot) -> str:
    label = _HABIT_LABELS.get(kind, kind)
    icon = _HABIT_ICONS.get(kind, "✅")
    delta_str = _format_entry(kind, delta)
    if kind in {"water", "steps"} and delta > 0:
        delta_str = f"+{delta_str}"
    header = f"{icon} {label}: {delta_str}"
    today_str = snapshot.local_today.strftime("%d.%m")
    lines = [
        header,
        "",
        f"📅 Сегодня ({today_str}):",
    ]
    lines.extend(_format_daily_section(snapshot.daily))
    lines.append("")
    lines.append("🔥 Серии:")
    lines.extend(_format_streaks_section(snapshot.streaks))
    lines.append("")
    lines.append("📈 За 7 дней:")
    lines.extend(_format_weekly_section(snapshot.weekly))
    lines.append("")
    lines.append("→ /today — прогресс, /streaks — серии")
    return "\n".join(lines)


def _format_today_message(snapshot: TrackerSnapshot) -> str:
    today_str = snapshot.local_today.strftime("%d.%m")
    lines = [
        f"📅 Сегодня ({today_str}):",
    ]
    lines.extend(_format_daily_section(snapshot.daily))
    lines.append("")
    lines.append("🔥 Серии:")
    lines.extend(_format_streaks_section(snapshot.streaks))
    lines.append("")
    lines.append("📈 За 7 дней:")
    lines.extend(_format_weekly_section(snapshot.weekly))
    lines.append("")
    lines.append("Команды: /track_water, /track_sleep, /track_stress")
    return "\n".join(lines)


def _format_streaks_message(snapshot: TrackerSnapshot) -> str:
    today_str = snapshot.local_today.strftime("%d.%m")
    lines = [
        f"🔥 Серии на {today_str}:",
    ]
    lines.extend(_format_streaks_section(snapshot.streaks))
    lines.append("")
    lines.append("📈 За 7 дней:")
    lines.extend(_format_weekly_section(snapshot.weekly))
    lines.append("")
    lines.append("/today — дневной прогресс")
    return "\n".join(lines)


async def _send_tracking_response(message: Message, kind: str, value: int, *, default_keyboard: bool = False) -> None:
    snapshot = await _snapshot(message.from_user.id, message.from_user.username, new_event=(kind, value))
    text = _format_tracking_message(kind, value, snapshot)
    reply_markup = _water_keyboard() if default_keyboard else None
    await message.answer(text, reply_markup=reply_markup)


@router.message(Command("track_water"))
async def track_water_cmd(message: Message) -> None:
    value, error = _parse_amount(message.text, default=250)
    if value is None:
        await message.answer(error or "Укажи объём воды в мл, например /track_water 250")
        return
    error = _validate_amount("water", value)
    if error:
        await message.answer(error)
        return
    await _send_tracking_response(message, "water", value, default_keyboard=True)


@router.message(Command("track_sleep"))
async def track_sleep_cmd(message: Message) -> None:
    value, error = _parse_amount(message.text)
    if value is None:
        await message.answer(error or "Формат: /track_sleep 7")
        return
    error = _validate_amount("sleep", value)
    if error:
        await message.answer(error)
        return
    await _send_tracking_response(message, "sleep", value)


@router.message(Command("track_stress"))
async def track_stress_cmd(message: Message) -> None:
    value, error = _parse_amount(message.text)
    if value is None:
        await message.answer(error or "Формат: /track_stress 3 (0–10)")
        return
    error = _validate_amount("stress", value)
    if error:
        await message.answer(error)
        return
    await _send_tracking_response(message, "stress", value)


@router.message(Command("today"))
async def today_cmd(message: Message) -> None:
    snapshot = await _snapshot(message.from_user.id, message.from_user.username)
    await message.answer(_format_today_message(snapshot))


@router.message(Command("streaks"))
async def streaks_cmd(message: Message) -> None:
    snapshot = await _snapshot(message.from_user.id, message.from_user.username)
    await message.answer(_format_streaks_message(snapshot))


async def _reminder_status_text(user_id: int, username: str | None) -> str:
    async with compat_session(session_scope) as session:
        user = await users_repo.get_or_create_user(session, user_id, username)
        tracker_repo.ensure_profile_defaults(user)
        tz_name = user.timezone or "Не указан"
        times = user.habit_reminders_times or tracker_repo.DEFAULT_REMINDER_TIMES
        status = "включены" if user.habit_reminders_enabled else "выключены"
        times_text = ", ".join(times) if times else "—"
    return (
        "🔔 Напоминания {status}.\n"
        "Часовой пояс: {tz}\n"
        "Расписание: {times}\n"
        "Настроить: /remind_config"
    ).format(status=status, tz=tz_name, times=times_text)


@router.message(Command("remind"))
async def remind_cmd(message: Message) -> None:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) == 1:
        await message.answer(await _reminder_status_text(message.from_user.id, message.from_user.username))
        return
    action = parts[1].strip().lower()
    if action not in {"on", "off"}:
        await message.answer("Используй /remind on или /remind off. Настройки: /remind_config")
        return
    enabled = action == "on"
    async with compat_session(session_scope) as session:
        user = await users_repo.get_or_create_user(session, message.from_user.id, message.from_user.username)
        tracker_repo.ensure_profile_defaults(user)
        if enabled and not user.timezone:
            user.timezone = getattr(resolve_timezone(None), "key", "UTC")
        await tracker_repo.set_reminders_enabled(session, user, enabled)
        times = user.habit_reminders_times or tracker_repo.DEFAULT_REMINDER_TIMES
        tz_value = user.timezone or "UTC"
        await commit_safely(session)
    if enabled:
        lines = [
            "🔔 Напоминания включены.",
            f"Часовой пояс: {tz_value}",
            f"Расписание: {', '.join(times)}",
            "Настроить: /remind_config",
        ]
    else:
        lines = [
            "🔕 Напоминания выключены.",
            "Включить снова: /remind on",
        ]
    await message.answer("\n".join(lines))


def _parse_config_payload(payload: str) -> tuple[str | None, list[str] | None]:
    tokens = payload.split()
    tz_value: str | None = None
    times_items: list[str] | None = None
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if token.startswith("tz="):
            tz_value = token[3:]
        elif token == "tz" and idx + 1 < len(tokens):
            idx += 1
            tz_value = tokens[idx]
        elif token.startswith("times="):
            raw = token[6:]
            parts = [part for part in raw.split(",") if part]
            times_items = parts
        elif token == "times":
            idx += 1
            collected: list[str] = []
            while idx < len(tokens) and "=" not in tokens[idx]:
                collected.extend(part for part in tokens[idx].split(",") if part)
                idx += 1
            times_items = collected
            continue
        idx += 1
    return tz_value, times_items


@router.message(Command("remind_config"))
async def remind_config_cmd(message: Message) -> None:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) == 1:
        await message.answer(await _reminder_status_text(message.from_user.id, message.from_user.username))
        return
    tz_value, times_items = _parse_config_payload(parts[1])
    updates: list[str] = []
    async with compat_session(session_scope) as session:
        user = await users_repo.get_or_create_user(session, message.from_user.id, message.from_user.username)
        tracker_repo.ensure_profile_defaults(user)
        if tz_value:
            if not is_valid_timezone(tz_value):
                await message.answer("Не удалось распознать часовой пояс")
                return
            tz_obj = resolve_timezone(tz_value)
            tz_key = getattr(tz_obj, "key", tz_value)
            user.timezone = tz_key
            updates.append(f"Часовой пояс: {tz_key}")
        if times_items is not None:
            try:
                times = normalise_times(times_items)
            except ValueError as exc:
                await message.answer(str(exc))
                return
            if not times:
                await message.answer("Укажи хотя бы одно время в формате ЧЧ:ММ")
                return
            await tracker_repo.update_reminder_times(session, user, times)
            updates.append(f"Расписание: {', '.join(times)}")
        await commit_safely(session)
        tz_display = user.timezone or "Не указан"
        times_display = ", ".join(user.habit_reminders_times or [])
    if not updates:
        await message.answer("Не нашёл, что обновить. Формат: /remind_config tz=Europe/Moscow times=09:00,13:00")
        return
    lines = ["⚙️ Обновил настройки:"] + updates
    lines.append("")
    lines.append(f"Текущий пояс: {tz_display}")
    lines.append(f"Текущее расписание: {times_display or '—'}")
    await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("track:water:"))
async def track_water_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        await callback.answer("Нет сообщения", show_alert=True)
        return
    parts = callback.data.split(":") if callback.data else []
    amount = 0
    try:
        amount = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer("Не понял", show_alert=True)
        return
    error = _validate_amount("water", amount)
    if error:
        await callback.answer(error, show_alert=True)
        return
    snapshot = await _snapshot(callback.from_user.id, callback.from_user.username, new_event=("water", amount))
    text = _format_tracking_message("water", amount, snapshot)
    await callback.answer("Добавлено")
    await callback.message.answer(text, reply_markup=_water_keyboard())
