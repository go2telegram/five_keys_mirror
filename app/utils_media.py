from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import aiohttp
from aiogram import Bot
from aiogram.types import BufferedInputFile, FSInputFile, InputMediaPhoto
from aiohttp import ClientError

from app.catalog.loader import product_by_alias, product_by_id
from app.utils.image_resolver import resolve_media_reference

LOG = logging.getLogger(__name__)


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
    if isinstance(primary, str) and primary:
        if primary not in refs:
            refs.insert(0, primary)
    return refs


async def _build_media_group(refs: List[str]) -> list[InputMediaPhoto]:
    media: list[InputMediaPhoto] = []
    session: aiohttp.ClientSession | None = None
    try:
        for ref in refs:
            source, session = await _resolve_media_source(ref, session)
            if not source:
                continue
            media.append(InputMediaPhoto(media=source))
    finally:
        if session:
            await session.close()
    return media


async def _resolve_media_source(
    ref: str, session: aiohttp.ClientSession | None
) -> tuple[FSInputFile | BufferedInputFile | None, aiohttp.ClientSession | None]:
    resolved = resolve_media_reference(ref)
    if isinstance(resolved, FSInputFile):
        return resolved, session
    if isinstance(resolved, str):
        session = session or aiohttp.ClientSession()
        proxy = await _download_via_proxy(session, resolved)
        if proxy:
            return proxy, session
        return None, session
    return None, session


async def _download_via_proxy(
    session: aiohttp.ClientSession, url: str
) -> BufferedInputFile | None:
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                LOG.warning(
                    "Failed to fetch media %s via proxy: status %s", url, resp.status
                )
                return None
            data = await resp.read()
    except ClientError as exc:
        LOG.warning("Network error fetching media %s: %s", url, exc)
        return None
    except Exception:
        LOG.exception("Unexpected error fetching media %s", url)
        return None

    filename = _extract_filename(url)
    return BufferedInputFile(data, filename=filename)


def _extract_filename(url: str) -> str:
    name = Path(url).name
    if not name:
        return "image"
    if "?" in name:
        return name.split("?")[0] or "image"
    return name


async def send_product_album(bot: Bot, chat_id: int, codes: List[str]) -> None:
    """Send a media album with catalog images for the given product codes."""

    collected: list[str] = []
    seen: set[str] = set()
    for code in codes:
        product = _resolve_product(code)
        if not product:
            LOG.warning("send_product_album: unknown product %s", code)
            continue
        for ref in _collect_image_refs(product):
            if ref in seen:
                continue
            if not resolve_media_reference(ref):
                continue
            collected.append(ref)
            seen.add(ref)
            break
        else:
            LOG.warning("send_product_album: no local images for %s", code)

    if not collected:
        LOG.info("send_product_album: nothing to send for %s", codes)
        return

    media_group = await _build_media_group(collected)
    if not media_group:
        LOG.info("send_product_album: failed to build media group for %s", collected)
        return

    if len(media_group) >= 2:
        try:
            await bot.send_media_group(chat_id, media=media_group)
            LOG.debug("send_product_album: sent media group (%d items)", len(media_group))
            return
        except Exception:
            LOG.exception("send_product_album: media group failed; falling back to singles")

    session: aiohttp.ClientSession | None = None
    try:
        for ref in collected:
            source, session = await _resolve_media_source(ref, session)
            if not source:
                continue
            try:
                await bot.send_photo(chat_id, photo=source)
                LOG.debug("send_product_album: sent single %s", ref)
            except Exception:
                LOG.exception("send_product_album: failed to send %s", ref)
    finally:
        if session:
            await session.close()
