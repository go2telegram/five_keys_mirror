"""Admin commands for bulk managing product and registration links."""

from __future__ import annotations

import io
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.cache import clear_cache
from app.catalog.loader import load_catalog
from app.handlers.admin import admin_only
from app.links.importer import ImportResult, LinkRecord, analyze_payload, parse_payload
from app.links.service import get_register_url
from app.links.storage import LinkSnapshot, export_csv, export_json, load_snapshot, save_snapshot
from app.links.verification import schedule_verification
from app.storage import session_get, session_set

router = Router(name="link_manager")

_SESSION_KEY = "link_manager"
_STATE_TTL = 1800


def _get_state(user_id: int) -> dict[str, Any]:
    if not user_id:
        return {}
    data = session_get(user_id) or {}
    state = data.get(_SESSION_KEY) or {}
    return dict(state)


def _save_state(user_id: int, state: dict[str, Any]) -> None:
    if not user_id:
        return
    data = session_get(user_id) or {}
    if state:
        data[_SESSION_KEY] = state
    elif _SESSION_KEY in data:
        data.pop(_SESSION_KEY, None)
    session_set(user_id, data, ttl=_STATE_TTL)


def _set_mode(user_id: int, mode: str | None) -> None:
    state = _get_state(user_id)
    if mode is None:
        state.pop("mode", None)
    else:
        state["mode"] = mode
    _save_state(user_id, state)


def _store_pending(user_id: int, result: ImportResult) -> None:
    state = _get_state(user_id)
    if result.can_apply:
        verify: list[dict[str, str]] = []
        if result.register_url:
            verify.append({"type": "register", "id": "", "url": result.register_url})
        for pid, url in sorted(result.product_links.items()):
            verify.append({"type": "product", "id": pid, "url": url})
        state["pending"] = {
            "register_url": result.register_url,
            "product_links": dict(result.product_links),
            "verify": verify,
        }
    else:
        state.pop("pending", None)
    _save_state(user_id, state)


def _pop_pending(user_id: int) -> dict[str, Any] | None:
    state = _get_state(user_id)
    pending = state.pop("pending", None)
    _save_state(user_id, state)
    return pending


def _is_waiting_file(user_id: int) -> bool:
    state = _get_state(user_id)
    return state.get("mode") == "await_file"


def _format_overview() -> tuple[str, InlineKeyboardBuilder]:
    snapshot = load_snapshot()
    total_products = len(load_catalog()["products"])
    register = get_register_url() or "—"
    configured = len(snapshot.products)
    missing = max(0, total_products - configured)

    lines = [
        "🔗 <b>Link Manager</b>",
        f"Регистрация: {register}",
        f"Продукты: {configured}/{total_products}",
    ]
    if missing:
        lines.append(f"⚠️ Не хватает ссылок для {missing} продуктов — импортируйте JSON/CSV.")
    lines.append("\nКоманды:\n• /export_links — выгрузка JSON и CSV\n• /import_links — начать импорт")

    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Импорт JSON/CSV", callback_data="links:import")
    kb.adjust(1)
    return "\n".join(lines), kb


def _format_report(result: ImportResult) -> str:
    lines = [
        "📥 <b>Импорт ссылок — проверка</b>",
        f"Всего записей: {result.total}",
        f"✅ Валидных: {result.valid}",
        f"📦 Продукты: {result.valid_products}/{result.expected_products}",
    ]
    register = result.register_url or "—"
    lines.append(f"🔗 Регистрация: {register}")

    if result.invalid_url:
        preview = ", ".join(record.id or record.type for record in result.invalid_url[:5])
        suffix = "…" if len(result.invalid_url) > 5 else ""
        lines.append(f"⚠️ Некорректные URL: {len(result.invalid_url)} ({preview}{suffix})")
    if result.unknown_ids:
        preview = ", ".join(result.unknown_ids[:5])
        suffix = "…" if len(result.unknown_ids) > 5 else ""
        lines.append(f"⚠️ Неизвестные id: {len(result.unknown_ids)} ({preview}{suffix})")
    if result.errors:
        lines.append(f"⚠️ Ошибок: {len(result.errors)}")

    if result.can_apply:
        lines.append("\nНажмите «Применить», чтобы обновить ссылки.")
    else:
        lines.append("\nИсправьте предупреждения и попробуйте ещё раз.")
    return "\n".join(lines)


