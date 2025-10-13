from typing import Iterable, Mapping

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.feature_flags import feature_flags
from app.products import PRODUCTS

# ---------- Главное меню ----------


def kb_main(*, user_id: int | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="⚡ Тесты", callback_data="menu:tests")
    kb.button(text="🎯 План (AI)", callback_data="pick:menu")
    kb.button(text="🛍 Каталог", callback_data="catalog:menu")
    kb.button(text="💎 Премиум", callback_data="menu:premium")
    kb.button(text="👤 Профиль", callback_data="profile:open")

    nav_footer = feature_flags.is_enabled("FF_NAV_FOOTER", user_id=user_id)
    kb.button(text="ℹ️ Помощь", callback_data="menu:help")
    if nav_footer:
        kb.button(text="🧭 Навигатор", callback_data="nav:root")

    if nav_footer:
        kb.adjust(2, 2, 2, 1)
    else:
        kb.adjust(2, 2, 2)
    return kb.as_markup()


# ---------- Онбординг ----------


def kb_onboarding_entry(*, user_id: int | None = None) -> InlineKeyboardMarkup:
    """Первый экран /start с основными сценариями."""

    kb = InlineKeyboardBuilder()
    kb.button(text="⚡ Пройти тест энергии", callback_data="onboard:energy")
    kb.button(text="🎯 Подобрать продукты", callback_data="onboard:recommend")
    kb.button(text="🎁 Получить бонус-рекомендации", callback_data="onboard:recommend_full")

    nav_footer = feature_flags.is_enabled("FF_NAV_FOOTER", user_id=user_id)
    if nav_footer:
        kb.button(text="🧭 Навигатор", callback_data="nav:root")
        kb.button(text="ℹ️ Помощь", callback_data="menu:help")
        kb.adjust(1, 1, 1, 2)
    else:
        kb.adjust(1)
    return kb.as_markup()


def kb_recommendation_prompt(*, user_id: int | None = None) -> InlineKeyboardMarkup:
    """Короткая кнопка для быстрого перехода к рекомендациям."""

    kb = InlineKeyboardBuilder()
    kb.button(text="💊 Получить рекомендации", callback_data="pick:menu")

    nav_footer = feature_flags.is_enabled("FF_NAV_FOOTER", user_id=user_id)
    if nav_footer:
        kb.button(text="🧭 Навигатор", callback_data="nav:root")
        kb.button(text="ℹ️ Помощь", callback_data="menu:help")
        kb.adjust(1, 2)
    else:
        kb.adjust(1)
    return kb.as_markup()


def kb_premium_info_actions() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💎 Оформить подписку", callback_data="sub:menu")
    kb.button(text="📘 Что входит", callback_data="/premium_center")
    kb.button(text="⬅️ Назад", callback_data="home:main")
    kb.adjust(1)
    return kb.as_markup()


# ---------- Меню «Все квизы» ----------


def kb_quiz_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    tests = [
        ("⚡ Энергия", "energy"),
        ("😴 Сон", "sleep"),
        ("😰 Стресс", "stress"),
        ("🛡 Иммунитет", "immunity"),
        ("🦠 ЖКТ", "gut"),
    ]
    for title, slug in tests:
        kb.button(
            text=title,
            callback_data=f"quiz:{slug}:nav:next",
        )
    kb.button(text="🧮 Калькуляторы", callback_data="/calculators")
    kb.button(text="⬅️ Назад", callback_data="home:main")
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1)
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
    kb.button(text="⬅️ Назад", callback_data="menu:tests")
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


def kb_products_cta_home(back_cb: str, *, discount_url: str | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    discount = discount_url or settings.velavie_url
    if discount:
        kb.button(text="🔗 Заказать со скидкой", url=discount)
    kb.button(text="⬅️ Назад", callback_data=back_cb)
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1, 2)
    return kb.as_markup()


# ---------- CTA с PDF + консультация ----------


def kb_products_cta_home_pdf(
    back_cb: str, *, discount_url: str | None = None
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    discount = discount_url or settings.velavie_url
    if discount:
        kb.button(text="🔗 Заказать со скидкой", url=discount)
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


def kb_buylist_pdf(
    back_cb: str,  # noqa: ARG001 - legacy parameter
    codes: list[str],
    *,
    links: Mapping[str, str] | None = None,  # noqa: ARG001 - legacy parameter
    discount_url: str | None = None,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    normalized = [code for code in codes if isinstance(code, str) and code]
    if normalized:
        payload = ",".join(dict.fromkeys(normalized))
        kb.button(text="🛒 В корзину", callback_data=f"cart:add_many:{payload}")
    kb.button(text="📄 PDF-план", callback_data="report:last")
    discount = discount_url or settings.velavie_url
    if discount:
        kb.button(text="🎟️ Скидка", url=discount)
    else:
        kb.button(text="🎟️ Скидка", callback_data="reg:open")
    kb.button(text="🏠 Домой", callback_data="home:main")

    kb.adjust(2, 2)
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
    discount_url: str | None = None,
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
        discount = discount_url or settings.velavie_url
        if discount:
            kb.button(text="🔗 Заказать со скидкой", url=discount)
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
