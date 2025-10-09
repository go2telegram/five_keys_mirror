from datetime import datetime, timedelta, timezone
from functools import wraps
from io import StringIO
from pathlib import Path
from typing import Awaitable, Callable, ParamSpec, TypeVar
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, FSInputFile, Message

from app.catalog.report import CatalogReportError, get_catalog_report
from app.config import settings
from app.db.session import (
    compat_session,
    current_revision,
    head_revision,
    session_scope,
    upgrade_to_head,
)
from app.feature_flags import feature_flags
from app.repo import (
    events as events_repo,
    retention as retention_repo,
    leads as leads_repo,
    referrals as referrals_repo,
    subscriptions as subscriptions_repo,
    users as users_repo,
)
from app.middlewares import (
    is_callback_trace_enabled,
    set_callback_trace_enabled,
)
from app.router_map import get_router_map, write_router_map

router = Router()


def _is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    allowed = set(settings.ADMIN_USER_IDS or [])
    allowed.add(settings.ADMIN_ID)
    return user_id in allowed


P = ParamSpec("P")
R = TypeVar("R")


def admin_only(handler: Callable[P, Awaitable[R]]):
    @wraps(handler)
    async def wrapper(*args: P.args, **kwargs: P.kwargs):
        target = args[0] if args else kwargs.get("message")
        from_user = getattr(target, "from_user", None)
        user_id = getattr(from_user, "id", None)
        if not _is_admin(user_id):
            return None
        return await handler(*args, **kwargs)

    return wrapper


def _format_flag_snapshot() -> str:
    snapshot = feature_flags.snapshot()
    defaults = feature_flags.defaults()
    canary_flags = set(feature_flags.canary_flags())
    lines: list[str] = []
    percent = feature_flags.canary_percent()
    for name in feature_flags.available():
        enabled = snapshot.get(name, False)
        default = defaults.get(name, False)
        status = "ON" if enabled else "OFF"
        hints: list[str] = []
        if enabled != default:
            hints.append("override")
        if name in canary_flags and percent:
            hints.append(f"canary {percent}%")
        suffix = f" ({', '.join(hints)})" if hints else ""
        lines.append(f"• {name}: {status}{suffix}")
    return "\n".join(lines) if lines else "• нет флагов"


@router.message(Command("stats"))
async def stats(m: Message):
    if not _is_admin(m.from_user.id if m.from_user else None):
        return

    async with compat_session(session_scope) as session:
        total_users = await users_repo.count(session)
        active_subs = await subscriptions_repo.count_active(session)
        quiz_finishes = await events_repo.stats(session, name="quiz_finish")
        starts = await events_repo.stats(session, name="start")
        leads_cnt = await leads_repo.count(session)
        referrals_conv = await referrals_repo.converted_count(session)

    await m.answer(
        "📊 Статистика\n"
        f"Пользователи: {total_users}\n"
        f"Активные подписки: {active_subs}\n"
        f"Стартов: {starts}\n"
        f"Завершено квизов: {quiz_finishes}\n"
        f"Лиды (всего): {leads_cnt}\n"
        f"Рефералы (конверсии): {referrals_conv}\n\n"
        "Команды:\n"
        "• /leads — последние 10 лидов\n"
        "• /leads 20 — последние 20 лидов\n"
        "• /leads_csv — CSV последних 100\n"
        "• /leads_csv 500 — CSV последних 500"
    )


@router.message(Command("retention_report"))
async def retention_report(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1)

    async with compat_session(session_scope) as session:
        tip_enabled = await retention_repo.count_tip_enabled(session)
        sent = await events_repo.stats(session, name="daily_tip_sent", since=since)
        clicks = await events_repo.stats(session, name="daily_tip_click", since=since)
        click_users = await retention_repo.count_tip_click_users(session, since=since)

    ctr = (clicks / sent * 100.0) if sent else 0.0
    await message.answer(
        "📈 Retention-отчёт\n"
        f"Советы включены у: {tip_enabled}\n"
        f"Отправлено за 24ч: {sent}\n"
        f"Кликов за 24ч: {clicks} (уникальных: {click_users})\n"
        f"CTR: {ctr:.1f}%",
    )


