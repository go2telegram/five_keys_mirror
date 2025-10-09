from typing import Iterable, Mapping

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.products import BUY_URLS, PRODUCTS

# ---------- Главное меню ----------


def kb_main() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="⚡ Тесты и диагностика", callback_data="menu:tests")
    kb.button(text="🎯 Персональные рекомендации", callback_data="pick:menu")
    kb.button(text="🛍 Каталог", callback_data="catalog:menu")
    kb.button(text="💎 Премиум-доступ", callback_data="menu:premium")
    kb.button(text="👤 Профиль", callback_data="profile:open")
    kb.button(text="ℹ️ Помощь", callback_data="menu:help")

    kb.adjust(2, 2, 2)
    return kb.as_markup()


# ---------- Онбординг ----------


def kb_onboarding_entry() -> InlineKeyboardMarkup:
    """Первый экран /start с основными сценариями."""

    kb = InlineKeyboardBuilder()
    kb.button(text="⚡ Пройти тест энергии", callback_data="onboard:energy")
    kb.button(text="🎯 Подобрать продукты", callback_data="onboard:recommend")
    kb.button(text="🎁 Получить бонус-рекомендации", callback_data="onboard:recommend_full")
    kb.adjust(1)
    return kb.as_markup()


def kb_recommendation_prompt() -> InlineKeyboardMarkup:
    """Короткая кнопка для быстрого перехода к рекомендациям."""

    kb = InlineKeyboardBuilder()
    kb.button(text="💊 Получить рекомендации", callback_data="pick:menu")
    kb.adjust(1)
    return kb.as_markup()


def kb_premium_info_actions() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💎 Оформить подписку", callback_data="sub:menu")
    kb.button(text="📘 Что входит в Премиум", callback_data="premium:info")
    kb.button(text="⬅️ Назад", callback_data="home:main")
    kb.adjust(1)
    return kb.as_markup()


# ---------- Меню «Все квизы» ----------


def kb_quiz_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⚡ Энергия", callback_data="quiz:energy")
    kb.button(text="🛡 Иммунитет", callback_data="quiz:immunity")
    kb.button(text="🌿 ЖКТ", callback_data="quiz:gut")
    kb.button(text="😴 Сон", callback_data="quiz:sleep")
    kb.button(text="🧠 Стресс", callback_data="quiz:stress")
    kb.button(text="🩸 Дефициты", callback_data="quiz:deficits")
    kb.button(text="🧘 Стресс 2.0", callback_data="quiz:stress2")
    kb.button(text="✨ Кожа и суставы", callback_data="quiz:skin_joint")
    kb.button(text="⬅️ Назад", callback_data="home:main")
    kb.adjust(2, 2, 2, 2, 1)
    return kb.as_markup()


# ---------- Да / Нет ----------


def kb_yes_no(cb_yes: str, cb_no: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data=cb_yes)
    kb.button(text="❌ Нет", callback_data=cb_no)
    kb.adjust(2)
    return kb.as_markup()


def kb_premium_cta() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💎 Узнать про Премиум", callback_data="premium:info")
    kb.adjust(1)
    return kb.as_markup()


# ---------- Назад + Домой ----------


def kb_back_home(back_cb: str | None = None, home_cb: str = "home:main") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=back_cb or home_cb)
    kb.button(text="🏠 Домой", callback_data=home_cb)
    kb.adjust(2)
    return kb.as_markup()


# ---------- Меню калькуляторов ----------


def kb_calc_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="MSD идеальный вес", callback_data="calc:msd")
    kb.button(text="ИМТ", callback_data="calc:bmi")
    kb.button(text="Водный баланс", callback_data="calc:water")
    kb.button(text="Калории (BMR/TDEE)", callback_data="calc:kcal")
    kb.button(text="БЖУ", callback_data="calc:macros")
    kb.button(text="⬅️ Назад", callback_data="home:main")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(2, 2, 1, 2)
    return kb.as_markup()


# ---------- Меню целей ----------


