from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from datetime import datetime
from io import StringIO

from app.config import settings
from app.db.session import session_scope
from app.repo import events as events_repo
from app.repo import leads as leads_repo
from app.repo import referrals as referrals_repo
from app.repo import subscriptions as subscriptions_repo
from app.repo import users as users_repo

router = Router()


@router.message(Command("stats"))
async def stats(m: Message):
    if m.from_user.id != settings.ADMIN_ID:
        return

    async with session_scope() as session:
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
    if m.from_user.id != settings.ADMIN_ID:
        return

    parts = m.text.strip().split()
    try:
        limit = int(parts[1]) if len(parts) > 1 else 10
    except Exception:
        limit = 10

    async with session_scope() as session:
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
    if m.from_user.id != settings.ADMIN_ID:
        return

    parts = m.text.strip().split()
    try:
        limit = int(parts[1]) if len(parts) > 1 else 100
    except Exception:
        limit = 100

    async with session_scope() as session:
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