@router.message(Command("leads"))
async def leads_list(m: Message):
    if not _is_admin(m.from_user.id if m.from_user else None):
        return

    parts = m.text.strip().split()
    try:
        limit = int(parts[1]) if len(parts) > 1 else 10
    except Exception:
        limit = 10

    async with compat_session(session_scope) as session:
        items = await leads_repo.list_last(session, limit)

    if not items:
        await m.answer("Лидов пока нет.")
        return

    chunks: list[str] = []
    for idx, lead in enumerate(items, 1):
        username = f"@{lead.username}" if lead.username else str(lead.user_id or "(нет)")
        ts = lead.ts.strftime("%Y-%m-%d %H:%M:%S") if lead.ts else ""
        chunks.append(
            f"#{idx} — <b>{lead.name or '(без имени)'}</b>\n"
            f"📞 {lead.phone or '(нет)'}\n"
            f"💬 {lead.comment or '(пусто)'}\n"
            f"👤 {username}\n"
            f"🕒 {ts}"
        )

    text = "📝 Последние лиды:\n\n" + "\n\n".join(chunks)
    if len(text) > 4000:
        text = text[:3900] + "\n\n…обрезано, выгрузи CSV → /leads_csv"
    await m.answer(text)


@router.message(Command("leads_csv"))
async def leads_csv(m: Message):
    if not _is_admin(m.from_user.id if m.from_user else None):
        return

    parts = m.text.strip().split()
    try:
        limit = int(parts[1]) if len(parts) > 1 else 100
    except Exception:
        limit = 100

    async with compat_session(session_scope) as session:
        items = await leads_repo.list_last(session, limit)

    if not items:
        await m.answer("Лидов пока нет.")
        return

    out = StringIO()
    out.write("ts;name;phone;comment;username;user_id\n")
    for lead in items:
        ts = lead.ts.strftime("%Y-%m-%d %H:%M:%S") if lead.ts else ""
        name = (lead.name or "").replace(";", ",")
        phone = (lead.phone or "").replace(";", ",")
        comment = (lead.comment or "").replace(";", ",")
        username = (lead.username or "").replace(";", ",")
        user_id = lead.user_id or ""
        out.write(f"{ts};{name};{phone};{comment};{username};{user_id}\n")

    csv_bytes = out.getvalue().encode("utf-8")
    out.close()

    fname = f"leads_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    await m.answer_document(
        BufferedInputFile(csv_bytes, filename=fname),
        caption=f"Экспорт лидов ({len(items)})",
    )