def kb_goal_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⚡ Энергия", callback_data="pick:goal:energy")
    kb.button(text="🛡 Иммунитет", callback_data="pick:goal:immunity")
    kb.button(text="🌿 ЖКТ", callback_data="pick:goal:gut")
    kb.button(text="😴 Сон", callback_data="pick:goal:sleep")
    kb.button(text="✨ Кожа/суставы", callback_data="pick:goal:beauty_joint")
    kb.button(text="⬅️ Назад", callback_data="home:main")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(2, 2, 2)
    return kb.as_markup()


# ---------- CTA без PDF ----------


def kb_products_cta_home(back_cb: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if settings.velavie_url:
        kb.button(text="🔗 Заказать со скидкой", url=settings.velavie_url)
    kb.button(text="⬅️ Назад", callback_data=back_cb)
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 2)
    return kb.as_markup()


# ---------- CTA с PDF + консультация ----------


def kb_products_cta_home_pdf(back_cb: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if settings.velavie_url:
        kb.button(text="🔗 Заказать со скидкой", url=settings.velavie_url)
    kb.button(text="📄 PDF-план", callback_data="report:last")
    kb.button(text="📝 Консультация", callback_data="lead:start")
    kb.button(text="⬅️ Назад", callback_data=back_cb)
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 1, 2)
    return kb.as_markup()


# ---------- Отмена ----------


def kb_cancel_home() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="lead:cancel")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(2)
    return kb.as_markup()


# ---------- Кнопки покупки продуктов ----------


def kb_buylist_pdf(back_cb: str, codes: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code in codes:
        p = PRODUCTS.get(code)
        url = BUY_URLS.get(code)
        if not p or not url:
            continue
        title = p.get("title", code)
        kb.button(text=f"🛒 Купить {title}", url=url)

    kb.button(text="📄 PDF-план", callback_data="report:last")
    if settings.velavie_url:
        kb.button(text="🔗 Заказать со скидкой", url=settings.velavie_url)
    kb.button(text="⬅️ Назад", callback_data=back_cb)
    kb.button(text="🏠 Домой", callback_data="home:main")

    rows = [1] * len(codes)
    kb.adjust(*(rows + [1, 1, 2]))
    return kb.as_markup()


def kb_actions(
    cards: Iterable[Mapping[str, object]],
    back_cb: str | None = None,
    *,
    home_cb: str = "home:main",
    with_pdf: bool = True,
    with_discount: bool = True,
    with_consult: bool = True,
    bundle_action: tuple[str, str] | None = None,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    buy_buttons = 0
    cart_buttons = 0
    for card in cards:
        name = card.get("name") or card.get("code") or "Product"
        url = card.get("order_url")
        if url:
            kb.button(text=f"🛒 Купить {name}", url=str(url))
            buy_buttons += 1
        code = str(card.get("code") or card.get("id") or card.get("name") or "")
        if code:
            kb.button(text="🛒 В корзину", callback_data=f"cart:add:{code}")
            cart_buttons += 1

    if with_pdf:
        kb.button(text="📄 PDF-план", callback_data="report:last")
    if with_discount:
        if settings.velavie_url:
            kb.button(text="🔗 Заказать со скидкой", url=settings.velavie_url)
        else:
            kb.button(text="🔗 Заказать со скидкой", callback_data="reg:open")
    if with_consult:
        kb.button(text="📝 Консультация", callback_data="lead:start")
    if bundle_action:
        text, callback = bundle_action
        kb.button(text=text, callback_data=callback)

    kb.button(text="⬅️ Назад", callback_data=back_cb or home_cb)
    kb.button(text="🏠 Домой", callback_data=home_cb)

    layout = [1] * buy_buttons
    tail = [1] * cart_buttons
    if with_pdf:
        tail.append(1)
    if with_discount:
        tail.append(1)
    if with_consult:
        tail.append(1)
    if bundle_action:
        tail.append(1)
    tail.extend([2])
    kb.adjust(*(layout + tail))
    return kb.as_markup()


# Backwards compatibility for older imports
kb_card_actions = kb_actions
