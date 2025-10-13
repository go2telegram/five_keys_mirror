# app/handlers/lead.py
import re
from contextlib import suppress

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import settings
from app.db.session import compat_session, session_scope
from app.keyboards import kb_cancel_home, kb_main
from app.repo import events as events_repo, leads as leads_repo, users as users_repo
from app.storage import commit_safely

router = Router()

PHONE_RE = re.compile(r"^\+?\d[\d\-\s\(\)]{6,}$")


class LeadForm(StatesGroup):
    name = State()
    phone = State()
    comment = State()


# старт из меню/рекомендаций


@router.callback_query(F.data == "lead:start")
async def lead_start(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.set_state(LeadForm.name)
    await c.message.answer("Как к вам обращаться? (имя)", reply_markup=kb_cancel_home())


@router.message(Command("consult"))
async def lead_cmd(m: Message, state: FSMContext):
    await state.set_state(LeadForm.name)
    await m.answer("Как к вам обращаться? (имя)", reply_markup=kb_cancel_home())


@router.callback_query(F.data == "lead:cancel")
async def lead_cancel_cb(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.clear()
    cancel_text = "Заявка отменена. Если понадобится — нажмите 📝 Консультация."
    await c.message.answer(
        cancel_text,
        reply_markup=kb_main(user_id=getattr(c.from_user, "id", None)),
    )


@router.message(LeadForm.name)
async def lead_name(m: Message, state: FSMContext):
    name = m.text.strip()
    if len(name) < 2:
        await m.answer("Введите, пожалуйста, корректное имя.", reply_markup=kb_cancel_home())
        return
    await state.update_data(name=name)
    await state.set_state(LeadForm.phone)
    await m.answer("Телефон для связи (с кодом страны, например +7...)")


@router.message(LeadForm.phone)
async def lead_phone(m: Message, state: FSMContext):
    phone = m.text.strip()
    if not PHONE_RE.match(phone):
        error_text = (
            "Похоже, номер в необычном формате. Введите ещё раз (пример: +7 999 123-45-67)."
        )
        await m.answer(error_text)
        return
    await state.update_data(phone=phone)
    await state.set_state(LeadForm.comment)
    prompt_comment = "Коротко: что хотите обсудить? (можно пропустить — напишите «-»)."
    await m.answer(prompt_comment)


@router.message(LeadForm.comment)
async def lead_done(m: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    name = data.get("name")
    phone = data.get("phone")
    comment = m.text.strip()
    if comment == "-":
        comment = ""

    username = m.from_user.username

    async with compat_session(session_scope) as session:
        await users_repo.get_or_create_user(session, m.from_user.id, username)
        lead = await leads_repo.add(
            session,
            user_id=m.from_user.id,
            username=username,
            name=name,
            phone=phone,
            comment=comment,
        )
        await events_repo.log(
            session,
            m.from_user.id,
            "lead_created",
            {
                "lead_id": lead.id,
                "name": name,
            },
        )
        await commit_safely(session)

    # уведомление администратору/в чат
    admin_chat = settings.LEADS_CHAT_ID or settings.ADMIN_ID
    text_admin = (
        "🆕 Заявка на консультацию\n"
        f"Имя: {name}\n"
        f"Телефон: {phone}\n"
        f"Комментарий: {comment or '(пусто)'}\n"
        f"Профиль: @{m.from_user.username if m.from_user.username else m.from_user.id}"
    )
    with suppress(Exception):
        await m.bot.send_message(admin_chat, text_admin)

    thanks_text = "Спасибо! Я передал заявку. Мы свяжемся с вами в ближайшее время. 🙌"
    await m.answer(
        thanks_text,
        reply_markup=kb_main(user_id=getattr(m.from_user, "id", None)),
    )
