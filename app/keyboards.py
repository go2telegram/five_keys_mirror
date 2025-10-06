from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup
from app.config import settings
from app.catalog import PRODUCTS, get_buy_url
from app.catalog.analytics import normalize_campaign

# ---------- Главное меню ----------


def kb_main() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="🗂 Все квизы", callback_data="quiz:menu")
    kb.button(text="🧭 Навигатор", callback_data="nav:root")
    kb.button(text="📐 Калькуляторы", callback_data="calc:menu")
    kb.button(text="📝 Консультация", callback_data="lead:start")
    kb.button(text="💊 Подбор продуктов", callback_data="pick:menu")
    kb.button(text="🎁 Регистрация со скидкой", callback_data="reg:open")

    # Новые пункты
    kb.button(text="💎 Подписка", callback_data="sub:menu")
    kb.button(text="🔓 Premium", callback_data="premium:menu")
    kb.button(text="👥 Пригласить друга", callback_data="ref:menu")

    # Раскладка
    kb.adjust(1, 2, 1, 1, 1, 3)
    return kb.as_markup()

# ---------- Меню «Все квизы» ----------


def kb_quiz_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⚡ Энергия", callback_data="quiz:energy")
    kb.button(text="🛡 Иммунитет", callback_data="quiz:immunity")
    kb.button(text="🌿 ЖКТ", callback_data="quiz:gut")
    kb.button(text="😴 Сон", callback_data="quiz:sleep")
    kb.button(text="🧠 Стресс", callback_data="quiz:stress")
    kb.button(text="⬅️ Назад", callback_data="home")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()

# ---------- Да / Нет ----------


def kb_yes_no(cb_yes: str, cb_no: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data=cb_yes)
    kb.button(text="❌ Нет", callback_data=cb_no)
    kb.adjust(2)
    return kb.as_markup()

# ---------- Назад + Домой ----------


def kb_back_home(back_cb: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=back_cb)
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(2)
    return kb.as_markup()

# ---------- Меню калькуляторов ----------


def kb_calc_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="MSD идеальный вес", callback_data="calc:msd")
    kb.button(text="ИМТ", callback_data="calc:bmi")
    kb.button(text="⬅️ Назад", callback_data="home")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 1, 2)
    return kb.as_markup()

# ---------- Меню целей ----------


def kb_goal_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⚡ Энергия", callback_data="pick:goal:energy")
    kb.button(text="🛡 Иммунитет", callback_data="pick:goal:immunity")
    kb.button(text="🌿 ЖКТ", callback_data="pick:goal:gut")
    kb.button(text="😴 Сон", callback_data="pick:goal:sleep")
    kb.button(text="✨ Кожа/суставы", callback_data="pick:goal:beauty_joint")
    kb.button(text="⬅️ Назад", callback_data="home")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(2, 2, 2)
    return kb.as_markup()

# ---------- CTA без PDF ----------


def kb_products_cta_home(back_cb: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if settings.VILAVI_REF_LINK_DISCOUNT:
        kb.button(text="🔗 Заказать со скидкой",
                  url=settings.VILAVI_REF_LINK_DISCOUNT)
    kb.button(text="⬅️ Назад", callback_data=back_cb)
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 2)
    return kb.as_markup()

# ---------- CTA с PDF + консультация ----------


def kb_products_cta_home_pdf(back_cb: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if settings.VILAVI_REF_LINK_DISCOUNT:
        kb.button(text="🔗 Заказать со скидкой",
                  url=settings.VILAVI_REF_LINK_DISCOUNT)
    kb.button(text="📄 PDF-план", callback_data="pdf:last")
    kb.button(text="📝 Консультация", callback_data="lead:start")
    kb.button(text="⬅️ Назад", callback_data=back_cb)
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 1, 2)
    return kb.as_markup()

# ---------- Отмена ----------


def kb_cancel_home() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="lead:cancel")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(2)
    return kb.as_markup()

# ---------- Кнопки покупки продуктов ----------


def kb_buylist_pdf(back_cb: str, codes: list[str], campaign: str | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    campaign_slug = normalize_campaign(campaign or "general")
    count = 0
    for code in codes:
        p = PRODUCTS.get(code)
        url = get_buy_url(code)
        if not p or not url:
            continue
        title = p.get("title", code)
        kb.button(
            text=f"🛒 Купить {title}",
            callback_data=f"catalog:buy:{code}:{campaign_slug}",
        )
        count += 1

    kb.button(text="📄 PDF-план", callback_data="pdf:last")
    if settings.VILAVI_REF_LINK_DISCOUNT:
        kb.button(text="🔗 Заказать со скидкой",
                  url=settings.VILAVI_REF_LINK_DISCOUNT)
    kb.button(text="⬅️ Назад", callback_data=back_cb)
    kb.button(text="🏠 Домой", callback_data="home")

    rows = [1] * count
    kb.adjust(*(rows + [1, 1, 2]))
    return kb.as_markup()
