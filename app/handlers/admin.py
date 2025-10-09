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
from app.repo import (
    events as events_repo,
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
from app.services.growth import collect_growth_report
from app.utils.utm import build_deep_link, format_utm_label, format_utm_tuple, parse_utm_kv

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


def _format_percent(value: float) -> str:
    return f"{value:.1f}%"


def _format_currency(amount: float) -> str:
    return f"{amount:,.0f}".replace(",", " ")


def _parse_days_argument(raw: str, default: int = 7) -> int:
    for token in raw.replace(",", " ").split():
        try:
            value = int(token)
        except ValueError:
            continue
        return max(1, min(90, value))
    return default


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


@router.message(Command("link_builder"))
@admin_only
async def link_builder_cmd(message: Message, command: CommandObject) -> None:
    args = (command.args or "").strip() if command else ""
    bot = message.bot
    me = await bot.get_me()
    username = me.username or "your_bot"

    if not args:
        await message.answer(
            "🔧 Конструктор deep-link\n"
            "Использование: /link_builder source=tiktok medium=ads campaign=spring content=shorts01\n"
            "Поддерживаются ключи: utm_source, utm_medium, utm_campaign, utm_content (и короткие алиасы)."
        )
        return

    params = parse_utm_kv(args)
    if not params:
        await message.answer("Не удалось распознать параметры. Укажите пары вида source=tiktok.")
        return

    link, payload = build_deep_link(username, params)
    label = format_utm_tuple(
        params.get("utm_source"),
        params.get("utm_medium"),
        params.get("utm_campaign"),
        params.get("utm_content"),
    )
    payload_text = payload or "(пусто — будет /start без параметров)"

    await message.answer(
        "🔗 Deep-link готов\n"
        f"{link}\n\n"
        f"start payload: {payload_text}\n"
        f"UTM: {label}\n"
        "Скопируй ссылку и используй в рекламном канале."
    )


@router.message(Command("growth_report"))
@admin_only
async def growth_report_cmd(message: Message, command: CommandObject) -> None:
    args = (command.args or "").strip() if command else ""
    days = _parse_days_argument(args)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    async with compat_session(session_scope) as session:
        report = await collect_growth_report(session, since=since, until=now)

    total_users = sum(row.new_users for row in report.users)
    total_quiz = sum(row.quiz for row in report.users)
    total_reco = sum(row.recommendations for row in report.users)
    total_subs = sum(row.subscriptions for row in report.users)
    total_orders = sum(row.orders for row in report.orders)
    total_revenue = sum(row.revenue for row in report.orders)
    total_payers = sum(row.payers for row in report.orders)

    lines: list[str] = [
        "📈 Growth report",
        f"Период: {since.date()} – {report.until.date()} ({days} дн.)",
        f"Новые пользователи: {total_users}",
    ]

    if total_users:
        lines.append(
            "CR → тесты {tests}/{users} ({tests_cr}), рекомендации {reco}/{users} ({reco_cr}), подписки {subs}/{users} ({subs_cr})".format(
                tests=total_quiz,
                users=total_users,
                tests_cr=_format_percent(total_quiz / total_users * 100.0),
                reco=total_reco,
                reco_cr=_format_percent(total_reco / total_users * 100.0),
                subs=total_subs,
                subs_cr=_format_percent(total_subs / total_users * 100.0),
            )
        )
    else:
        lines.append("Нет новых пользователей за выбранный период.")

    if report.users:
        lines.append("")
        lines.append("UTM источники → конверсии:")
        max_rows = 12
        for row in report.users[:max_rows]:
            label = format_utm_label(row.source, row.medium, row.campaign, row.content)
            lines.append(
                "• {label}: {users} → тесты {tests} ({tests_cr}), рекомендации {reco} ({reco_cr}), подписки {subs} ({subs_cr})".format(
                    label=label,
                    users=row.new_users,
                    tests=row.quiz,
                    tests_cr=_format_percent(row.quiz_cr()),
                    reco=row.recommendations,
                    reco_cr=_format_percent(row.recommendation_cr()),
                    subs=row.subscriptions,
                    subs_cr=_format_percent(row.subscription_cr()),
                )
            )
        remaining = len(report.users) - max_rows
        if remaining > 0:
            lines.append(f"…и ещё {remaining} источников")
    else:
        lines.append("")
        lines.append("UTM источники: данных нет")

    lines.append("")
    lines.append(
        "Платежи orders_paid: {orders} заказов, плательщиков {payers}, выручка ₽{revenue}".format(
            orders=total_orders,
            payers=total_payers,
            revenue=_format_currency(total_revenue),
        )
    )
    if report.orders:
        lines.append("По источникам:")
        max_rows = 12
        for row in report.orders[:max_rows]:
            label = format_utm_label(row.source, row.medium, row.campaign, row.content)
            lines.append(
                "• {label}: {orders} заказов, плательщиков {payers}, выручка ₽{revenue}".format(
                    label=label,
                    orders=row.orders,
                    payers=row.payers,
                    revenue=_format_currency(row.revenue),
                )
            )
        remaining = len(report.orders) - max_rows
        if remaining > 0:
            lines.append(f"…и ещё {remaining} источников")
    else:
        lines.append("Источники платежей: данных нет")

    lines.append("")
    lines.append("Измени период: /growth_report 30 — последние 30 дней")

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