@router.message(Command("debug_callbacks"))
async def debug_callbacks(message: Message, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return

    arg = (command.args or "").strip().lower() if command else ""
    current = is_callback_trace_enabled()

    if arg in {"on", "off"}:
        enabled = arg == "on"
        set_callback_trace_enabled(enabled)
        status = "включен" if enabled else "выключен"
        await message.answer(f"🪪 Callback trace {status}.")
        return

    status = "включен" if current else "выключен"
    await message.answer(
        "ℹ️ Callback trace сейчас {status}. Используй /debug_callbacks on|off.".format(
            status=status
        )
    )


@router.message(Command("routers"))
async def routers_dump(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        return

    snapshot = get_router_map()
    if not snapshot:
        await message.answer("Карта роутеров ещё не собрана.")
        return

    lines = ["🛣 <b>Router map</b>"]
    for idx, entry in enumerate(snapshot, start=1):
        event_counts = ", ".join(
            f"{event.event}:{len(event.handlers)}" for event in entry.patterns
        )
        lines.append(
            f"{idx}. {entry.name} — {entry.handlers_count} handlers" + (
                f" ({event_counts})" if event_counts else ""
            )
        )

    path = write_router_map(Path("build/reports/routers.json"))

    await message.answer("\n".join(lines))
    await message.answer_document(FSInputFile(path), caption="Router map JSON")


@router.message(Command("toggle"))
@admin_only
async def toggle_flag(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split() if command else []
    if len(args) != 2:
        await message.answer("Использование: /toggle <FLAG> on|off")
        return

    flag = args[0].strip().upper()
    desired = args[1].strip().lower()

    if flag not in feature_flags.available():
        available = ", ".join(feature_flags.available()) or "(нет доступных флагов)"
        await message.answer(f"Неизвестный флаг {flag}. Доступно: {available}")
        return

    if desired not in {"on", "off"}:
        await message.answer("Значение должно быть on или off.")
        return

    enabled = desired == "on"

    try:
        await feature_flags.set_flag(flag, enabled)
    except Exception as exc:  # pragma: no cover - defensive guard
        await message.answer(f"Не удалось обновить флаг: {exc}")
        return

    snapshot = feature_flags.snapshot()
    defaults = feature_flags.defaults()
    state = "ON" if snapshot.get(flag, False) else "OFF"
    note = " (по умолчанию)" if snapshot.get(flag, False) == defaults.get(flag, False) else " (override)"

    overview = _format_flag_snapshot()
    await message.answer(
        "✅ Флаг {flag} переключён в состояние {state}{note}.\n\n{overview}".format(
            flag=flag,
            state=state,
            note=note,
            overview=overview,
        )
    )


@router.message(Command("ab_status"))
@admin_only
async def ab_status(message: Message) -> None:
    percent = feature_flags.canary_percent()
    canary_flags = ", ".join(feature_flags.canary_flags()) or "—"
    lines = [
        "🧪 Feature flags rollout",
        f"Environment: {feature_flags.environment()}",
        f"Canary rollout: {percent}% (flags: {canary_flags})",
        "",
        _format_flag_snapshot(),
    ]
    await message.answer("\n".join(lines))


@router.message(Command("ci_report"))
@admin_only
async def ci_report_cmd(m: Message) -> None:
    report_path = Path("build/reports/ci_diagnostics.md")
    if not report_path.exists():
        await m.answer("📄 Отчёт CI пока не найден.")
        return

    await m.answer_document(
        FSInputFile(report_path),
        caption="CI diagnostics report",
    )


@router.message(Command("doctor_db"))
async def doctor_db(m: Message) -> None:
    if not _is_admin(m.from_user.id if m.from_user else None):
        return

    db_url = settings.DB_URL
    current = await current_revision(db_url)
    head = await head_revision(db_url)

    lines = [
        "🩺 <b>Doctor DB</b>",
        f"Текущая ревизия: {current or '—'}",
        f"Последняя миграция: {head or '—'}",
    ]

    if not head:
        lines.append("⚠️ Не удалось определить последнюю ревизию Alembic.")
        await m.answer("\n".join(lines))
        return

    if current == head:
        lines.append("✅ База данных уже в актуальном состоянии.")
        await m.answer("\n".join(lines))
        return

    lines.append("⚙️ Применяем миграции…")
    await m.answer("\n".join(lines))

    applied = await upgrade_to_head(db_url=db_url, timeout=None)
    updated_revision = await current_revision(db_url)

    if applied:
        text = (
            "✅ Миграции применены.\n"
            f"Текущая ревизия: {updated_revision or '—'}"
        )
    else:
        text = (
            "❌ Не удалось применить миграции. Подробности в логах.\n"
            f"Текущая ревизия: {updated_revision or current or '—'}"
        )

    await m.answer(text)


def _format_catalog_items(items: list[str], *, limit: int = 10) -> str:
    if not items:
        return "—"
    preview = items[:limit]
    remainder = len(items) - len(preview)
    formatted = ", ".join(preview)
    if remainder > 0:
        formatted += f", … (+{remainder})"
    return formatted


def _format_catalog_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


@router.message(Command("catalog_report"))
async def catalog_report(m: Message) -> None:
    if not _is_admin(m.from_user.id if m.from_user else None):
        return

    try:
        report = get_catalog_report()
    except CatalogReportError as exc:
        await m.answer(f"Не удалось собрать отчёт: {exc}")
        return

    tz = None
    try:
        tz = ZoneInfo(settings.TIMEZONE)
    except Exception:  # noqa: BLE001 - timezone may be invalid in config
        tz = None

    timestamp = "—"
    if report.generated_at:
        dt = report.generated_at
        if tz:
            dt = dt.astimezone(tz)
        timestamp = dt.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
        if not timestamp:
            timestamp = dt.isoformat(timespec="seconds")

    text = (
        "📦 <b>Каталог</b>\n"
        f"found_descriptions={report.found_descriptions}\n"
        f"found_images={report.found_images}\n"
        f"built={report.built}\n"
        f"missing_images: {_format_catalog_items(report.missing_images)}\n"
        f"unmatched_images: {_format_catalog_items(report.unmatched_images)}\n"
        f"catalog: {_format_catalog_path(report.catalog_path)}\n"
        f"build_time: {timestamp}"
    )

    await m.answer(text)
