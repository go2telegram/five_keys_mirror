from io import BytesIO
from typing import List, Tuple

import httpx
from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaPhoto

from app.config import settings
from app.products import PRODUCTS

try:
    from PIL import Image

    PIL_OK = True
except Exception:
    PIL_OK = False


def _is_valid_url(u: str | None) -> bool:
    if not u:
        return False
    u = u.strip()
    return u.startswith("http")


async def _download(url: str) -> bytes | None:
    """
    Скачивает картинку по URL. Работает без системных прокси (trust_env=False).
    Если в .env указан HTTP_PROXY_URL, то используем его.
    """
    proxies = None
    if getattr(settings, "HTTP_PROXY_URL", None):
        proxies = settings.HTTP_PROXY_URL

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "TelegramBot/1.0"},
            trust_env=False,
            proxies=proxies,
        ) as cli:
            r = await cli.get(url)
            r.raise_for_status()
            return r.content
    except Exception as e:
        print(f"[media] download fail {url}: {e}")
        return None


def _to_jpeg_bytes(raw: bytes, target_name: str) -> Tuple[bytes, str]:
    """
    Если доступен Pillow — приводим к JPEG (RGB), макс. размер 1600px, качество 85.
    """
    if not PIL_OK:
        return raw, target_name

    try:
        im = Image.open(BytesIO(raw))
        im = im.convert("RGB")

        max_side = 1600
        w, h = im.size
        scale = min(max_side / max(w, h), 1.0)
        if scale < 1.0:
            im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        buf = BytesIO()
        im.save(buf, format="JPEG", optimize=True, quality=85)
        buf.seek(0)
        return buf.read(), (target_name.rsplit(".", 1)[0] + ".jpg")
    except Exception as e:
        print(f"[media] pillow fail ({target_name}): {e}; sending raw bytes")
        return raw, target_name


async def _prepare_files(urls: List[str]) -> List[InputMediaPhoto]:
    """
    Скачиваем и нормализуем список URL → готовим InputMediaPhoto.
    """
    media: List[InputMediaPhoto] = []
    for u in urls:
        data = await _download(u)
        if not data:
            continue
        name = u.split("/")[-1] or "image.jpg"
        data, name = _to_jpeg_bytes(data, name)
        media.append(InputMediaPhoto(media=BufferedInputFile(data, filename=name)))
        print(f"[media] prepared {name} ({len(data)} bytes)")
    return media


async def send_product_album(bot: Bot, chat_id: int, codes: List[str]) -> None:
    """
    Гарантированная отправка картинок:
    - качаем и нормализуем все файлы;
    - если 2+ фото → пробуем альбом;
    - если альбом не удался → шлём по одному.
    """
    urls: List[str] = []
    for code in codes:
        img = PRODUCTS.get(code, {}).get("image_url")
        ok = _is_valid_url(img)
        print(f"[media] url {code}: {img} -> {'OK' if ok else 'BAD'}")
        if ok:
            urls.append(img)

    if not urls:
        print("[media] no urls to send")
        return

    files = await _prepare_files(urls)
    if not files:
        print("[media] no files after prepare")
        return

    # 2+ файлов → альбом
    if len(files) >= 2:
        try:
            await bot.send_media_group(chat_id, media=files)
            print(f"[media] album sent: {len(files)} items")
            return
        except Exception as e:
            print(f"[media] album send fail: {e}; fallback singles")

    # fallback или 1 файл → по одному
    for f in files:
        try:
            await bot.send_photo(chat_id, photo=f.media)
            print(f"[media] single sent {f.media.file_name}")
        except Exception as e:
            print(f"[media] single fail: {e}")
