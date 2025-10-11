"""Handlers for the interactive Premium center."""

from __future__ import annotations

import datetime as dt
import io
import logging
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

try:  # pragma: no cover - optional dependency fallback
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ModuleNotFoundError:  # pragma: no cover - tests run without matplotlib
    matplotlib = None  # type: ignore
    plt = None  # type: ignore

from app.config import settings
from app.db.session import compat_session, session_scope
from app.keyboards import kb_premium_cta
from app.reco.ai_reasoner import edit_ai_plan
from app.repo import (
    events as events_repo,
    habits as habits_repo,
    profiles as profiles_repo,
    subscriptions as subscriptions_repo,
    users as users_repo,
)
from app.services import premium_metrics
from app.services.plan_storage import archive_plan
from app.services.weekly_ai_plan import PlanPayload, build_ai_plan
from app.storage import commit_safely
from app.utils import safe_edit_text

router = Router(name="premium_center")
log = logging.getLogger("premium-center")

MAIN_MENU_TEXT = "💎 Мой Premium-центр"
PLAN_PLACEHOLDER = "План пока не сформирован. Нажми «Обновить план», чтобы получить рекомендации."

_GOAL_STATE: dict[int, list[str]] = {}

GOAL_OPTIONS: Sequence[tuple[str, str]] = (
    ("energy", "⚡ Энергия"),
    ("sleep", "😴 Сон"),
    ("stress", "🧘 Стресс"),
    ("detox", "🧼 Детокс"),
    ("recovery", "💪 Восстановление"),
)


def _main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Мой план на неделю", callback_data="prem:center:plan")
    builder.button(text="📈 Прогресс и трекер", callback_data="prem:center:progress")
    builder.button(text="🔄 Обновить план", callback_data="prem:center:refresh")
    builder.button(text="🧠 Редактировать цели", callback_data="prem:center:edit_goals")
    builder.button(text="⬅️ Назад", callback_data="home:main")
    builder.adjust(1)
    return builder.as_markup()


def _goal_kb(selected: Iterable[str]) -> InlineKeyboardMarkup:
    selected_set = set(selected)
    builder = InlineKeyboardBuilder()
    for key, title in GOAL_OPTIONS:
        prefix = "✅" if key in selected_set else "▫️"
        builder.button(text=f"{prefix} {title}", callback_data=f"prem:center:goal:{key}")
    builder.button(text="Сохранить", callback_data="prem:center:goal_save")
    builder.button(text="Отмена", callback_data="prem:center:goal_cancel")
    builder.adjust(1)
    return builder.as_markup()


async def _ensure_premium(user_id: int) -> bool:
    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, user_id)
        is_active, _ = await subscriptions_repo.is_active(session, user_id)
        await commit_safely(session)
    return is_active


async def _deny_if_not_premium(message: Message | CallbackQuery) -> bool:
    user = message.from_user if isinstance(message, CallbackQuery) else message.from_user
    user_id = getattr(user, "id", None)
    if user_id is None:
        return True
    if await _ensure_premium(user_id):
        return False
    text = (
        "🔒 Premium-центр доступен только подписчикам MITO Premium.\n"
        "💎 Узнай подробнее и оформи доступ командой /premium."
    )
    if isinstance(message, CallbackQuery):
        await message.answer(text, show_alert=True)
        if message.message:
            await message.message.answer(text, reply_markup=kb_premium_cta())
    else:
        await message.answer(text, reply_markup=kb_premium_cta())
    return True


def _is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    admin_ids: set[int] = set(settings.ADMIN_USER_IDS or [])
    if settings.ADMIN_ID:
        admin_ids.add(int(settings.ADMIN_ID))
    return user_id in admin_ids


async def _save_plan(
    session,
    user_id: int,
    plan: PlanPayload,
    *,
    source: str,
    diff: dict | None = None,
) -> dict:
    plan_json = dict(plan.plan_json or {})
    plan_json.setdefault("summary", plan.text)
    plan_json.setdefault("recommendations", list(plan.recommendations))
    plan_json.setdefault("goals", plan_json.get("goals") or [])
    plan_json["source"] = source
    if diff:
        plan_json["diff"] = diff
    await profiles_repo.save_plan(session, user_id, plan_json)
    try:
        archive_plan(user_id, plan_json)
    except Exception:  # pragma: no cover - best effort
        log.warning("failed to archive plan for user %s", user_id, exc_info=True)
    premium_metrics.record_ai_plan(len(plan.render()))
    return plan_json


