# app/scheduler/jobs.py
import datetime as dt
import json
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot
from sqlalchemy import func, or_, select

from app.config import settings
from app.db.models import Event, Lead, Subscription
from app.db.session import session_scope
from app.repo import events as events_repo
from app.services.partner_links import check_partner_links, filter_partner_issues
from app.utils_openai import ai_generate

_analytics_log = logging.getLogger("scheduler.analytics")


async def send_nudges(bot: Bot, tz_name: str, weekdays: set[str]):
    """
    Рассылка «мягких напоминаний» тем, кто согласился (последнее событие notify_on).
    Дни недели фильтруем по TZ; тексты — короткие, через ChatGPT для свежести.
    """
    now_local = dt.datetime.now(ZoneInfo(tz_name))
    wd = now_local.strftime("%a")  # 'Mon', 'Tue', ...
    if weekdays and wd not in weekdays:
        return

    prompt = (
        "Сделай короткий мотивирующий чек-лист (3–4 строки) для энергии и здоровья: "
        "сон, утренний свет, 30 минут быстрой ходьбы. Пиши дружелюбно, без воды."
    )
    text = await ai_generate(prompt)
    if not text or text.startswith("⚠️"):
        text = "Микро-челлендж дня:\n" "☑️ Сон 7–9 часов\n" "☑️ 10 мин утреннего света\n" "☑️ 30 мин быстрой ходьбы"

    async with session_scope() as session:
        user_ids = await events_repo.notify_recipients(session)

    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
        except Exception:
            continue


async def _start_followup_candidates(session, cutoff: dt.datetime) -> list[int]:
    latest_start = (
        select(Event.user_id, func.max(Event.ts).label("ts"))
        .where(Event.name == "start", Event.user_id.is_not(None))
        .group_by(Event.user_id)
        .subquery()
    )
    latest_quiz = (
        select(Event.user_id, func.max(Event.ts).label("ts"))
        .where(Event.name == "quiz_finish", Event.user_id.is_not(None))
        .group_by(Event.user_id)
        .subquery()
    )
    latest_nudge = (
        select(Event.user_id, func.max(Event.ts).label("ts"))
        .where(Event.name == "retention_test_nudge", Event.user_id.is_not(None))
        .group_by(Event.user_id)
        .subquery()
    )

    stmt = (
        select(latest_start.c.user_id)
        .outerjoin(latest_quiz, latest_quiz.c.user_id == latest_start.c.user_id)
        .outerjoin(latest_nudge, latest_nudge.c.user_id == latest_start.c.user_id)
        .where(
            latest_start.c.ts <= cutoff,
            or_(
                latest_quiz.c.ts.is_(None),
                latest_quiz.c.ts < latest_start.c.ts,
            ),
            or_(
                latest_nudge.c.ts.is_(None),
                latest_nudge.c.ts < latest_start.c.ts,
            ),
        )
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all() if row[0] is not None]


async def _premium_followup_candidates(
    session, cutoff: dt.datetime, now: dt.datetime
) -> list[int]:
    latest_quiz = (
        select(Event.user_id, func.max(Event.ts).label("ts"))
        .where(Event.name == "quiz_finish", Event.user_id.is_not(None))
        .group_by(Event.user_id)
        .subquery()
    )
    latest_nudge = (
        select(Event.user_id, func.max(Event.ts).label("ts"))
        .where(Event.name == "retention_premium_nudge", Event.user_id.is_not(None))
        .group_by(Event.user_id)
        .subquery()
    )
    active_subs = (
        select(Subscription.user_id)
        .where(Subscription.until > now)
        .subquery()
    )

    stmt = (
        select(latest_quiz.c.user_id)
        .outerjoin(active_subs, active_subs.c.user_id == latest_quiz.c.user_id)
        .outerjoin(latest_nudge, latest_nudge.c.user_id == latest_quiz.c.user_id)
        .where(
            latest_quiz.c.ts <= cutoff,
            active_subs.c.user_id.is_(None),
            or_(
                latest_nudge.c.ts.is_(None),
                latest_nudge.c.ts < latest_quiz.c.ts,
            ),
        )
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all() if row[0] is not None]


