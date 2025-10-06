# app/handlers/admin.py
from aiogram import Router
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command
from io import StringIO
from datetime import datetime

from app.config import settings
from app.storage import get_leads_last
from app.notifications import collect_daily_stats, render_stats_report, render_error_report

router = Router()


@router.message(Command("stats"))
async def stats(m: Message):
    if m.from_user.id != settings.ADMIN_ID:
        return
    hours = 24
    parts = m.text.strip().split()
    if len(parts) > 1:
        try:
            hours = max(1, int(parts[1]))
        except Exception:
            hours = 24
    stats = await collect_daily_stats(hours)
    await m.answer(
        render_stats_report(stats)
        + "\n\nКоманды:\n"
        "• /leads — последние 10 лидов\n"
        "• /leads 20 — последние 20 лидов\n"
        "• /leads_csv — CSV последних 100\n"
        "• /leads_csv 500 — CSV последних 500\n"
        "• /errors — ошибки за период"
    )


@router.message(Command("errors"))
async def errors_report(m: Message):
    if m.from_user.id != settings.ADMIN_ID:
        return
    hours = 24
    parts = m.text.strip().split()
    if len(parts) > 1:
        try:
            hours = max(1, int(parts[1]))
        except Exception:
            hours = 24
    report = await render_error_report(window_hours=hours)
    await m.answer(report)


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

    items = await get_leads_last(n)
    if not items:
        await m.answer("Лидов пока нет.")
        return

    # Рендер карточек
    chunks = []
    for i, lead in enumerate(items, 1):
        chunks.append(
            f"#{i} — <b>{lead.name or '(без имени)'}</b>\n"
            f"📞 {lead.phone or '(нет)'}\n"
            f"💬 {lead.comment or '(пусто)'}\n"
            f"👤 {lead.username or lead.user_id or '(нет)'}\n"
            f"🕒 {lead.created_at.isoformat()}"
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

    items = await get_leads_last(n)
    if not items:
        await m.answer("Лидов пока нет.")
        return

    # CSV
    out = StringIO()
    out.write("ts;name;phone;comment;username;user_id\n")
    for lead in items:
        ts = lead.created_at.isoformat()
        name = (lead.name or "").replace(";", ",")
        phone = lead.phone or ""
        comment = (lead.comment or "").replace(";", ",")
        username = lead.username or ""
        user_id = lead.user_id or ""
        out.write(f"{ts};{name};{phone};{comment};{username};{user_id}\n")

    csv_bytes = out.getvalue().encode("utf-8")
    out.close()

    fname = f"leads_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    await m.answer_document(BufferedInputFile(csv_bytes, filename=fname), caption=f"Экспорт лидов ({len(items)})")
