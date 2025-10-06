"""Handlers for catalog commands and callbacks."""

from __future__ import annotations

import math
from time import monotonic
from typing import List, Sequence

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.catalog.loader import CatalogData, Category, Product, get_catalog
from app.config import settings
from app.metrics.product import (
    log_catalog_search,
    log_product_click_buy,
    log_product_view,
)

router = Router(name="catalog")

_CATEGORIES_PAGE = 6
_PRODUCTS_PAGE = 6
_THROTTLE: dict[tuple[int, str], float] = {}
_THROTTLE_LIMITS = {
    "catalog": 1.5,
    "category": 1.0,
    "product": 0.5,
    "search": 2.0,
}


class CatalogCallback(CallbackData, prefix="catalog"):
    action: str
    category: str | None = None
    item: str | None = None
    page: int = 0


def _allow(user_id: int, key: str) -> bool:
    limit = _THROTTLE_LIMITS.get(key, 1.0)
    now = monotonic()
    prev = _THROTTLE.get((user_id, key))
    if prev is not None and now - prev < limit:
        return False
    _THROTTLE[(user_id, key)] = now
    return True


def _build_categories_keyboard(data: CatalogData, page: int) -> InlineKeyboardMarkup:
    categories = list(data.iter_categories())
    if not categories:
        return InlineKeyboardMarkup(inline_keyboard=[])

    total_pages = max(1, math.ceil(len(categories) / _CATEGORIES_PAGE))
    page = max(0, min(page, total_pages - 1))
    start = page * _CATEGORIES_PAGE
    current = categories[start : start + _CATEGORIES_PAGE]

    builder = InlineKeyboardBuilder()
    for category in current:
        builder.button(
            text=category.title,
            callback_data=CatalogCallback(action="category", category=category.id, page=0).pack(),
        )
    if current:
        builder.adjust(*(1 for _ in current))

    nav_buttons: List[InlineKeyboardButton] = []
    if total_pages > 1 and page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=CatalogCallback(action="categories", page=page - 1).pack(),
            )
        )
    if total_pages > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}",
                callback_data=CatalogCallback(action="noop", page=page).pack(),
            )
        )
    if total_pages > 1 and page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="Вперёд ➡️",
                callback_data=CatalogCallback(action="categories", page=page + 1).pack(),
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(InlineKeyboardButton(text="🏠 Домой", callback_data="home"))
    return builder.as_markup()


def _build_category_keyboard(
    data: CatalogData, category: Category, page: int
) -> InlineKeyboardMarkup:
    products = data.category_products.get(category.id, [])
    total_pages = max(1, math.ceil(len(products) / _PRODUCTS_PAGE))
    page = max(0, min(page, total_pages - 1))
    start = page * _PRODUCTS_PAGE
    current = products[start : start + _PRODUCTS_PAGE]

    builder = InlineKeyboardBuilder()
    for product in current:
        builder.button(
            text=product.name,
            callback_data=CatalogCallback(
                action="product", category=category.id, item=product.id, page=page
            ).pack(),
        )
    if current:
        builder.adjust(*(1 for _ in current))

    nav_buttons: List[InlineKeyboardButton] = []
    if total_pages > 1 and page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=CatalogCallback(
                    action="category", category=category.id, page=page - 1
                ).pack(),
            )
        )
    if total_pages > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}",
                callback_data=CatalogCallback(
                    action="noop", category=category.id, page=page
                ).pack(),
            )
        )
    if total_pages > 1 and page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="Вперёд ➡️",
                callback_data=CatalogCallback(
                    action="category", category=category.id, page=page + 1
                ).pack(),
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(
            text="⬅️ Все категории",
            callback_data=CatalogCallback(action="categories", page=0).pack(),
        )
    )
    builder.row(InlineKeyboardButton(text="🏠 Домой", callback_data="home"))
    return builder.as_markup()


