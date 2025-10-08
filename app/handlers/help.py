"""Inline FAQ and help command handlers."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.faq import get_faq_item, load_faq

router = Router(name="help")

_HELP_INTRO = (
    "Чем могу помочь? Ниже — ответы на популярные вопросы. "
    "Если не нашли нужный пункт, оставьте заявку — эксперт свяжется."
)


def _build_faq_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for item in load_faq():
        builder.button(text=f"❓ {item['question']}", callback_data=f"help:item:{item['id']}")
    builder.button(text="📝 Консультация", callback_data="lead:start")
    builder.button(text="🏠 Домой", callback_data="home:main")
    builder.adjust(1)
    return builder


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    kb = _build_faq_keyboard().as_markup()
    await message.answer(_HELP_INTRO, reply_markup=kb)


@router.callback_query(F.data == "help:open")
async def help_open(c: CallbackQuery) -> None:
    await c.answer()
    kb = _build_faq_keyboard().as_markup()
    try:
        await c.message.edit_text(_HELP_INTRO, reply_markup=kb)
    except Exception:
        await c.message.answer(_HELP_INTRO, reply_markup=kb)


@router.callback_query(F.data.startswith("help:item:"))
async def help_item(c: CallbackQuery) -> None:
    item_id = c.data.split(":", 2)[-1]
    item = get_faq_item(item_id)
    if not item:
        await c.answer("Раздел скоро обновится", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ К вопросам", callback_data="help:open")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1)
    text = f"<b>{item['question']}</b>\n\n{item['answer']}"
    try:
        await c.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await c.message.answer(text, reply_markup=kb.as_markup())
    finally:
        await c.answer()
