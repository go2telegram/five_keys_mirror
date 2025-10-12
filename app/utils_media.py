from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from pathlib import Path

import aiohttp
from aiogram import Bot
from aiogram.types import BufferedInputFile, FSInputFile, InputMediaPhoto
from aiohttp import ClientError

from app.background import background_queue
from app.catalog.loader import product_by_alias, product_by_id
from app.feature_flags import feature_flags
from app.utils.image_resolver import resolve_media_reference

LOG = logging.getLogger(__name__)
_IMAGE_CACHE: OrderedDict[str, bytes] = OrderedDict()
_CACHE_LOCK = asyncio.Lock()
_MAX_CACHE_ITEMS = 180
_DEFAULT_TIMEOUT = 8.0
_DEFAULT_RETRIES = 2
_FALLBACK_CONTENT_TYPES = {"application/octet-stream", "binary/octet-stream"}


async def _get_cached_bytes(url: str) -> bytes | None:
    async with _CACHE_LOCK:
        data = _IMAGE_CACHE.get(url)
        if data is None:
            return None
        _IMAGE_CACHE.move_to_end(url)
        return data


async def _store_cached_bytes(url: str, data: bytes) -> None:
    async with _CACHE_LOCK:
        _IMAGE_CACHE[url] = data
        _IMAGE_CACHE.move_to_end(url)
        while len(_IMAGE_CACHE) > _MAX_CACHE_ITEMS:
            _IMAGE_CACHE.popitem(last=False)


def _is_supported_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized.startswith("image/"):
        return True
    return normalized in _FALLBACK_CONTENT_TYPES


async def _download_image(
    url: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
    retries: int = _DEFAULT_RETRIES,
) -> bytes | None:
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    delay = 0.2
    async with aiohttp.ClientSession(timeout=client_timeout) as session:
        for attempt in range(retries + 1):
            try:
                async with session.get(url, allow_redirects=True) as response:
                    content_type = response.headers.get("Content-Type")
                    status = response.status
                    if status != 200:
                        LOG.warning(
                            "Failed to fetch media %s: status %s",
                            url,
                            status,
                        )
                        if attempt < retries and status >= 500:
                            await asyncio.sleep(delay)
                            delay = min(delay * 2, 1.0)
                            continue
                        return None
                    if not _is_supported_content_type(content_type):
                        LOG.warning(
                            "Unexpected content type for %s: %s",
                            url,
                            content_type,
                        )
                        return None
                    data = await response.read()
                    if not data:
                        LOG.warning("Empty payload received for media %s", url)
                        return None
                    return data
            except (ClientError, asyncio.TimeoutError) as exc:
                LOG.warning(
                    "Network error fetching media %s (attempt %s/%s): %s",
                    url,
                    attempt + 1,
                    retries + 1,
                    exc,
                )
            except Exception:  # pragma: no cover - defensive guard
                LOG.exception("Unexpected error fetching media %s", url)
                return None
            if attempt < retries:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 1.0)
    return None


async def fetch_image_as_file(
    url: str, *, timeout: float = _DEFAULT_TIMEOUT, retries: int = _DEFAULT_RETRIES
) -> BufferedInputFile | None:
    cached = await _get_cached_bytes(url)
    if cached is not None:
        return BufferedInputFile(cached, filename=_extract_filename(url))

    data = await _download_image(url, timeout=timeout, retries=retries)
    if data is None:
        return None

    await _store_cached_bytes(url, data)
    return BufferedInputFile(data, filename=_extract_filename(url))


def _resolve_product(code: str) -> dict | None:
    if not code:
        return None
    product = product_by_id(code)
    if product:
        return product
    return product_by_alias(code)


def _collect_image_refs(product: dict) -> list[str]:
    refs: list[str] = []
    raw_images = product.get("images")
    if isinstance(raw_images, list):
        for image in raw_images:
            if isinstance(image, str) and image and image not in refs:
                refs.append(image)
    primary = product.get("image")
    if isinstance(primary, str) and primary and primary not in refs:
        refs.insert(0, primary)
    return refs


