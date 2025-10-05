from __future__ import annotations

import html
import json
from datetime import datetime, timezone

import aiohttp
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config import settings
from app.keyboards import kb_panel
from app.utils_logs import tail_logs

router = Router()


def _resolve_base_url() -> str:
    host = settings.WEB_HOST
    if host in {"0.0.0.0", "::", ""}:
        host = "127.0.0.1"
    return f"http://{host}:{settings.WEB_PORT}"


async def _request_json(method: str, path: str, payload: dict | None = None) -> str:
    url = f"{_resolve_base_url()}{path}"
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if method.upper() == "GET":
                async with session.get(url) as resp:
                    return await _format_response(resp)
            async with session.post(url, json=payload or {}) as resp:
                return await _format_response(resp)
    except aiohttp.ClientError as exc:
        return f"Ошибка запроса: {exc}"


async def _format_response(resp: aiohttp.ClientResponse) -> str:
    text = await resp.text()
    if resp.content_type == "application/json":
        try:
            data = await resp.json()
            return json.dumps(data, ensure_ascii=False, indent=2)
        except (aiohttp.ContentTypeError, json.JSONDecodeError):
            pass
    if text:
        return text.strip()
    return f"HTTP {resp.status}"


def _format_as_pre(text: str) -> str:
    escaped = html.escape(text)
    return f"<pre><code>{escaped}</code></pre>"


def _check_admin(user_id: int) -> bool:
    return user_id == settings.ADMIN_ID


@router.message(Command("panel"))
async def panel_command(message: Message) -> None:
    if not _check_admin(message.from_user.id):
        return

    await message.answer(
        "Панель диагностики:",
        reply_markup=kb_panel(),
    )


@router.callback_query(F.data == "panel:ping")
async def panel_ping(callback: CallbackQuery) -> None:
    if not _check_admin(callback.from_user.id):
        await callback.answer()
        return

    result = await _request_json("GET", "/ping")
    if callback.message:
        await callback.message.answer(_format_as_pre(result))
    else:  # pragma: no cover - callbacks without messages are rare
        await callback.answer(result[:200], show_alert=True)
        return
    await callback.answer("Пинг выполнен")


@router.callback_query(F.data == "panel:echo")
async def panel_echo(callback: CallbackQuery) -> None:
    if not _check_admin(callback.from_user.id):
        await callback.answer()
        return

    payload = {"source": "panel", "ts": datetime.now(timezone.utc).isoformat()}
    result = await _request_json("POST", "/doctor/echo", payload)
    if callback.message:
        await callback.message.answer(_format_as_pre(result))
    else:  # pragma: no cover
        await callback.answer(result[:200], show_alert=True)
        return
    await callback.answer("Echo отправлен")


@router.callback_query(F.data == "panel:logs")
async def panel_logs(callback: CallbackQuery) -> None:
    if not _check_admin(callback.from_user.id):
        await callback.answer()
        return

    if not settings.LOG_PATH:
        if callback.message:
            await callback.message.answer("LOG_PATH не настроен")
        await callback.answer()
        return

    logs_text = tail_logs(settings.LOG_PATH)
    if callback.message:
        await callback.message.answer(_format_as_pre(logs_text))
    else:  # pragma: no cover
        await callback.answer("Логи недоступны", show_alert=True)
        return
    await callback.answer("Логи готовы")
