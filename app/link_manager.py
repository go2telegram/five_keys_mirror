"""Hot-reloadable link overrides for product and registration URLs."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import csv
import io
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote, urlsplit

import httpx

from app.config import settings
from app.http_client import (
    AsyncCircuitBreaker,
    CircuitBreakerOpenError,
    async_http_client,
    request_with_retries,
)

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

_ACTOR: contextvars.ContextVar[str | int | None] = contextvars.ContextVar(
    "link_manager_actor", default=None
)

_PING_CIRCUIT_BREAKER = AsyncCircuitBreaker(
    max_failures=settings.HTTP_CIRCUIT_BREAKER_MAX_FAILURES,
    base_delay=settings.HTTP_CIRCUIT_BREAKER_BASE_DELAY,
    max_delay=settings.HTTP_CIRCUIT_BREAKER_MAX_DELAY,
    name="link-ping",
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
    "export_set_csv",
    "import_set",
    "audit_actor",
]


@contextlib.contextmanager
def audit_actor(admin_id: str | int | None):
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
    if not force and name == _LOADED_SET:
        return
    payload = await _load_set_payload(name)
    register_raw = payload.get("register")
    _REGISTER_LINK = (
        register_raw.strip() if isinstance(register_raw, str) and register_raw.strip() else None
    )
    products_raw = payload.get("products")
    _PRODUCT_LINKS = _canonicalise_mapping(products_raw) if isinstance(products_raw, dict) else {}
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
        "products": (
            dict(payload.get("products")) if isinstance(payload.get("products"), dict) else {}
        ),
        "set": target,
    }
    return data


async def export_set_csv(name: str | None = None) -> str:
    data = await export_set(name)
    return _build_csv_snapshot(data["register"], data["products"])


def _schedule_ping(url: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - no running loop
        return
    loop.create_task(_ping_url(url))


async def _ping_url(url: str) -> None:
    try:
        async with async_http_client(follow_redirects=True) as client:
            await request_with_retries(
                "HEAD",
                url,
                client=client,
                circuit_breaker=_PING_CIRCUIT_BREAKER,
                retries=settings.HTTP_RETRY_ATTEMPTS,
                backoff_factor=settings.HTTP_RETRY_BACKOFF_INITIAL,
                backoff_max=settings.HTTP_RETRY_BACKOFF_MAX,
                retry_statuses=settings.HTTP_RETRY_STATUS_CODES,
            )
    except CircuitBreakerOpenError:
        LOG.warning("link_manager: circuit open for HEAD %s", url)
    except httpx.HTTPError as exc:
        LOG.warning("link_manager: HEAD %s failed: %s", url, exc)
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
        "admin": actor,
        "action": action,
        "product_id": None,
        "register": None,
        "old": old,
        "new": new,
        "set": set_name,
    }

    if target == "register":
        entry["register"] = True
    else:
        entry["product_id"] = target

    def _write() -> None:
        _ensure_storage()
        with AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False))
            fh.write("\n")

    await asyncio.to_thread(_write)


def _build_csv_snapshot(register: str | None, products: dict[str, str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["product_id", "url"])
    if register:
        writer.writerow(["register", register])
    for pid, url in sorted(products.items()):
        writer.writerow([pid, url])
    return buffer.getvalue().strip()


def _parse_import_payload(data: Any) -> tuple[str | None, dict[str, str], list[str]]:
    if isinstance(data, dict):
        return _parse_import_dict(data)
    if isinstance(data, bytes):
        text = data.decode("utf-8")
    elif isinstance(data, str):
        text = data
    else:
        raise ValueError("unsupported import payload type")

    candidate = text.strip()
    if not candidate:
        raise ValueError("import payload cannot be empty")
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return _parse_import_csv(candidate)
    return _parse_import_dict(parsed)


def _parse_import_dict(data: Dict[str, Any]) -> tuple[str | None, dict[str, str], list[str]]:
    warnings: list[str] = []
    register: str | None = None
    products: dict[str, str] = {}

    if "register" in data:
        register_value = data.get("register")
        if isinstance(register_value, str) and register_value.strip():
            register = _validate_url(register_value)
        elif register_value:
            warnings.append("register value ignored: expected string URL")

    products_value = data.get("products")
    if isinstance(products_value, dict):
        products = _canonicalise_mapping(products_value)
    elif isinstance(products_value, list):
        for item in products_value:
            if not isinstance(item, dict):
                continue
            pid = item.get("product_id") or item.get("product") or item.get("id")
            url = item.get("url")
            if not pid or not url:
                continue
            try:
                products[_sanitize_product_id(pid)] = _validate_url(str(url))
            except ValueError:
                warnings.append(f"invalid product row ignored: {pid!r}")
    elif products_value:
        warnings.append("products value ignored: expected mapping")

    if not products and "products" not in data:
        products = _canonicalise_mapping({k: v for k, v in data.items() if isinstance(v, str)})

    return register, products, warnings


def _parse_import_csv(text: str) -> tuple[str | None, dict[str, str], list[str]]:
    stream = io.StringIO(text)
    reader = csv.DictReader(stream)
    if not reader.fieldnames:
        raise ValueError("CSV payload must include headers")

    field_map = {name.strip().lower(): name for name in reader.fieldnames if isinstance(name, str)}
    url_field = field_map.get("url")
    if not url_field:
        raise ValueError("CSV payload must include a 'url' column")
    product_field = None
    for candidate in ("product_id", "product", "id", "code"):
        if candidate in field_map:
            product_field = field_map[candidate]
            break
    register_field = None
    for candidate in ("register", "is_register", "kind", "type"):
        if candidate in field_map:
            register_field = field_map[candidate]
            break
    if product_field is None and register_field is None:
        raise ValueError("CSV payload must include a product identifier column")

    warnings: list[str] = []
    register: str | None = None
    products: dict[str, str] = {}

    for row in reader:
        if not row:
            continue
        url_raw = (row.get(url_field) or "").strip()
        if not url_raw:
            continue
        marker = (row.get(register_field) or "").strip().lower() if register_field else ""
        product_raw = (row.get(product_field) or "").strip() if product_field else ""
        try:
            candidate_url = _validate_url(url_raw)
        except ValueError:
            warnings.append(f"invalid URL ignored: {url_raw!r}")
            continue

        if marker in {"1", "true", "yes", "register"} or product_raw.lower() == "register":
            register = candidate_url
            continue

        if not product_raw:
            warnings.append("row without product_id skipped")
            continue

        try:
            pid = _sanitize_product_id(product_raw)
        except ValueError:
            warnings.append(f"invalid product_id ignored: {product_raw!r}")
            continue
        products[pid] = candidate_url

    return register, products, warnings


async def import_set(
    data: Any,
    *,
    target: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    global _REGISTER_LINK, _PRODUCT_LINKS, _LOADED_SET
    register, products, warnings = _parse_import_payload(data)
    name = _sanitize_set_name(target) if target else await active_set_name()
    result = {
        "set": name,
        "register": register,
        "products": dict(products),
        "warnings": warnings,
        "applied": False,
    }

    if not apply:
        return result

    active = await active_set_name()
    async with _CACHE_LOCK:
        await _refresh_cache(force=True)
        payload = await _load_set_payload(name)
        old_register = payload.get("register") if isinstance(payload.get("register"), str) else None
        old_products = (
            dict(payload.get("products")) if isinstance(payload.get("products"), dict) else {}
        )
        if register:
            payload["register"] = register
        else:
            payload.pop("register", None)
        payload["products"] = dict(products)
        await _save_set_payload(name, payload)
        if name == active:
            global _REGISTER_LINK, _PRODUCT_LINKS, _LOADED_SET
            _REGISTER_LINK = register
            _PRODUCT_LINKS = dict(products)
            _LOADED_SET = name
        else:
            _invalidate_cache()

    if register:
        _schedule_ping(register)
    for url in products.values():
        _schedule_ping(url)

    await _append_audit("import_register", "register", old_register, register, name)
    await _append_audit("import_products", "products", old_products, products, name)

    result["applied"] = True
    return result
