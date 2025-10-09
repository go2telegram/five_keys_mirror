"""Hot-reloadable link overrides for product and registration URLs."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote, urlsplit

import httpx

from app.config import settings

LOG = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
SETS_DIR = BASE_DIR / "links" / "sets"
ACTIVE_SET_FILE = BASE_DIR / "links" / "active_set.txt"
AUDIT_LOG = BASE_DIR / "links" / "audit.jsonl"

DEFAULT_SET_NAME = "default"

_CACHE_LOCK = asyncio.Lock()
_ACTIVE_LOCK = asyncio.Lock()

_ACTIVE_SET: str | None = None
_LOADED_SET: str | None = None
_REGISTER_LINK: str | None = None
_PRODUCT_LINKS: dict[str, str] = {}

_ACTOR: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "link_manager_actor", default=None
)

__all__ = [
    "get_register_link",
    "set_register_link",
    "get_product_link",
    "set_product_link",
    "delete_product_link",
    "get_all_product_links",
    "set_bulk_links",
    "active_set_name",
    "switch_set",
    "list_sets",
    "export_set",
    "audit_actor",
]


@contextlib.contextmanager
def audit_actor(admin_id: int | None):
    """Attach the acting admin id to subsequent mutations."""

    token = _ACTOR.set(admin_id)
    try:
        yield
    finally:  # pragma: no branch - context manager contract
        _ACTOR.reset(token)


def _ensure_storage() -> None:
    SETS_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_SET_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)


def _sanitize_set_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("set name must be a string")
    candidate = name.strip()
    if not candidate:
        raise ValueError("set name cannot be empty")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", candidate):
        raise ValueError("set name must match [A-Za-z0-9_-]{1,64}")
    return candidate


def _sanitize_product_id(product_id: str) -> str:
    candidate = str(product_id).strip()
    if not candidate:
        raise ValueError("product_id cannot be empty")
    return candidate


def _validate_url(url: str) -> str:
    if not isinstance(url, str):
        raise ValueError("url must be a string")
    candidate = url.strip()
    if not candidate:
        raise ValueError("url cannot be empty")
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() != "https":
        raise ValueError("only https:// links are allowed")
    if not parsed.netloc:
        raise ValueError("url must include a host")
    if parsed.scheme.lower().startswith("javascript"):
        raise ValueError("javascript URLs are not allowed")
    return candidate


async def _read_active_set() -> str:
    def _read() -> str:
        try:
            raw = ACTIVE_SET_FILE.read_text(encoding="utf-8")
        except FileNotFoundError:
            return DEFAULT_SET_NAME
        candidate = raw.strip()
        return candidate or DEFAULT_SET_NAME

    return await asyncio.to_thread(_read)


async def _write_active_set(name: str) -> None:
    def _write() -> None:
        _ensure_storage()
        ACTIVE_SET_FILE.write_text(name, encoding="utf-8")

    await asyncio.to_thread(_write)


async def active_set_name() -> str:
    global _ACTIVE_SET
    if _ACTIVE_SET is not None:
        return _ACTIVE_SET
    async with _ACTIVE_LOCK:
        if _ACTIVE_SET is not None:
            return _ACTIVE_SET
        name = await _read_active_set()
        _ACTIVE_SET = name
        return name


def _set_active_cache(name: str) -> None:
    global _ACTIVE_SET
    _ACTIVE_SET = name


async def _load_set_payload(name: str) -> dict[str, Any]:
    path = SETS_DIR / f"{name}.json"

    def _load() -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            LOG.warning("link_manager: invalid JSON in %s", path)
            return {}
        if isinstance(raw, dict):
            return raw
        return {}

    return await asyncio.to_thread(_load)


async def _save_set_payload(name: str, payload: dict[str, Any]) -> None:
    path = SETS_DIR / f"{name}.json"

    def _write() -> None:
        _ensure_storage()
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")

    await asyncio.to_thread(_write)


def _canonicalise_mapping(mapping: Dict[str, Any]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in mapping.items():
        if not isinstance(value, str):
            continue
        try:
            pid = _sanitize_product_id(key)
            url = _validate_url(value)
        except ValueError:
            continue
        cleaned[pid] = url
    return cleaned


def _invalidate_cache() -> None:
    global _LOADED_SET, _REGISTER_LINK, _PRODUCT_LINKS
    _LOADED_SET = None
    _REGISTER_LINK = None
    _PRODUCT_LINKS = {}


async def _refresh_cache(force: bool = False) -> None:
    global _LOADED_SET, _REGISTER_LINK, _PRODUCT_LINKS
    name = await active_set_name()
    if not force and _LOADED_SET == name:
        return
    payload = await _load_set_payload(name)
    register_raw = payload.get("register")
    if isinstance(register_raw, str) and register_raw.strip():
        _REGISTER_LINK = register_raw.strip()
    else:
        _REGISTER_LINK = None
    products_raw = payload.get("products")
    if isinstance(products_raw, dict):
        _PRODUCT_LINKS = _canonicalise_mapping(products_raw)
    else:
        _PRODUCT_LINKS = {}
    _LOADED_SET = name


def _auto_product_link(product_id: str) -> str | None:
    base = (settings.BASE_PRODUCT_URL or "").strip()
    if not base:
        return None
    return f"{base.rstrip('/')}/{quote(product_id)}"


def _resolve_register_fallback() -> str:
    return (
        (_REGISTER_LINK or "")
        or (settings.BASE_REGISTER_URL or "").strip()
        or settings.velavie_url
        or ""
    )


async def get_register_link() -> str:
    async with _CACHE_LOCK:
        await _refresh_cache()
        link = _REGISTER_LINK
    return link or _resolve_register_fallback()


async def set_register_link(url: str) -> None:
    candidate = _validate_url(url)
    name = await active_set_name()
    async with _CACHE_LOCK:
        global _REGISTER_LINK, _LOADED_SET
        await _refresh_cache()
        payload = await _load_set_payload(name)
        old = None
        if isinstance(payload.get("register"), str):
            old = payload.get("register") or None
        payload["register"] = candidate
        await _save_set_payload(name, payload)
        _REGISTER_LINK = candidate
        _LOADED_SET = name
    _schedule_ping(candidate)
    await _append_audit("set_register", "register", old, candidate, name)


async def get_product_link(product_id: str) -> str | None:
    pid = _sanitize_product_id(product_id)
    async with _CACHE_LOCK:
        await _refresh_cache()
        override = _PRODUCT_LINKS.get(pid)
    if override:
        return override
    if not settings.LINK_AUTOBUILD:
        return None
    return _auto_product_link(pid)


async def set_product_link(product_id: str, url: str) -> None:
    pid = _sanitize_product_id(product_id)
    candidate = _validate_url(url)
    name = await active_set_name()
    async with _CACHE_LOCK:
        await _refresh_cache()
        payload = await _load_set_payload(name)
        products = payload.get("products")
        if not isinstance(products, dict):
            products = {}
        old = products.get(pid)
        products[pid] = candidate
        payload["products"] = products
        await _save_set_payload(name, payload)
        _PRODUCT_LINKS[pid] = candidate
        _LOADED_SET = name
    _schedule_ping(candidate)
    await _append_audit("set_product", pid, old, candidate, name)


async def delete_product_link(product_id: str) -> None:
    pid = _sanitize_product_id(product_id)
    name = await active_set_name()
    async with _CACHE_LOCK:
        await _refresh_cache()
        payload = await _load_set_payload(name)
        products = payload.get("products")
        if not isinstance(products, dict) or pid not in products:
            return
        old = products.pop(pid)
        payload["products"] = products
        await _save_set_payload(name, payload)
        _PRODUCT_LINKS.pop(pid, None)
        _LOADED_SET = name
    await _append_audit("delete_product", pid, old, None, name)


async def get_all_product_links() -> dict[str, str]:
    async with _CACHE_LOCK:
        await _refresh_cache()
        return dict(_PRODUCT_LINKS)


async def set_bulk_links(mapping: dict[str, str]) -> None:
    if not isinstance(mapping, dict):
        raise ValueError("mapping must be a dict")
    name = await active_set_name()
    cleaned = {}
    for key, value in mapping.items():
        pid = _sanitize_product_id(key)
        cleaned[pid] = _validate_url(value)
    async with _CACHE_LOCK:
        global _PRODUCT_LINKS, _LOADED_SET
        await _refresh_cache()
        payload = await _load_set_payload(name)
        source = payload.get("products") if isinstance(payload.get("products"), dict) else {}
        old_products = dict(source)
        payload["products"] = dict(cleaned)
        await _save_set_payload(name, payload)
        _PRODUCT_LINKS = dict(cleaned)
        _LOADED_SET = name
    for url in cleaned.values():
        _schedule_ping(url)
    await _append_audit("bulk_set", "products", old_products, cleaned, name)


async def switch_set(name: str) -> None:
    new_name = _sanitize_set_name(name)
    _ensure_storage()
    old_name = await active_set_name()
    # Ensure the target file exists so subsequent loads succeed.
    target_path = SETS_DIR / f"{new_name}.json"
    if not target_path.exists():
        await _save_set_payload(new_name, {})
    await _write_active_set(new_name)
    _set_active_cache(new_name)
    _invalidate_cache()
    await _append_audit("switch_set", "active_set", old_name, new_name, new_name)


async def list_sets() -> list[str]:
    def _list() -> list[str]:
        if not SETS_DIR.exists():
            return [DEFAULT_SET_NAME]
        items = []
        for path in SETS_DIR.glob("*.json"):
            items.append(path.stem)
        if DEFAULT_SET_NAME not in items:
            items.append(DEFAULT_SET_NAME)
        return sorted(set(items))

    return await asyncio.to_thread(_list)


async def export_set(name: str | None = None) -> dict[str, Any]:
    target = name or await active_set_name()
    payload = await _load_set_payload(target)
    data = {
        "register": payload.get("register") if isinstance(payload.get("register"), str) else None,
        "products": dict(payload.get("products")) if isinstance(payload.get("products"), dict) else {},
        "set": target,
    }
    return data


def _schedule_ping(url: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - no running loop
        return
    loop.create_task(_ping_url(url))


async def _ping_url(url: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            await client.head(url)
    except Exception:  # noqa: BLE001 - network failures are not fatal
        LOG.warning("link_manager: HEAD %s failed", url)


async def _append_audit(
    action: str,
    target: str,
    old: Any,
    new: Any,
    set_name: str,
) -> None:
    actor = _ACTOR.get()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "admin_id": actor,
        "action": action,
        "target": target,
        "old": old,
        "new": new,
        "set": set_name,
    }

    def _write() -> None:
        _ensure_storage()
        with AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False))
            fh.write("\n")

    await asyncio.to_thread(_write)
