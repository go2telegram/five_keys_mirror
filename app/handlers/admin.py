from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from app.catalog.report import CatalogReportError, get_catalog_report
from app.calculators.engine import CALCULATORS
from app.config import settings
from app.db.session import (
    compat_session,
    current_revision,
    head_revision,
    session_scope,
    upgrade_to_head,
)
from app.repo import (
    calculator_results as calc_results_repo,
    events as events_repo,
    leads as leads_repo,
    referrals as referrals_repo,
    subscriptions as subscriptions_repo,
    users as users_repo,
)

router = Router()


def _is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    allowed = set(settings.ADMIN_USER_IDS or [])
    allowed.add(settings.ADMIN_ID)
    return user_id in allowed


def _calculator_label(slug: str) -> str:
    definition = CALCULATORS.get(slug)
    if definition is not None:
        return definition.title
    if slug == "msd":
        return "Калькулятор MSD"
    return slug


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


@router.message(Command("calc_report"))
async def calc_report(m: Message) -> None:
    if not _is_admin(m.from_user.id if m.from_user else None):
        return

    text = (m.text or "").strip()
    parts = text.split()
    days = 7
    if len(parts) > 1:
        try:
            days = int(parts[1])
        except Exception:
            days = 7

    since = None
    period_label = "за всё время"
    if days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        period_label = f"за последние {days} дн."

    async with compat_session(session_scope) as session:
        usage = await calc_results_repo.usage_summary(session, since=since)
        errors = await calc_results_repo.recent_errors(session, since=since, limit=5)

    if not usage and not errors:
        await m.answer("🧮 Калькуляторы: пока нет данных для отчёта.")
        return

    lines = [f"🧮 Отчёт по калькуляторам ({period_label})"]

    if usage:
        total_ok = sum(item.ok for item in usage)
        total_err = sum(item.error for item in usage)
        lines.append("")
        lines.append("Использование:")
        for item in usage:
            label = _calculator_label(item.calculator)
            if item.error:
                lines.append(f"• {label}: {item.ok} заверш., {item.error} ошибок")
            else:
                lines.append(f"• {label}: {item.ok} заверш.")
        lines.append(f"Всего: {total_ok} заверш., {total_err} ошибок")

    if errors:
        lines.append("")
        lines.append("Ошибки (последние):")
        tz = ZoneInfo(settings.TIMEZONE) if getattr(settings, "TIMEZONE", None) else None
        for record in errors:
            label = _calculator_label(record.calculator)
            ts = record.created
            if ts and tz:
                ts = ts.astimezone(tz)
            ts_text = ts.strftime("%Y-%m-%d %H:%M") if ts else "—"
            payload = record.input_data or {}
            step = payload.get("step") if isinstance(payload, dict) else None
            raw_value = payload.get("raw") if isinstance(payload, dict) else None
            raw_text = str(raw_value or "")
            if len(raw_text) > 40:
                raw_text = raw_text[:37] + "…"
            detail = f"шаг: {step}" if step else ""
            if detail and raw_text:
                detail = f"{detail}, ввод: {raw_text}"
            elif raw_text:
                detail = f"ввод: {raw_text}"
            if record.user_id:
                detail = f"uid {record.user_id}{(', ' + detail) if detail else ''}"
            error_text = record.error or "ошибка"
            if detail:
                lines.append(f"• {ts_text} — {label}: {error_text} ({detail})")
            else:
                lines.append(f"• {ts_text} — {label}: {error_text}")

    await m.answer("\n".join(lines))


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
