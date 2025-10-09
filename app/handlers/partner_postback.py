"""Handlers for partner postback/webhook events."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from aiohttp import web

from app.db.session import compat_session, session_scope
from app.repo import events as events_repo

_LOG = logging.getLogger("partner.postback")

_EVENT_ALIASES = {
    "click": "partner_click",
    "lead": "partner_click",
    "visit": "partner_click",
    "conversion": "partner_conversion",
    "sale": "partner_conversion",
    "order": "partner_conversion",
    "purchase": "partner_conversion",
    "pay": "partner_conversion",
}

_INT_KEYS = {
    "telegram_id",
    "tg_id",
    "user_id",
    "uid",
    "order_id",
    "click_id",
    "sub_id",
    "subid",
}

_FLOAT_KEYS = {"amount", "revenue", "value", "payout", "commission"}


def _parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(" ", "")
    if not text:
        return None
    text = text.replace(",", ".")
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _merge_payload(request: web.Request, body: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key, value in request.rel_url.query.items():
        payload[key] = value
    payload.update(body)
    return payload


async def _extract_body(request: web.Request) -> Dict[str, Any]:
    if request.method == "POST":
        content_type = request.content_type or ""
        if "json" in content_type:
            try:
                data = await request.json()
            except json.JSONDecodeError:
                data = {}
            if isinstance(data, dict):
                return data
            return {}
        if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            form = await request.post()
            return dict(form.items())
    return {}


def _normalize_meta(payload: Dict[str, Any]) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    for key, value in payload.items():
        norm_key = key.lower()
        if norm_key in _FLOAT_KEYS:
            parsed = _parse_float(value)
            if parsed is not None:
                meta[key] = parsed
                continue
        if norm_key in _INT_KEYS:
            parsed_int = _parse_int(value)
            if parsed_int is not None:
                meta[key] = parsed_int
                continue
        if isinstance(value, (int, float, bool)):
            meta[key] = value
            continue
        text = str(value)
        if not text:
            continue
        if len(text) > 512:
            text = text[:509] + "…"
        meta[key] = text
    return meta


def _detect_event_name(payload: Dict[str, Any]) -> str:
    raw = str(payload.get("event") or payload.get("type") or payload.get("action") or "").lower()
    if raw:
        name = _EVENT_ALIASES.get(raw)
        if name:
            return name
        return f"partner_{raw}"

    for key in ("amount", "order_id", "revenue", "value", "payout"):
        if payload.get(key) not in (None, ""):
            return "partner_conversion"
    for key in ("click_id", "subid", "sub_id"):
        if payload.get(key) not in (None, ""):
            return "partner_click"
    return "partner_event"


def _extract_user_id(payload: Dict[str, Any]) -> int | None:
    for key in ("telegram_id", "tg_id", "user_id", "uid"):
        value = payload.get(key) or payload.get(key.upper())
        parsed = _parse_int(value)
        if parsed:
            return parsed
    return None


async def partner_postback(request: web.Request) -> web.Response:
    body = await _extract_body(request)
    payload = _merge_payload(request, body)
    meta = _normalize_meta(payload)
    event_name = _detect_event_name(payload)
    user_id = _extract_user_id(payload)

    if not meta and payload:
        meta = {"payload": payload}

    try:
        async with compat_session(session_scope) as session:
            await events_repo.log(session, user_id, event_name, meta)
            await session.commit()
    except Exception as exc:  # pragma: no cover - defensive logging
        _LOG.exception("partner_postback failed: %s", exc)
        return web.json_response({"ok": False, "error": "internal_error"}, status=500)

    _LOG.info(
        "partner_event name=%s user_id=%s meta_keys=%s", event_name, user_id, sorted(meta.keys())
    )
    return web.json_response({"ok": True, "event": event_name})


__all__ = ["partner_postback"]