def _render_plan(plan_json: dict | None) -> str:
    if not plan_json:
        return PLAN_PLACEHOLDER
    summary = plan_json.get("summary") or plan_json.get("text")
    recs = plan_json.get("recommendations") or []
    if not summary and not recs:
        return PLAN_PLACEHOLDER
    if not summary:
        summary = "План обновлён."
    if not recs:
        return summary
    bullets = "\n".join(f"• {item}" for item in recs)
    return f"{summary}\n\nРекомендации недели:\n{bullets}"


async def _get_plan_text(user_id: int) -> str:
    async with compat_session(session_scope) as session:
        plan_json = await profiles_repo.get_plan(session, user_id)
        if plan_json:
            return _render_plan(plan_json)
        plan = await build_ai_plan({"source": "initial"})
        await _save_plan(session, user_id, plan, source="initial")
        await commit_safely(session)
        return plan.render()


def _store_goal_state(user_id: int, goals: Sequence[str]) -> None:
    _GOAL_STATE[user_id] = list(goals)


def _load_goal_state(user_id: int) -> list[str]:
    return list(_GOAL_STATE.get(user_id, []))


async def _generate_chart(user_id: int) -> BufferedInputFile | None:
    if plt is None:
        log.warning("matplotlib is not available; skipping chart generation")
        return None
    tz = ZoneInfo(settings.TIMEZONE)
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=7)
    async with compat_session(session_scope) as session:
        events = await habits_repo.events_between(session, user_id, start, end, kinds=("water", "sleep", "stress"))
    if not events:
        return None

    date_map: dict[dt.date, dict[str, float]] = {}
    for idx in range(6, 0, -1):
        day = (end - dt.timedelta(days=idx)).astimezone(tz).date()
        date_map[day] = {"water": 0.0, "sleep": 0.0, "stress": 0.0}
    today = end.astimezone(tz).date()
    date_map[today] = {"water": 0.0, "sleep": 0.0, "stress": 0.0}

    for event in events:
        local_day = event.ts.astimezone(tz).date()
        bucket = date_map.get(local_day)
        if bucket is None:
            continue
        bucket[event.kind.value] = bucket.get(event.kind.value, 0.0) + float(event.value)

    ordered_days = list(date_map.keys())
    water = [date_map[label_date]["water"] for label_date in ordered_days]
    sleep = [date_map[label_date]["sleep"] for label_date in ordered_days]
    stress = [date_map[label_date]["stress"] for label_date in ordered_days]
    display_labels = [label.strftime("%d.%m") for label in ordered_days]

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(display_labels, [v / 1000 for v in water], label="Вода (л)", marker="o")
    ax.plot(display_labels, sleep, label="Сон (ч)", marker="o")
    ax.plot(display_labels, stress, label="Стресс (оценка)", marker="o")
    ax.set_ylim(bottom=0)
    ax.set_title("Прогресс за 7 дней")
    ax.grid(True, alpha=0.2)
    ax.legend(loc="upper left")
    fig.autofmt_xdate(rotation=45)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return BufferedInputFile(buf.getvalue(), filename="premium_progress.png")


@router.message(Command("premium_center"))
async def premium_center_command(message: Message) -> None:
    if await _deny_if_not_premium(message):
        return
    await message.answer(MAIN_MENU_TEXT, reply_markup=_main_menu_kb())


@router.callback_query(F.data == "/premium_center")
async def premium_center_entry(c: CallbackQuery) -> None:
    if await _deny_if_not_premium(c):
        return
    if c.message:
        await safe_edit_text(c.message, MAIN_MENU_TEXT, _main_menu_kb())
    await c.answer()


@router.callback_query(F.data == "prem:center:back")
async def premium_center_back(c: CallbackQuery) -> None:
    if await _deny_if_not_premium(c):
        return
    if c.message:
        await safe_edit_text(c.message, MAIN_MENU_TEXT, _main_menu_kb())
    await c.answer()


