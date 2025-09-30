# app/handlers/lead.py
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import settings
from app.db.session import session_scope
from app.keyboards import kb_cancel_home, kb_main
from app.repo import events as events_repo
from app.repo import leads as leads_repo
from app.repo import users as users_repo

router = Router()

PHONE_RE = re.compile(r"^\+?\d[\d\-\s\(\)]{6,}$")


class LeadForm(StatesGroup):
    name = State()
    phone = State()
    comment = State()

# старт из меню/рекомендаций


@router.callback_query(F.data == "lead:start")
async def lead_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(LeadForm.name)
    await c.message.answer("Как к вам обращаться? (имя)", reply_markup=kb_cancel_home())


@router.message(Command("consult"))
async def lead_cmd(m: Message, state: FSMContext):
    await state.set_state(LeadForm.name)
    await m.answer("Как к вам обращаться? (имя)", reply_markup=kb_cancel_home())


@router.callback_query(F.data == "lead:cancel")
async def lead_cancel_cb(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.answer("Заявка отменена. Если понадобится — нажмите 📝 Консультация.", reply_markup=kb_main())


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
        await m.answer("Похоже, номер в необычном формате. Введите ещё раз (пример: +7 999 123-45-67).")
        return
    await state.update_data(phone=phone)
    await state.set_state(LeadForm.comment)
    await m.answer("Коротко: что хотите обсудить? (можно пропустить — напишите «-»).")


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

    async with session_scope() as session:
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
        await session.commit()

    # уведомление администратору/в чат
    admin_chat = settings.LEADS_CHAT_ID or settings.ADMIN_ID
    text_admin = (
        "🆕 Заявка на консультацию\n"
        f"Имя: {name}\n"
        f"Телефон: {phone}\n"
        f"Комментарий: {comment or '(пусто)'}\n"
        f"Профиль: @{m.from_user.username if m.from_user.username else m.from_user.id}"
    )
    try:
        from aiogram import Bot
        # получаем bot через мидлварь? проще — попросим юзера передать через контекст нельзя; используем message.bot
        await m.bot.send_message(admin_chat, text_admin)
    except Exception:
        pass

    await m.answer("Спасибо! Я передал заявку. Мы свяжемся с вами в ближайшее время. 🙌", reply_markup=kb_main())
