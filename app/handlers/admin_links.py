"""Admin commands for managing product and registration links."""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Mapping

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
    get_all_product_links,
    get_register_link,
    list_sets,
    set_bulk_links,
    set_product_link,
    set_register_link,
    switch_set,
)

router = Router(name="admin_links")

_PENDING_IMPORT: set[int] = set()


def _collect_core_products(limit: int = 38) -> list[str]:
    catalog = load_catalog()
    ordered = catalog.get("ordered") or []
    return list(ordered)[:limit]


def _format_links_csv(register: str | None, products: Mapping[str, str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["type", "id", "url"])
    writer.writerow(["register", "", register or ""])
    for product_id in sorted(products):
        url = products[product_id]
        writer.writerow(["product", product_id, url])
    return buffer.getvalue()


def _parse_links_payload(raw: str) -> tuple[str | None, dict[str, str]]:
    stripped = raw.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:  # pragma: no cover - re-raised below
            raise ValueError("Невалидный JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Ожидался объект с полями register/products")
        register = payload.get("register")
        products_raw: Any = payload.get("products")
        products = products_raw if isinstance(products_raw, dict) else {}
        cleaned: dict[str, str] = {}
        for pid, url in products.items():
            product_id = str(pid).strip()
            link = str(url).strip()
            if product_id and link:
                cleaned[product_id] = link
        register_value = register.strip() if isinstance(register, str) and register.strip() else None
        return register_value, cleaned

    buffer = io.StringIO(raw)
    reader = csv.DictReader(buffer)
    required = {"type", "id", "url"}
    header = {
        (name or "").strip().lower()
        for name in reader.fieldnames or []
        if name is not None
    }
    if not header or not required.issubset(header):
        raise ValueError("CSV должен содержать колонки type,id,url")

    register_link: str | None = None
    products: dict[str, str] = {}
    for row in reader:
        if not isinstance(row, dict):
            continue
        entry_type = (row.get("type") or "").strip().lower()
        if entry_type == "register":
            url = (row.get("url") or "").strip()
            if url:
                register_link = url
            continue
        if entry_type != "product":
            continue
        product_id = (row.get("id") or "").strip()
        url = (row.get("url") or "").strip()
        if product_id and url:
            products[product_id] = url

    if register_link is None and not products:
        raise ValueError("CSV не содержит данных для импорта")
    return register_link, products


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
    raw_args = command.args or ""
    parts = [part for part in raw_args.split() if part]
    fmt = "json"
    target: str | None = None
    for part in parts:
        lowered = part.lower()
        if lowered in {"json", "csv"}:
            fmt = lowered
        elif target is None:
            target = part
    data = await export_set(target)
    if fmt == "csv":
        csv_payload = _format_links_csv(data.get("register"), data.get("products", {}))
        await message.answer(f"<pre>{csv_payload}</pre>", parse_mode="HTML")
        return
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    await message.answer(f"<pre>{payload}</pre>", parse_mode="HTML")


@router.message(Command("import_links"))
@admin_only
async def cmd_import_links(message: Message, command: CommandObject) -> None:
    raw = (command.args or "").strip()
    if raw:
        await _apply_import(message, raw)
        return
    if not message.from_user:
        return
    _PENDING_IMPORT.add(message.from_user.id)
    await message.answer("Пришли JSON с ключами register/products в следующем сообщении")


@router.message(F.text)
@admin_only
async def handle_import_payload(message: Message) -> None:
    if not message.from_user:
        return
    admin_id = message.from_user.id
    if admin_id not in _PENDING_IMPORT:
        return
    _PENDING_IMPORT.discard(admin_id)
    await _apply_import(message, message.text or "")


async def _apply_import(message: Message, raw: str) -> None:
    admin_id = message.from_user.id if message.from_user else None
    try:
        register, products = _parse_links_payload(raw)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    try:
        with audit_actor(admin_id):
            if register:
                await set_register_link(register)
            await set_bulk_links(products)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    await message.answer(
        "✅ Импорт завершён\n"
        f"Регистрация: {register or 'без изменений'}\n"
        f"Overrides: {len(products)}",
    )