@router.callback_query(F.data == "prem:center:plan")
async def premium_center_plan(c: CallbackQuery) -> None:
    if await _deny_if_not_premium(c):
        return
    user_id = c.from_user.id
    text = await _get_plan_text(user_id)
    if c.message:
        await safe_edit_text(c.message, text, _main_menu_kb())
    await c.answer()


async def _generate_and_send_plan(
    user_id: int,
    message: Message | CallbackQuery,
    *,
    diff: dict | None,
    source: str,
) -> None:
    async with compat_session(session_scope) as session:
        existing = await profiles_repo.get_plan(session, user_id)
        if diff:
            merged_diff = dict(existing or {})
            merged_diff.update(diff)
            plan = await edit_ai_plan(user_id, merged_diff)
        else:
            profile = {"source": source}
            if existing:
                stored_profile = existing.get("profile") or {}
                for key, value in stored_profile.items():
                    profile.setdefault(key, value)
                if existing.get("goals"):
                    profile["goals"] = existing["goals"]
            plan = await build_ai_plan(profile)
        plan_json = await _save_plan(session, user_id, plan, source=source, diff=diff)
        await events_repo.log(
            session,
            user_id,
            "premium_plan_refresh",
            {"source": source, "goals": plan_json.get("goals", [])},
        )
        await commit_safely(session)
        text = plan.render() if plan.plan_json else _render_plan(plan_json)
    if isinstance(message, CallbackQuery) and message.message:
        await safe_edit_text(message.message, text, _main_menu_kb())
        await message.answer("План обновлён", show_alert=False)
    elif isinstance(message, Message):
        await message.answer(text, reply_markup=_main_menu_kb())


@router.callback_query(F.data == "prem:center:refresh")
async def premium_center_refresh(c: CallbackQuery) -> None:
    if await _deny_if_not_premium(c):
        return
    await _generate_and_send_plan(c.from_user.id, c, diff=None, source="manual")


@router.callback_query(F.data == "prem:center:progress")
async def premium_center_progress(c: CallbackQuery) -> None:
    if await _deny_if_not_premium(c):
        return
    chart = await _generate_chart(c.from_user.id)
    if chart is None:
        await c.answer("Пока нет данных трекера", show_alert=True)
        return
    if c.message:
        await c.message.answer_photo(chart, caption="📈 Прогресс за 7 дней")
    await c.answer()


@router.callback_query(F.data == "prem:center:edit_goals")
async def premium_center_edit_goals(c: CallbackQuery) -> None:
    if await _deny_if_not_premium(c):
        return
    user_id = c.from_user.id
    async with compat_session(session_scope) as session:
        plan_json = await profiles_repo.get_plan(session, user_id)
    goals = list(plan_json.get("goals", [])) if plan_json else []
    _store_goal_state(user_id, goals)
    text = "Выбери цели для обновления плана:" if goals else "Выбери 1-2 цели, чтобы обновить план."
    if c.message:
        await safe_edit_text(c.message, text, _goal_kb(goals))
    await c.answer()


@router.callback_query(F.data.startswith("prem:center:goal:"))
async def premium_center_goal_toggle(c: CallbackQuery) -> None:
    if await _deny_if_not_premium(c):
        return
    parts = (c.data or "").split(":", 2)
    goal = parts[-1] if len(parts) == 3 else ""
    current = set(_load_goal_state(c.from_user.id))
    if goal in current:
        current.remove(goal)
    else:
        current.add(goal)
    _store_goal_state(c.from_user.id, sorted(current))
    goals_sorted = sorted(current)
    if c.message:
        await safe_edit_text(c.message, "Выбери цели для обновления плана:", _goal_kb(goals_sorted))
    _store_goal_state(c.from_user.id, goals_sorted)
    await c.answer()


@router.callback_query(F.data == "prem:center:goal_cancel")
async def premium_center_goal_cancel(c: CallbackQuery) -> None:
    if await _deny_if_not_premium(c):
        return
    _store_goal_state(c.from_user.id, [])
    if c.message:
        await safe_edit_text(c.message, MAIN_MENU_TEXT, _main_menu_kb())
    await c.answer("Изменения отменены")


@router.callback_query(F.data == "prem:center:goal_save")
async def premium_center_goal_save(c: CallbackQuery) -> None:
    if await _deny_if_not_premium(c):
        return
    goals = _load_goal_state(c.from_user.id)
    diff = {"goals": goals}
    await _generate_and_send_plan(c.from_user.id, c, diff=diff, source="edit")


