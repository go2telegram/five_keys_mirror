"""Utilities for working with the product catalog."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable

from app.config import settings

BASE_MEDIA = "https://raw.githubusercontent.com/go2telegram/media/main/media/products"

# Fallback catalog data (used if products.json is missing on first run)
_DEFAULT_PRODUCTS = [
    {
        "id": "T8_EXTRA",
        "title": "T8 EXTRA",
        "bullets": [
            "Полипренолы 90% для мембран митохондрий",
            "Больше АТФ, меньше утомляемости",
        ],
        "image_url": f"{BASE_MEDIA}/extra.jpg",
        "buy_url": "https://shop.vilavi.com/Item/47086?ref=735861",
        "categories": ["energy"],
    },
    {
        "id": "T8_BLEND",
        "title": "T8 BLEND",
        "bullets": [
            "6 таёжных ягод + SibXP",
            "Антиоксидантная поддержка каждый день",
        ],
        "image_url": f"{BASE_MEDIA}/blend.jpg",
        "buy_url": "https://shop.vilavi.com/Item/79666?ref=735861",
        "categories": ["energy", "immunity", "stress"],
    },
    {
        "id": "VITEN",
        "title": "NASH ViTEN",
        "bullets": [
            "Природный индуктор интерферона",
            "Поддержка иммунитета в сезон простуд",
        ],
        "image_url": f"{BASE_MEDIA}/viten.jpg",
        "buy_url": "https://shop.vilavi.com/Item/28146?ref=735861",
        "categories": ["immunity", "energy"],
    },
    {
        "id": "TEO_GREEN",
        "title": "T8 TEO GREEN",
        "bullets": [
            "Растворимая/нерастворимая клетчатка",
            "Питает микробиом и ЖКТ",
        ],
        "image_url": f"{BASE_MEDIA}/teogreen.jpg",
        "buy_url": "https://shop.vilavi.com/Item/56176?ref=735861",
        "categories": ["gut", "energy"],
    },
    {
        "id": "MOBIO",
        "title": "MOBIO+",
        "bullets": [
            "Метабиотик с высокой биодоступностью",
            "После антибиотиков/стрессов — восстановление",
        ],
        "image_url": f"{BASE_MEDIA}/mobio.jpg",
        "buy_url": "https://shop.vilavi.com/Item/53056?ref=735861",
        "categories": ["gut"],
    },
    {
        "id": "OMEGA3",
        "title": "NASH Омега-3",
        "bullets": [
            "Высокая концентрация EPA/DHA",
            "Сосуды, мозг, противовоспалительно",
        ],
        "image_url": f"{BASE_MEDIA}/omega3.jpg",
        "buy_url": "https://shop.vilavi.com/Item/49596?ref=735861",
        "categories": ["energy", "sleep", "stress", "beauty_joint"],
    },
    {
        "id": "MAG_B6",
        "title": "Magnesium + B6",
        "bullets": [
            "Антистресс и мышечное расслабление",
            "Поддержка качества сна",
        ],
        "image_url": f"{BASE_MEDIA}/magniyb6.jpg",
        "buy_url": "https://shop.vilavi.com/Item/49576?ref=735861",
        "categories": ["sleep", "stress"],
    },
    {
        "id": "D3",
        "title": "Vitamin D3",
        "bullets": [
            "Иммунитет, кости, настроение",
            "Осенне-зимняя поддержка",
        ],
        "image_url": f"{BASE_MEDIA}/d3.jpg",
        "buy_url": "https://shop.vilavi.com/Item/49586?ref=735861",
        "categories": ["immunity", "sleep"],
    },
    {
        "id": "ERA_MIT_UP",
        "title": "T8 ERA MIT UP",
        "bullets": [
            "Коллаген + Уролитин A + SibXP",
            "Кожа/связки и энергия митохондрий",
        ],
        "image_url": f"{BASE_MEDIA}/mitup.jpg",
        "buy_url": "https://shop.vilavi.com/Item/39176?ref=735861",
        "categories": ["beauty_joint"],
    },
]

GOAL_MAP = {
    "energy": ["T8_EXTRA", "T8_BLEND"],
    "immunity": ["VITEN", "T8_BLEND", "D3"],
    "gut": ["TEO_GREEN", "MOBIO"],
    "sleep": ["MAG_B6", "OMEGA3", "D3"],
    "beauty_joint": ["ERA_MIT_UP", "OMEGA3"],
}

PRODUCTS: Dict[str, Dict[str, Any]] = {}
BUY_URLS: Dict[str, str] = {}
PRODUCT_CATEGORIES: Dict[str, list[str]] = {}
CATALOG_PATH: Path | None = None


def _catalog_path() -> Path:
    """Resolve catalog path based on settings."""
    custom = getattr(settings, "CATALOG_PRODUCTS_PATH", None)
    path = Path(custom) if custom else Path(__file__).with_name("products.json")
    return path.expanduser().resolve()


def _apply_catalog(items: Iterable[dict]) -> None:
    """Populate in-memory structures with catalog data."""
    PRODUCTS.clear()
    BUY_URLS.clear()
    PRODUCT_CATEGORIES.clear()

    for raw in items:
        if not isinstance(raw, dict):
            continue
        code = raw.get("id")
        if not code:
            continue
        entry = {
            "title": raw.get("title", code),
            "bullets": list(raw.get("bullets", []) or []),
            "image_url": raw.get("image_url"),
            "description": raw.get("description"),
        }
        PRODUCTS[code] = entry
        url = raw.get("buy_url")
        if url:
            BUY_URLS[code] = url
        PRODUCT_CATEGORIES[code] = list(raw.get("categories", []) or [])


def load_products() -> tuple[Path, int]:
    """Read products.json (or fallback) and update globals."""
    global CATALOG_PATH
    path = _catalog_path()
    items: Iterable[dict]
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        items = data.get("products", []) if isinstance(data, dict) else []
    else:
        items = _DEFAULT_PRODUCTS
    _apply_catalog(items)
    CATALOG_PATH = path
    return path, len(PRODUCTS)


def reload_products() -> tuple[Path, int]:
    """Force reload of catalog file."""
    return load_products()


def get_product(code: str) -> Dict[str, Any] | None:
    return PRODUCTS.get(code)


def get_product_categories(code: str) -> list[str]:
    return PRODUCT_CATEGORIES.get(code, [])


# Initial load on import
load_products()