async def send_retention_reminders(bot: Bot) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    start_cutoff = now - dt.timedelta(hours=24)
    premium_cutoff = now - dt.timedelta(hours=72)

    async with session_scope() as session:
        start_candidates = await _start_followup_candidates(session, start_cutoff)
        premium_candidates = await _premium_followup_candidates(session, premium_cutoff, now)

    sent_start: list[int] = []
    sent_premium: list[int] = []

    for uid in start_candidates:
        try:
            await bot.send_message(uid, "⚡ Начать тест энергии")
        except Exception:
            continue
        else:
            sent_start.append(uid)

    for uid in premium_candidates:
        try:
            await bot.send_message(uid, "💎 Включи Премиум — получай подборку каждую неделю")
        except Exception:
            continue
        else:
            sent_premium.append(uid)

    if not sent_start and not sent_premium:
        return

    async with session_scope() as session:
        for uid in sent_start:
            await events_repo.log(session, uid, "retention_test_nudge", {})
        for uid in sent_premium:
        await events_repo.log(session, uid, "retention_premium_nudge", {})
        await session.commit()


async def partner_link_health(bot: Bot) -> None:
    chat_id = settings.PARTNER_ALERT_CHAT_ID or settings.ADMIN_ID
    if not chat_id:
        return

    try:
        results = await check_partner_links()
    except Exception as exc:  # pragma: no cover - defensive logging
        logging.getLogger("scheduler.partner").exception(
            "partner link check failed: %s", exc
        )
        return

    issues = filter_partner_issues(results)
    if not issues:
        return

    lines = ["⚠️ Партнёрские ссылки: обнаружены проблемы", ""]
    for issue in issues[:10]:
        fragments: list[str] = []
        if issue.error:
            fragments.append(issue.error)
        if issue.status < 200 or issue.status >= 400:
            fragments.append(f"status={issue.status}")
        fragments.extend(issue.utm_issues)
        detail = "; ".join(fragments) or "неизвестная ошибка"
        lines.append(f"• {issue.link.title} ({issue.link.product_id}) — {detail}")
        lines.append(f"  {issue.link.url}")
        if issue.final_url and issue.final_url != issue.link.url:
            lines.append(f"  → {issue.final_url}")
    if len(issues) > 10:
        lines.append(f"…ещё {len(issues) - 10} ссылок")

    message = "\n".join(lines)
    try:
        await bot.send_message(chat_id, message)
    except Exception:  # pragma: no cover - bot delivery issues
        logging.getLogger("scheduler.partner").exception("failed to send partner alert")


async def export_analytics_snapshot() -> Path | None:
    target = getattr(settings, "ANALYTICS_EXPORT_PATH", "")
    if not target:
        _analytics_log.info("analytics export skipped: path not configured")
        return None

    export_path = Path(target)
    now = dt.datetime.now(dt.timezone.utc)
    day_ago = now - dt.timedelta(hours=24)
    week_ago = now - dt.timedelta(days=7)

    async with session_scope() as session:
        quiz_24h = await events_repo.stats(session, name="quiz_finish", since=day_ago)
        quiz_7d = await events_repo.stats(session, name="quiz_finish", since=week_ago)
        plans_24h = await events_repo.stats(session, name="plan_generated", since=day_ago)
        plans_7d = await events_repo.stats(session, name="plan_generated", since=week_ago)
        retention_test_24h = await events_repo.stats(session, name="retention_test_nudge", since=day_ago)
        retention_test_7d = await events_repo.stats(session, name="retention_test_nudge", since=week_ago)
        retention_premium_24h = await events_repo.stats(
            session, name="retention_premium_nudge", since=day_ago
        )
        retention_premium_7d = await events_repo.stats(
            session, name="retention_premium_nudge", since=week_ago
        )

        total_leads_stmt = select(func.count(Lead.id))
        total_leads = (await session.execute(total_leads_stmt)).scalar_one()
        leads_7d_stmt = select(func.count(Lead.id)).where(Lead.ts >= week_ago)
        leads_7d = (await session.execute(leads_7d_stmt)).scalar_one()

        active_subs_stmt = select(func.count(Subscription.user_id)).where(Subscription.until > now)
        active_subs = (await session.execute(active_subs_stmt)).scalar_one()
        new_subs_stmt = select(func.count(Subscription.user_id)).where(Subscription.since >= week_ago)
        new_subs = (await session.execute(new_subs_stmt)).scalar_one()

    payload = {
        "generated_at": now.isoformat(),
        "quiz_finishes": {"24h": quiz_24h, "7d": quiz_7d},
        "plans": {"24h": plans_24h, "7d": plans_7d},
        "retention": {
            "test": {"24h": retention_test_24h, "7d": retention_test_7d},
            "premium": {"24h": retention_premium_24h, "7d": retention_premium_7d},
        },
        "leads": {"total": total_leads, "7d": leads_7d},
        "premium": {"active": active_subs, "new_7d": new_subs},
    }

    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _analytics_log.info("analytics snapshot exported", extra={"path": str(export_path)})
    return export_path