def _build_apply_keyboard(result: ImportResult) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    if result.can_apply:
        kb.button(text="✅ Применить", callback_data="links:apply")
    kb.button(text="⬅️ Готово", callback_data="links:done")
    kb.adjust(1)
    return kb


@router.message(Command("links"))
@admin_only
async def links_overview(message: Message) -> None:
    text, kb = _format_overview()
    await message.answer(text, reply_markup=kb.as_markup())


@router.message(Command("export_links"))
@admin_only
async def export_links(message: Message) -> None:
    snapshot = load_snapshot()
    json_bytes = export_json(snapshot)
    csv_bytes = export_csv(snapshot)
    await message.answer_document(
        BufferedInputFile(json_bytes, filename="links.json"),
        caption="📤 Экспорт ссылок (JSON)",
    )
    await message.answer_document(
        BufferedInputFile(csv_bytes, filename="links.csv"),
        caption="📤 Экспорт ссылок (CSV)",
    )


@router.message(Command("import_links"))
@admin_only
async def import_links_command(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    _set_mode(user_id, "await_file")
    await message.answer("Пришлите JSON или CSV файл со ссылками. После проверки появится кнопка «Применить».")


@router.callback_query(F.data == "links:import")
@admin_only
async def import_links_callback(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    _set_mode(user_id, "await_file")
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Пришлите JSON или CSV файл со ссылками. После проверки появится кнопка «Применить»."
        )


async def _process_payload(message: Message, data: bytes | str, filename: str | None = None) -> None:
    try:
        records = parse_payload(data, filename=filename)
    except ValueError as exc:
        await message.answer(f"❌ Не удалось прочитать файл: {exc}")
        return

    if not records:
        await message.answer("❌ Файл не содержит подходящих записей.")
        return

    result = analyze_payload(records)
    user_id = message.from_user.id if message.from_user else 0
    report = _format_report(result)
    kb = _build_apply_keyboard(result)
    _store_pending(user_id, result)
    _set_mode(user_id, None)
    await message.answer(report, reply_markup=kb.as_markup())


@router.message(F.document)
@admin_only
async def handle_import_document(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    if not _is_waiting_file(user_id):
        return
    document = message.document
    if document is None:
        await message.answer("❌ Не удалось получить файл.")
        return
    buf = io.BytesIO()
    await message.bot.download(document, destination=buf)
    data = buf.getvalue()
    await _process_payload(message, data, filename=document.file_name)


@router.message(F.text)
@admin_only
async def handle_import_text(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    if not _is_waiting_file(user_id):
        return
    text = message.text or ""
    await _process_payload(message, text)


@router.callback_query(F.data == "links:apply")
@admin_only
async def apply_links(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    pending = _pop_pending(user_id)
    if pending is None:
        await callback.answer("Нет данных для применения", show_alert=True)
        return

    register_url = pending.get("register_url")
    product_links = pending.get("product_links", {})
    snapshot = LinkSnapshot(register_url=register_url, products=dict(product_links))
    save_snapshot(snapshot)

    load_catalog(refresh=True)
    await clear_cache()

    await callback.answer("Ссылки обновлены", show_alert=False)
    if callback.message:
        text, kb = _format_overview()
        await callback.message.answer("✅ Импорт применён.")
        await callback.message.answer(text, reply_markup=kb.as_markup())

    verify_records = [
        LinkRecord(type=item.get("type", ""), id=item.get("id", ""), url=item.get("url", ""))
        for item in pending.get("verify", [])
    ]
    schedule_verification(callback.bot, callback.from_user.id, verify_records)


@router.callback_query(F.data == "links:done")
@admin_only
async def finish_links(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    _set_mode(user_id, None)
    _pop_pending(user_id)
    await callback.answer()