def _category_text(category: Category, products: Sequence[Product]) -> str:
    lines = [f"<b>{category.title}</b>"]
    if category.description:
        lines.append(category.description)
    if products:
        bullet_lines = [
            f"{idx}. <b>{product.name}</b> — {product.short}" for idx, product in enumerate(products, 1)
        ]
        lines.append("\n".join(bullet_lines))
    else:
        lines.append("Товары появятся скоро.")
    lines.append("Выберите продукт, чтобы посмотреть карточку.")
    return "\n\n".join(lines)


def _categories_text(data: CatalogData) -> str:
    lines = ["<b>Каталог продуктов</b>"]
    for category in data.iter_categories():
        preview = f" — {category.description}" if category.description else ""
        lines.append(f"• {category.title}{preview}")
    lines.append("\nВыберите категорию, чтобы посмотреть товары.")
    return "\n".join(lines)


def _search_products(data: CatalogData, query: str) -> List[Product]:
    q = query.lower().strip()
    if not q:
        return []
    matched: List[Product] = []
    for product in data.products.values():
        haystacks = [product.name, product.short, " ".join(product.tags)]
        if any(q in (hay or "").lower() for hay in haystacks):
            matched.append(product)
    matched.sort(key=lambda item: item.name)
    return matched


def _product_caption(product: Product) -> str:
    lines = [f"<b>{product.name}</b>"]
    lines.append(product.description)
    if product.tags:
        tags = ", ".join(f"#{tag}" for tag in product.tags)
        lines.append("")
        lines.append(tags)
    return "\n".join(lines)


@router.message(Command("catalog"))
async def cmd_catalog(message: Message) -> None:
    if not settings.ENABLE_CATALOG_UI:
        return
    if not message.from_user:
        return
    if not _allow(message.from_user.id, "catalog"):
        await message.answer("Подождите пару секунд перед следующим запросом.")
        return
    data = get_catalog()
    await message.answer(
        _categories_text(data), reply_markup=_build_categories_keyboard(data, page=0)
    )


@router.message(Command("product"))
async def cmd_product(message: Message, command: CommandObject) -> None:
    if not settings.ENABLE_CATALOG_UI:
        return
    if not message.from_user:
        return
    args = (command.args or "").strip().split()
    if not args:
        await message.answer("Укажите идентификатор продукта: /product T8_EXTRA")
        return
    product_id = args[0]
    data = get_catalog()
    product = data.products.get(product_id)
    if not product:
        await message.answer("Не нашёл такой продукт. Проверьте идентификатор.")
        return
    categories = data.product_categories.get(product_id) or []
    back_category = categories[0] if categories else None
    await message.answer_photo(
        product.image,
        caption=_product_caption(product),
        reply_markup=_product_keyboard(product, back_category, page=0),
    )
    log_product_view(message.from_user.id, product.id)


def _product_keyboard(product: Product, category_id: str | None, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🛒 Купить",
        callback_data=CatalogCallback(action="buy", item=product.id).pack(),
    )
    if category_id:
        builder.button(
            text="⬅️ Назад",
            callback_data=CatalogCallback(
                action="category", category=category_id, page=page
            ).pack(),
        )
    builder.button(
        text="📂 Категории",
        callback_data=CatalogCallback(action="categories", page=0).pack(),
    )
    rows = [1]
    if category_id:
        rows.append(2)
    else:
        rows.append(1)
    builder.adjust(*rows)
    return builder.as_markup()


