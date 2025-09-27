# app/handlers/report.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.filters import Command
from datetime import datetime

from app.storage import get_last_plan
from app.pdf_report import build_pdf

router = Router()


def _clean_lines(lines: list[str]) -> list[str]:
    out = []
    for s in lines:
        s = (s.replace("<b>", "").replace("</b>", "")
             .replace("<i>", "").replace("</i>", "")
             .replace("&nbsp;", " "))
        out.append(s)
    return out


def _compose_pdf(plan: dict) -> bytes:
    title = plan.get("title", "Персональный план")
    context_name = plan.get("context_name", "")
    level = plan.get("level")
    subtitle = f"{context_name} • {level}" if level else context_name

    actions = plan.get("actions", [])
    products = _clean_lines(plan.get("lines", []))
    notes = plan.get("notes", "")
    # <— если пусто, pdf_report сам подставит дефолт
    intake_rows = plan.get("intake", [])
    order_url = plan.get("order_url")

    footer = ("Отчёт носит образовательный характер и не заменяет консультацию врача. "
              "База: сон 7–9 ч, утренний свет, регулярное движение, сбалансированное питание.")

    return build_pdf(
        title=title,
        subtitle=subtitle,
        actions=actions,
        products=products,
        notes=notes,
        footer=footer,
        intake_rows=intake_rows,   # <— прокидываем
        order_url=order_url
    )


@router.callback_query(F.data == "pdf:last")
async def pdf_last_cb(c: CallbackQuery):
    plan = get_last_plan(c.from_user.id)
    if not plan:
        await c.answer("Нет данных для отчёта. Пройдите тест или калькулятор.", show_alert=True)
        return
    pdf_bytes = _compose_pdf(plan)
    filename = f"plan_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    await c.message.answer_document(BufferedInputFile(pdf_bytes, filename=filename), caption="Готово! 📄 Ваш PDF-план.")


@router.message(Command("pdf"))
async def pdf_cmd(m: Message):
    plan = get_last_plan(m.from_user.id)
    if not plan:
        await m.answer("Нет актуального плана. Пройдите тест или калькулятор, чтобы я собрал рекомендации.")
        return
    pdf_bytes = _compose_pdf(plan)
    filename = f"plan_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    await m.answer_document(BufferedInputFile(pdf_bytes, filename=filename), caption="Готово! 📄 Ваш PDF-план.")