def _parse_value(message: Message, default: float) -> float | None:
    parts = (message.text or "").split()
    if len(parts) < 2:
        return default
    try:
        return float(parts[1].replace("+", ""))
    except ValueError:
        return None


async def _log_habit(message: Message, kind: str, value: float) -> None:
    async with compat_session(session_scope) as session:
        await habits_repo.add_event(session, message.from_user.id, kind, value)
        await events_repo.log(session, message.from_user.id, "habit_track", {"kind": kind, "value": value})
        await commit_safely(session)
    premium_metrics.record_tracker_event()


@router.message(Command("track_water"))
async def track_water(message: Message) -> None:
    if await _deny_if_not_premium(message):
        return
    value = _parse_value(message, 250.0)
    if value is None or value <= 0:
        await message.answer("Введите количество воды в миллилитрах, например /track_water 250")
        return
    await _log_habit(message, "water", value)
    await message.answer(f"💧 Записано {value:.0f} мл воды.")


@router.message(Command("track_sleep"))
async def track_sleep(message: Message) -> None:
    if await _deny_if_not_premium(message):
        return
    value = _parse_value(message, 7.0)
    if value is None or value <= 0:
        await message.answer("Укажи продолжительность сна в часах, например /track_sleep 7")
        return
    await _log_habit(message, "sleep", value)
    await message.answer(f"😴 Сон {value:.1f} ч добавлен.")


@router.message(Command("track_stress"))
async def track_stress(message: Message) -> None:
    if await _deny_if_not_premium(message):
        return
    value = _parse_value(message, 3.0)
    if value is None or not 0 <= value <= 10:
        await message.answer("Укажи уровень стресса от 0 до 10, например /track_stress 3")
        return
    await _log_habit(message, "stress", value)
    await message.answer(f"🧘 Стресс {value:.1f} записан.")


@router.message(Command("progress_chart"))
async def progress_chart(message: Message) -> None:
    if await _deny_if_not_premium(message):
        return
    chart = await _generate_chart(message.from_user.id)
    if chart is None:
        await message.answer("Пока нет данных трекера — добавь записи командами /track_*")
        return
    await message.answer_photo(chart, caption="📈 Прогресс за 7 дней")


@router.message(Command("premium_report"))
async def premium_report(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    metrics = premium_metrics.load_metrics()
    plans = int(metrics.get("ai_plans_sent", 0))
    total_chars = int(metrics.get("plan_chars_total", 0))
    avg_len = total_chars / plans if plans else 0
    text = (
        "💎 Premium аналитика\n"
        f"Активные подписки: {int(metrics.get('active_subs', 0))}\n"
        f"Новых подписок: {int(metrics.get('new_subs', 0))}\n"
        f"AI-планы отправлены: {plans}\n"
        f"Средняя длина плана: {avg_len:.0f} символов\n"
        f"Использование трекера (7д): {int(metrics.get('tracker_events_week', 0))}"
    )
    await message.answer(text)


def _report_chart(metrics: dict[str, int]) -> BufferedInputFile:
    if plt is None:
        raise RuntimeError("matplotlib is required for chart generation")
    labels = ["Активные", "Новые", "AI-планы", "Трекер 7д"]
    values = [
        int(metrics.get("active_subs", 0)),
        int(metrics.get("new_subs", 0)),
        int(metrics.get("ai_plans_sent", 0)),
        int(metrics.get("tracker_events_week", 0)),
    ]
    fig, ax = plt.subplots(figsize=(5, 3))
    ax.bar(labels, values, color=["#6fa8dc", "#93c47d", "#ffd966", "#c27ba0"])
    ax.set_title("Premium-метрики")
    ax.set_ylabel("Количество")
    peak = max(values) if any(values) else 1
    for idx, value in enumerate(values):
        ax.text(idx, value + peak * 0.05, str(value), ha="center")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return BufferedInputFile(buf.getvalue(), filename="premium_report.png")


@router.message(Command("premium_report_img"))
async def premium_report_img(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return
    metrics = premium_metrics.load_metrics()
    if plt is None:
        await message.answer("matplotlib не установлен — график недоступен")
        return
    chart = _report_chart(metrics)
    await message.answer_photo(chart, caption="Premium-метрики")
