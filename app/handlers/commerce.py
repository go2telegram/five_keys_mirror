"""Commerce command handlers: cart, checkout, coupons and reports."""

from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.db.models import Bundle
from app.db.session import compat_session, session_scope
from app.handlers.admin import _is_admin
from app.services.cart import (
    add_bundle_to_cart,
    add_product_to_cart,
    clear_cart,
    get_cart,
    save_cart,
)
from app.services.checkout import calculate_total_with_coupon, create_order
from app.services.coupons import apply_coupon, fetch_coupon, is_coupon_valid

router = Router(name="commerce")


async def _reply_cart(message: Message, user_id: int) -> None:
    cart = get_cart(user_id)
    if not cart.items:
        await message.answer("🛒 Твоя корзина пока пуста. Добавь продукты из рекомендаций!")
        return
    lines = ["🛒 Корзина:"]
    lines.extend(cart.summary_lines())
    await message.answer("\n".join(lines))


@router.message(Command("cart"))
async def cart_command(message: Message) -> None:
    if not message.from_user:
        return
    await _reply_cart(message, message.from_user.id)


@router.message(Command("cart_add"))
async def cart_add_command(message: Message) -> None:
    if not message.from_user:
        return
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2:
        await message.answer("Используй: /cart_add <product_id>")
        return
    product_id = parts[1].strip()
    if not product_id:
        await message.answer("Нужно указать идентификатор продукта")
        return
    item = add_product_to_cart(message.from_user.id, product_id)
    if not item:
        await message.answer("Не удалось найти продукт. Попробуй выбрать из каталога.")
        return
    await message.answer(f"Добавлено в корзину: {item.title}")


@router.message(Command("cart_clear"))
async def cart_clear_command(message: Message) -> None:
    if not message.from_user:
        return
    clear_cart(message.from_user.id)
    await message.answer("Корзина очищена.")


@router.callback_query(F.data.startswith("cart:add:"))
async def cart_add_callback(callback: CallbackQuery) -> None:
    if not callback.from_user:
        await callback.answer("Недоступно", show_alert=True)
        return
    product_id = (callback.data or "").split(":", 2)[-1]
    item = add_product_to_cart(callback.from_user.id, product_id)
    if not item:
        await callback.answer("Товар не найден", show_alert=True)
        return
    await callback.answer("Добавлено в корзину", show_alert=False)


async def _fetch_bundle(bundle_id: int) -> Bundle | None:
    async with compat_session(session_scope) as session:
        bundle = await session.get(Bundle, bundle_id)
    return bundle


@router.callback_query(F.data.startswith("cart:add_bundle:"))
async def cart_add_bundle(callback: CallbackQuery) -> None:
    if not callback.from_user:
        await callback.answer("Недоступно", show_alert=True)
        return
    parts = (callback.data or "").split(":", 2)
    try:
        bundle_id = int(parts[-1])
    except (TypeError, ValueError):
        await callback.answer("Бандл не найден", show_alert=True)
        return
    bundle = await _fetch_bundle(bundle_id)
    if bundle is None:
        await callback.answer("Бандл не найден", show_alert=True)
        return
    add_bundle_to_cart(
        callback.from_user.id,
        {
            "id": bundle.id,
            "title": bundle.title,
            "price": bundle.price,
        },
    )
    await callback.answer("Бандл добавлен в корзину", show_alert=False)


def _format_coupon_message(result, currency: str) -> str:
    discount = result.discount.quantize(Decimal("0.01"))
    final = result.final_amount.quantize(Decimal("0.01"))
    cur = currency or "RUB"
    return f"Купон применён! Скидка −{discount} {cur}, итог {final} {cur}"


@router.message(Command("coupon"))
async def coupon_command(message: Message) -> None:
    if not message.from_user or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Используй: /coupon PROMO")
        return
    code = parts[1].strip()
    if not code:
        await message.answer("Введи код купона")
        return
    cart = get_cart(message.from_user.id)
    if not cart.items:
        await message.answer("Сначала добавь товары в корзину.")
        return
    async with compat_session(session_scope) as session:
        coupon = await fetch_coupon(session, code)
        if not is_coupon_valid(coupon):
            await message.answer("Купон недействителен или истёк.")
            return
        result = apply_coupon(cart.total, coupon)
    cart.coupon_code = coupon.code
    cart.coupon_meta = {
        "discount": str(result.discount),
        "kind": coupon.kind,
    }
    save_cart(message.from_user.id, cart)
    await message.answer(_format_coupon_message(result, cart.currency))


async def _resolve_coupon(user_id: int, *, session) -> tuple[object | None, object | None]:
    cart = get_cart(user_id)
    if not cart.coupon_code:
        return cart, None
    coupon = await fetch_coupon(session, cart.coupon_code)
    if not is_coupon_valid(coupon):
        return cart, None
    coupon_result = await calculate_total_with_coupon(cart, coupon)
    if coupon_result is not None:
        cart.coupon_meta = {
            "discount": str(coupon_result.discount),
            "kind": coupon.kind,
        }
        save_cart(user_id, cart)
    return cart, coupon_result


@router.message(Command("checkout"))
async def checkout_command(message: Message) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    cart = get_cart(user_id)
    if not cart.items:
        await message.answer("Корзина пуста. Добавь товары перед оформлением заказа.")
        return
    async with compat_session(session_scope) as session:
        cart, coupon_result = await _resolve_coupon(user_id, session=session)
        checkout = await create_order(
            session,
            user_id=user_id,
            cart=cart,
            coupon=coupon_result,
        )
        await session.commit()
    clear_cart(user_id)
    lines = [
        "✅ Заказ оформлен!",
        f"Номер заказа: {checkout.order.id}",
        "",
    ]
    lines.extend(cart.summary_lines())
    if checkout.receipt_path:
        lines.append("")
        lines.append(f"Чек: {checkout.receipt_path}")
    await message.answer("\n".join(lines))


def _format_currency(amount: float) -> str:
    return f"{Decimal(str(amount)).quantize(Decimal('0.01'))}"


async def _orders_report_lines(period: str, *, session) -> list[str]:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1) if period == "day" else now - timedelta(days=7)

    from app.db.models import Order

    stmt = select(func.count(Order.id), func.coalesce(func.sum(Order.amount), 0.0)).where(
        Order.created_at >= since, Order.status == "paid"
    )
    total_orders, total_amount = (await session.execute(stmt)).one()
    return [
        f"Заказы за {period}: {total_orders}",
        f"Выручка: {_format_currency(total_amount)}",
    ]


async def _mrr_report_lines(*, session) -> list[str]:
    from sqlalchemy import func, select

    from app.db.models import CommerceSubscription

    stmt = select(func.count(CommerceSubscription.id), func.coalesce(func.sum(CommerceSubscription.amount), 0.0)).where(
        CommerceSubscription.status == "active"
    )
    total_subs, total_amount = (await session.execute(stmt)).one()
    return [
        f"Активных подписок: {total_subs}",
        f"MRR: {_format_currency(total_amount)}",
    ]


@router.message(Command("orders_report"))
async def orders_report(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    async with compat_session(session_scope) as session:
        day = await _orders_report_lines("day", session=session)
        week = await _orders_report_lines("week", session=session)
    await message.answer("\n".join(["📊 Отчёт по заказам"] + day + week))


@router.message(Command("mrr_report"))
async def mrr_report(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    async with compat_session(session_scope) as session:
        lines = await _mrr_report_lines(session=session)
    await message.answer("\n".join(["💰 MRR"] + lines))
