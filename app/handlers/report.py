# app/handlers/report.py
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.db.session import compat_session, session_scope
from app.keyboards import kb_back_home
from app.pdf_report import build_pdf, ensure_reportlab
from app.repo import events as events_repo
from app.storage import commit_safely, get_last_plan

router = Router()

log = logging.getLogger(__name__)


def _clean_lines(lines: list[str]) -> list[str]:
    out = []
    for s in lines:
        s = s.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "").replace("&nbsp;", " ")
        out.append(s)
    return out


def _compose_pdf(plan: dict) -> bytes | None:
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

    footer = (
        "Отчёт носит образовательный характер и не заменяет консультацию врача. "
        "База: сон 7–9 ч, утренний свет, регулярное движение, сбалансированное питание."
    )

    if not ensure_reportlab():
        log.warning("PDF disabled (reportlab missing)")
        return None

    return build_pdf(
        title=title,
        subtitle=subtitle,
        actions=actions,
        products=products,
        notes=notes,
        footer=footer,
        intake_rows=intake_rows,  # <— прокидываем
        order_url=order_url,
        recommended_products=list(plan.get("products", [])),
        context=plan.get("context"),
    )


@router.callback_query(F.data.in_({"report:last", "pdf:last"}))
async def pdf_last_cb(c: CallbackQuery):
    async with compat_session(session_scope) as session:
        plan = await get_last_plan(session, c.from_user.id)
        if plan:
            await events_repo.log(
                session,
                c.from_user.id,
                "pdf_export",
                {"context": plan.get("context"), "title": plan.get("title")},
            )
            await commit_safely(session)
    if not plan:
        await c.answer("Нет данных для отчёта. Пройдите тест или калькулятор.", show_alert=True)
        await c.message.answer(
            "Сначала пройдите квиз или калькулятор, чтобы я собрал персональный план.",
            reply_markup=kb_back_home(),
        )
        return
    await c.answer()
    pdf_bytes = _compose_pdf(plan)
    if not pdf_bytes:
        await c.message.answer(
            "Генератор PDF недоступен на этой сборке.",
            reply_markup=kb_back_home(),
        )
        return
    filename = f"plan_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    await c.message.answer_document(BufferedInputFile(pdf_bytes, filename=filename), caption="Готово! 📄 Ваш PDF-план.")


@router.message(Command("pdf"))
async def pdf_cmd(m: Message):
    async with compat_session(session_scope) as session:
        plan = await get_last_plan(session, m.from_user.id)
        if plan:
            await events_repo.log(
                session,
                m.from_user.id,
                "pdf_export",
                {"context": plan.get("context"), "title": plan.get("title")},
            )
            await commit_safely(session)
    if not plan:
        await m.answer("Нет актуального плана. Пройдите тест или калькулятор, чтобы я собрал рекомендации.")
        return
    pdf_bytes = _compose_pdf(plan)
    if not pdf_bytes:
        await m.answer("Генератор PDF недоступен на этой сборке.")
        return
    filename = f"plan_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    await m.answer_document(BufferedInputFile(pdf_bytes, filename=filename), caption="Готово! 📄 Ваш PDF-план.")
