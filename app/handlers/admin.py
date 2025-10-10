# app/handlers/admin.py
"""Administrative handlers for bot commands."""

from datetime import datetime
from io import StringIO

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from app.config import settings
from app.catalog.loader import load_products
from app.storage import USERS, EVENTS, get_leads_last, get_leads_all

router = Router()


@router.message(Command("stats"))
async def stats(m: Message):
    if m.from_user.id != settings.ADMIN_ID:
        return
    total_users = len(USERS)
    subs = sum(1 for u in USERS.values() if u.get("subs"))
    quizzes = sum(1 for e in EVENTS if e["action"] == "quiz_finish")
    starts = sum(1 for e in EVENTS if e["action"] == "start")
    leads_cnt = len(get_leads_all())

    await m.answer(
        "📊 Статистика\n"
        f"Пользователи: {total_users}\n"
        f"Подписаны на напоминания: {subs}\n"
        f"Стартов: {starts}\n"
        f"Завершено квизов: {quizzes}\n"
        f"Лиды (всего): {leads_cnt}\n\n"
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

    # /leads <N?>
    parts = m.text.strip().split()
    try:
        n = int(parts[1]) if len(parts) > 1 else 10
    except Exception:
        n = 10

    items = get_leads_last(n)
    if not items:
        await m.answer("Лидов пока нет.")
        return

    # Рендер карточек
    chunks = []
    for i, lead in enumerate(items, 1):
        chunks.append(
            f"#{i} — <b>{lead.get('name','(без имени)')}</b>\n"
            f"📞 {lead.get('phone','(нет)')}\n"
            f"💬 {lead.get('comment','(пусто)')}\n"
            f"👤 {lead.get('username')}\n"
            f"🕒 {lead.get('ts')}"
        )

    text = "📝 Последние лиды:\n\n" + "\n\n".join(chunks)
    # телега ограничивает длину — если слишком длинно, порежем
    if len(text) > 4000:
        text = text[:3900] + "\n\n…обрезано, выгрузи CSV → /leads_csv"
    await m.answer(text)


@router.message(Command("leads_csv"))
async def leads_csv(m: Message):
    if m.from_user.id != settings.ADMIN_ID:
        return

    # /leads_csv <N?>
    parts = m.text.strip().split()
    try:
        n = int(parts[1]) if len(parts) > 1 else 100
    except Exception:
        n = 100

    items = get_leads_last(n)
    if not items:
        await m.answer("Лидов пока нет.")
        return

    # CSV
    out = StringIO()
    out.write("ts;name;phone;comment;username;user_id\n")
    for lead in items:
        ts = lead.get("ts", "")
        name = (lead.get("name", "").replace(";", ","))
        phone = lead.get("phone", "")
        comment = (lead.get("comment", "").replace(";", ","))
        username = lead.get("username", "")
        user_id = lead.get("user_id", "")
        out.write(f"{ts};{name};{phone};{comment};{username};{user_id}\n")

    csv_bytes = out.getvalue().encode("utf-8")
    out.close()

    fname = f"leads_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    await m.answer_document(BufferedInputFile(csv_bytes, filename=fname), caption=f"Экспорт лидов ({len(items)})")


@router.message(Command("catalog_reload"))
async def catalog_reload(m: Message):
    if m.from_user.id != settings.ADMIN_ID:
        return
    try:
        data = load_products(force=True)
    except Exception as exc:
        await m.answer(f"Не удалось обновить каталог: {exc}")
        return
    await m.answer(
        "Каталог обновлён."
        f"\nКатегорий: {len(data.categories)}"
        f"\nТоваров: {len(data.products)}"
    )