async def _check_remote_media(url: str) -> bool:
    timeout = aiohttp.ClientTimeout(total=4.0)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session, session.head(
            url, allow_redirects=True
        ) as response:
            status = response.status
            if status == 405:  # Method Not Allowed — trust Telegram to fetch via GET
                return True
            if not (200 <= status < 400):
                LOG.warning("send_product_album: remote HEAD %s returned %s", url, status)
                return False
            content_type = response.headers.get("Content-Type")
            if content_type and not _is_supported_content_type(content_type):
                LOG.warning("send_product_album: remote HEAD %s content-type %s", url, content_type)
                return False
            return True
    except (ClientError, asyncio.TimeoutError) as exc:
        LOG.warning("send_product_album: remote HEAD %s failed: %s", url, exc)
    except Exception:  # pragma: no cover - defensive fallback for unexpected errors
        LOG.exception("send_product_album: remote HEAD unexpected error for %s", url)
    return False


async def _gather_media_entries(
    refs: Sequence[str],
) -> list[tuple[str, FSInputFile | BufferedInputFile | str]]:
    entries: list[tuple[str, FSInputFile | BufferedInputFile | str]] = []
    for ref in refs:
        try:
            source = await _resolve_media_source(ref)
        except Exception:  # pragma: no cover - defensive guard
            LOG.exception("send_product_album: failed to resolve media %s", ref)
            continue
        if not source:
            continue
        if isinstance(source, str) and not await _check_remote_media(source):
            continue
        entries.append((ref, source))
    return entries


async def _resolve_media_source(ref: str) -> FSInputFile | BufferedInputFile | None:
    resolved = resolve_media_reference(ref)
    if isinstance(resolved, FSInputFile):
        return resolved
    if isinstance(resolved, str):
        if feature_flags.is_enabled("FF_MEDIA_PROXY"):
            proxy = await fetch_image_as_file(resolved)
            if proxy:
                return proxy
            LOG.warning("Failed to proxy remote media %s", resolved)
        return resolved
    return None


async def _prefetch_url(url: str) -> None:
    if await _get_cached_bytes(url) is not None:
        return
    data = await _download_image(url)
    if data is not None:
        await _store_cached_bytes(url, data)


def precache_remote_images(urls: Iterable[str]) -> None:
    """Schedule remote image URLs for background prefetching."""

    seen: set[str] = set()
    for url in urls:
        if not isinstance(url, str):
            continue
        normalized = url.strip()
        if not normalized or not normalized.startswith("http"):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        if not background_queue.submit(lambda url=normalized: _prefetch_url(url)):
            LOG.debug("background queue inactive; skipping precache for %s", normalized)
            break


def _extract_filename(url: str) -> str:
    name = Path(url).name
    if not name:
        return "image.jpg"
    if "?" in name:
        name = name.split("?", 1)[0]
    if not name:
        return "image.jpg"
    if "." not in name:
        return f"{name}.jpg"
    return name


async def send_product_album(bot: Bot, chat_id: int, codes: Sequence[str]) -> None:
    """Send a media album with catalog images for the given product codes."""

    collected: list[str] = []
    seen: set[str] = set()
    for code in codes:
        product = _resolve_product(code)
        if not product:
            LOG.warning("send_product_album: unknown product %s", code)
            continue
        added = False
        for ref in _collect_image_refs(product):
            if ref in seen:
                continue
            if not resolve_media_reference(ref):
                continue
            collected.append(ref)
            seen.add(ref)
            added = True
        if not added:
            LOG.warning("send_product_album: no usable images for %s", code)

    if not collected:
        LOG.info("send_product_album: nothing to send for %s", codes)
        return

    precache_remote_images(collected)

    entries = await _gather_media_entries(collected)
    if not entries:
        LOG.info("send_product_album: no valid media sources for %s", collected)
        return

    media_group = [InputMediaPhoto(media=source) for _, source in entries]

    if len(media_group) >= 2:
        try:
            await bot.send_media_group(chat_id, media=media_group)
            LOG.debug("send_product_album: sent media group (%d items)", len(media_group))
            return
        except Exception:
            LOG.exception("send_product_album: media group failed; falling back to singles")

    for ref, source in entries:
        try:
            await bot.send_photo(chat_id, photo=source)
            LOG.debug("send_product_album: sent single %s", ref)
        except Exception:
            LOG.exception("send_product_album: failed to send %s", ref)
