from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.keyboards import kb_back_home
from app.i18n import resolve_locale
from app.link_manager import get_register_link
from app.texts import Texts
from app.utils import safe_edit_text

router = Router()


@router.callback_query(F.data == "reg:open")
async def reg_open(c: CallbackQuery):
    url = await get_register_link()
    await c.answer()
    texts = Texts(resolve_locale(getattr(c.from_user, "language_code", None)))
    if not url:
        await safe_edit_text(c.message, texts.common.registration_unavailable(), kb_back_home())
        return

    await safe_edit_text(
        c.message,
        texts.common.registration_prompt(),
        build_reg_markup(url, texts),
    )


def build_reg_markup(url: str | None = None, texts: Texts | None = None):
    resolved_url = url or settings.VELAVIE_URL
    kb = InlineKeyboardBuilder()
    if texts is None:
        texts = Texts(resolve_locale(None))
    kb.button(text=texts.common.registration_button(), url=resolved_url)
    for row in kb_back_home().inline_keyboard:
        kb.row(*row)
    return kb.as_markup()