@router.message(Command("find"))
async def cmd_find(message: Message, command: CommandObject) -> None:
    if not settings.ENABLE_CATALOG_UI:
        return
    if not message.from_user:
        return
    if not _allow(message.from_user.id, "search"):
        await message.answer("Подождите немного и повторите поиск.")
        return
    query = (command.args or "").strip()
    if not query:
        await message.answer("Введите запрос: /find омега")
        return
    data = get_catalog()
    results = _search_products(data, query)
    log_catalog_search(message.from_user.id, query, [item.id for item in results])
    if not results:
        await message.answer("Ничего не нашлось. Попробуйте другую фразу.")
        return

    limited = results[:10]
    lines = [f"🔍 Результаты по запросу «{query}»:"]
    for idx, product in enumerate(limited, 1):
        lines.append(f"{idx}. <b>{product.name}</b> — {product.short}")
    text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    for product in limited:
        categories = data.product_categories.get(product.id) or []
        back_category = categories[0] if categories else None
        builder.button(
            text=product.name,
            callback_data=CatalogCallback(
                action="product", category=back_category, item=product.id, page=0
            ).pack(),
        )
    builder.adjust(*(1 for _ in limited) or [1])
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Категории", callback_data=CatalogCallback(action="categories", page=0).pack()
        )
    )

    await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(CatalogCallback.filter(F.action == "categories"))
async def cb_categories(callback: CallbackQuery, callback_data: CatalogCallback) -> None:
    if not settings.ENABLE_CATALOG_UI:
        await callback.answer()
        return
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id if callback.from_user else None
    if user_id and not _allow(user_id, "catalog"):
        await callback.answer("Чуть позже можно снова открыть список.", show_alert=True)
        return
    data = get_catalog()
    page = callback_data.page
    await callback.message.edit_text(
        _categories_text(data), reply_markup=_build_categories_keyboard(data, page=page)
    )
    await callback.answer()


@router.callback_query(CatalogCallback.filter(F.action == "category"))
async def cb_category(callback: CallbackQuery, callback_data: CatalogCallback) -> None:
    if not settings.ENABLE_CATALOG_UI:
        await callback.answer()
        return
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id if callback.from_user else None
    if user_id and not _allow(user_id, "category"):
        await callback.answer("Не так быстро, пожалуйста.", show_alert=True)
        return
    data = get_catalog()
    category_id = callback_data.category
    if not category_id:
        await callback.answer()
        return
    category = data.categories.get(category_id)
    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    products = data.category_products.get(category.id, [])
    page = max(0, min(callback_data.page, max(0, math.ceil(len(products) / _PRODUCTS_PAGE) - 1)))
    await callback.message.edit_text(
        _category_text(category, products[page * _PRODUCTS_PAGE : page * _PRODUCTS_PAGE + _PRODUCTS_PAGE]),
        reply_markup=_build_category_keyboard(data, category, page=page),
    )
    await callback.answer()


@router.callback_query(CatalogCallback.filter(F.action == "product"))
async def cb_product(callback: CallbackQuery, callback_data: CatalogCallback) -> None:
    if not settings.ENABLE_CATALOG_UI:
        await callback.answer()
        return
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id if callback.from_user else None
    if user_id and not _allow(user_id, "product"):
        await callback.answer("Нажимайте не так часто.", show_alert=True)
        return
    data = get_catalog()
    product_id = callback_data.item
    if not product_id:
        await callback.answer()
        return
    product = data.products.get(product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    category_id = callback_data.category
    await callback.message.answer_photo(
        product.image,
        caption=_product_caption(product),
        reply_markup=_product_keyboard(product, category_id, page=callback_data.page),
    )
    if user_id:
        log_product_view(user_id, product.id)
    await callback.answer()


@router.callback_query(CatalogCallback.filter(F.action == "buy"))
async def cb_buy(callback: CallbackQuery, callback_data: CatalogCallback) -> None:
    if not settings.ENABLE_CATALOG_UI:
        await callback.answer()
        return
    product_id = callback_data.item
    if callback.from_user and product_id:
        log_product_click_buy(callback.from_user.id, product_id)
    data = get_catalog()
    product = data.products.get(product_id) if product_id else None
    if product:
        await callback.answer(url=str(product.buy_url))
    else:
        await callback.answer("Ссылка временно недоступна", show_alert=True)


@router.callback_query(CatalogCallback.filter(F.action == "noop"))
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()
