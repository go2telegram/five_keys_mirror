"""Admin commands for managing product and registration links."""

from __future__ import annotations

import html
import json
from typing import Any, Dict, Optional, TypedDict

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.catalog.loader import load_catalog
from app.handlers.admin import admin_only
from app.link_manager import (
    active_set_name,
    audit_actor,
    delete_product_link,
    export_set,
    export_set_csv,
    get_all_product_links,
    get_register_link,
    import_set,
    list_sets,
    set_product_link,
    set_register_link,
    switch_set,
)

router = Router(name="admin_links")


class PendingImport(TypedDict, total=False):
    set: Optional[str]
    payload: Dict[str, Any]
    warnings: list[str]


_PENDING_IMPORT: dict[int, PendingImport] = {}


def _collect_core_products(limit: int = 38) -> list[str]:
    catalog = load_catalog()
    ordered = catalog.get("ordered") or []
    return list(ordered)[:limit]


@router.message(Command("set_register"))
@admin_only
async def cmd_set_register(message: Message, command: CommandObject) -> None:
    url = (command.args or "").strip()
    if not url:
        await message.answer("Использование: /set_register <url>")
        return
    admin_id = message.from_user.id if message.from_user else None
    try:
        with audit_actor(admin_id):
            await set_register_link(url)
    except ValueError as exc:  # pragma: no cover - defensive
        await message.answer(f"⚠️ {exc}")
        return
    await message.answer(f"✅ Ссылка регистрации обновлена:\n{url}")


@router.message(Command("set_link"))
@admin_only
async def cmd_set_link(message: Message, command: CommandObject) -> None:
    raw = (command.args or "").strip()
    parts = raw.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Использование: /set_link <product_id> <url>")
        return
    product_id, url = parts[0].strip(), parts[1].strip()
    if not product_id or not url:
        await message.answer("Нужно указать product_id и ссылку")
        return
    admin_id = message.from_user.id if message.from_user else None
    try:
        with audit_actor(admin_id):
            await set_product_link(product_id, url)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    await message.answer(f"✅ Ссылка для {product_id} обновлена")


@router.message(Command("del_link"))
@admin_only
async def cmd_delete_link(message: Message, command: CommandObject) -> None:
    product_id = (command.args or "").strip()
    if not product_id:
        await message.answer("Использование: /del_link <product_id>")
        return
    admin_id = message.from_user.id if message.from_user else None
    with audit_actor(admin_id):
        await delete_product_link(product_id)
    await message.answer(f"➖ Override для {product_id} удалён (если был)")


@router.message(Command("links"))
@admin_only
async def cmd_list_links(message: Message) -> None:
    register_link = await get_register_link()
    overrides = await get_all_product_links()
    current_set = await active_set_name()
    products = _collect_core_products()
    lines = [f"Активный сет: <b>{current_set}</b>"]
    lines.append(f"Регистрация: {register_link or '—'}")
    lines.append("")
    for pid in products:
        override = overrides.get(pid)
        status = "✅" if override else "➖"
        if override:
            lines.append(f"{status} {pid}: {override}")
        else:
            lines.append(f"{status} {pid}")
    await message.answer("\n".join(lines))


@router.message(Command("switch_links"))
@admin_only
async def cmd_switch_links(message: Message, command: CommandObject) -> None:
    target = (command.args or "").strip()
    if not target:
        sets = await list_sets()
        await message.answer("Укажи сет. Доступные: " + ", ".join(sets))
        return
    admin_id = message.from_user.id if message.from_user else None
    try:
        with audit_actor(admin_id):
            await switch_set(target)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    await message.answer(f"✅ Активный сет переключен на <b>{target}</b>")


@router.message(Command("export_links"))
@admin_only
async def cmd_export_links(message: Message, command: CommandObject) -> None:
    raw_args = (command.args or "").strip()
    tokens = [part for part in raw_args.split() if part]
    fmt = "all"
    target = None
    if tokens:
        last = tokens[-1].lower()
        if last in {"json", "csv"}:
            fmt = last
            tokens = tokens[:-1]
    if tokens:
        target = tokens[0]

    data = await export_set(target)
    if fmt in {"all", "json"}:
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        await message.answer(f"<pre>{payload}</pre>", parse_mode="HTML")
    if fmt in {"all", "csv"}:
        csv_payload = await export_set_csv(target)
        await message.answer(
            f"<pre>{html.escape(csv_payload)}</pre>",
            parse_mode="HTML",
        )


@router.message(Command("import_links"))
@admin_only
async def cmd_import_links(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    admin_id = message.from_user.id
    raw = (command.args or "").strip()
    lowered = raw.lower()
    if lowered == "apply":
        pending = _PENDING_IMPORT.get(admin_id)
        if not pending or not pending.get("payload"):
            await message.answer("⚠️ Нет данных для применения. Сначала пришли JSON или CSV.")
            return
        target = pending.get("set")
        payload = pending["payload"]
        try:
            with audit_actor(admin_id):
                result = await import_set(payload, target=target, apply=True)
        except ValueError as exc:
            await message.answer(f"⚠️ {exc}")
            return
        _PENDING_IMPORT.pop(admin_id, None)
        await message.answer(
            "✅ Импорт применён\n"
            f"Сет: <b>{html.escape(result['set'])}</b>\n"
            f"Регистрация: {html.escape(result['register']) if result['register'] else '—'}\n"
            f"Overrides: {len(result['products'])}",
            parse_mode="HTML",
        )
        return
    if lowered == "cancel":
        _PENDING_IMPORT.pop(admin_id, None)
        await message.answer("Импорт отменён")
        return

    target = raw or None
    _PENDING_IMPORT[admin_id] = PendingImport(set=target)
    await message.answer(
        "Пришли JSON или CSV (product_id,url). После проверки отправь /import_links apply",
    )


@router.message(F.text)
@admin_only
async def handle_import_payload(message: Message) -> None:
    if not message.from_user:
        return
    admin_id = message.from_user.id
    pending = _PENDING_IMPORT.get(admin_id)
    if not pending:
        return
    target = pending.get("set")
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("⚠️ Пустой импорт")
        return
    try:
        result = await import_set(raw, target=target, apply=False)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return

    payload: dict[str, Any] = {"products": result["products"]}
    if result.get("register_in_payload"):
        payload["register"] = result["register"]
    warnings = result.get("warnings") or []
    _PENDING_IMPORT[admin_id] = PendingImport(set=result["set"], payload=payload, warnings=warnings)

    preview_lines = [f"Сет: <b>{html.escape(result['set'])}</b>"]
    preview_lines.append(
        f"Регистрация: {html.escape(result['register']) if result['register'] else '—'}"
    )
    preview_lines.append(f"Overrides: {len(result['products'])}")
    sample = list(result["products"].items())[:5]
    if sample:
        preview_lines.append("Пример:")
        for pid, url in sample:
            preview_lines.append(f"• {html.escape(pid)}: {html.escape(url)}")
    if warnings:
        preview_lines.append("")
        preview_lines.append("⚠️ Предупреждения:")
        for warn in warnings:
            preview_lines.append(f"- {html.escape(warn)}")
    preview_lines.append("")
    preview_lines.append("Отправь /import_links apply чтобы применить или /import_links cancel")
    await message.answer("\n".join(preview_lines), parse_mode="HTML")
