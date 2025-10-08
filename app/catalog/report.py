"""Helpers for assembling catalog build reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


CATALOG_DIR = Path(__file__).resolve().parent
CATALOG_PATH = CATALOG_DIR / "products.json"
REPORT_PATH = CATALOG_DIR / "products.report.json"
BUILD_SUMMARY_PATH = CATALOG_DIR / "mapping" / "build_summary.json"
IMAGES_DIR = CATALOG_DIR.parent / "static" / "images" / "products"


class CatalogReportError(RuntimeError):
    """Raised when a catalog report cannot be generated."""


@dataclass(slots=True)
class CatalogReport:
    """Summary of the last catalog build."""

    built: int
    found_images: int
    found_descriptions: int
    unmatched_images: list[str]
    missing_images: list[str]
    catalog_path: Path
    generated_at: datetime | None


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return int(float(value))
        except ValueError:
            return None
    if isinstance(value, (list, tuple, set)):
        return len(value)
    if isinstance(value, dict):
        for key in ("count", "found", "total", "value", "length"):
            if key in value:
                nested = _coerce_int(value[key])
                if nested is not None:
                    return nested
    return None


def _coerce_list(value: object) -> list[str] | None:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if isinstance(value, dict):
        for key in ("items", "values", "list", "paths"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [str(item) for item in nested]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return None


def _dig(mapping: dict, path: tuple[str, ...]) -> object | None:
    current: object = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        if key not in current:
            return None
        current = current[key]
    return current


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogReportError(f"Catalog file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogReportError(f"Catalog file is not valid JSON: {path}") from exc


def _normalize_image_list(items: Iterable[str] | None) -> list[str]:
    if not items:
        return []
    normalized: list[str] = []
    for item in items:
        if not item:
            continue
        value = str(item).strip()
        if not value:
            continue
        normalized.append(value)
    return normalized


def _parse_report_payload(payload: dict, *, fallback_catalog: Path) -> CatalogReport:
    built = int(payload.get("built", 0))
    found_images = int(payload.get("found_images", 0))
    found_descriptions = int(payload.get("found_descriptions", built))
    catalog_path = Path(payload.get("catalog_path") or fallback_catalog)
    generated_raw = payload.get("generated_at") or payload.get("timestamp")
    generated_at: datetime | None = None
    if isinstance(generated_raw, str) and generated_raw.strip():
        try:
            generated_at = datetime.fromisoformat(generated_raw.strip())
            if generated_at.tzinfo is None:
                generated_at = generated_at.replace(tzinfo=timezone.utc)
        except ValueError:
            generated_at = None
    missing_images = _normalize_image_list(payload.get("missing_images"))
    unmatched_images = _normalize_image_list(payload.get("unmatched_images"))
    return CatalogReport(
        built=built,
        found_images=found_images,
        found_descriptions=found_descriptions,
        missing_images=missing_images,
        unmatched_images=unmatched_images,
        catalog_path=catalog_path,
        generated_at=generated_at,
    )


def _parse_summary_payload(payload: dict, *, fallback_catalog: Path) -> CatalogReport:
    candidates = payload if isinstance(payload, dict) else {}

    def extract_int(paths: Iterable[tuple[str, ...]], default: int = 0) -> int:
        for path in paths:
            value = _dig(candidates, path)
            if value is None:
                continue
            coerced = _coerce_int(value)
            if coerced is not None:
                return coerced
        return default

    def extract_list(paths: Iterable[tuple[str, ...]]) -> list[str]:
        for path in paths:
            value = _dig(candidates, path)
            if value is None:
                continue
            coerced = _coerce_list(value)
            if coerced:
                return _normalize_image_list(coerced)
        return []

    built = extract_int((("built",), ("stats", "built"), ("counts", "built")), 0)
    found_images = extract_int(
        (
            ("found_images",),
            ("found", "images"),
            ("counts", "images"),
            ("counts", "images", "found"),
            ("images", "found"),
        ),
        built,
    )
    found_descriptions = extract_int(
        (
            ("found_descriptions",),
            ("found", "descriptions"),
            ("counts", "descriptions"),
            ("counts", "descriptions", "found"),
            ("descriptions", "found"),
        ),
        built,
    )
    catalog_path_raw = _dig(
        candidates,
        ("catalog_path",),
    ) or _dig(candidates, ("paths", "catalog"))
    catalog_path = Path(str(catalog_path_raw)) if catalog_path_raw else fallback_catalog

    generated_raw = _dig(candidates, ("generated_at",)) or _dig(candidates, ("timestamp",))
    if generated_raw is None:
        generated_raw = _dig(candidates, ("finished_at",)) or _dig(candidates, ("built_at",))
    generated_at: datetime | None = None
    if isinstance(generated_raw, str) and generated_raw.strip():
        try:
            generated_at = datetime.fromisoformat(generated_raw.strip())
            if generated_at.tzinfo is None:
                generated_at = generated_at.replace(tzinfo=timezone.utc)
        except ValueError:
            generated_at = None

    missing_images = extract_list(
        (
            ("missing_images",),
            ("missing", "images"),
            ("images", "missing"),
        )
    )
    unmatched_images = extract_list(
        (
            ("unmatched_images",),
            ("unmatched", "images"),
            ("images", "unmatched"),
        )
    )

    return CatalogReport(
        built=built,
        found_images=found_images,
        found_descriptions=found_descriptions,
        missing_images=missing_images,
        unmatched_images=unmatched_images,
        catalog_path=catalog_path,
        generated_at=generated_at,
    )


def _relative_image_path(image: str) -> str | None:
    prefix = "/static/images/products/"
    if image.startswith(prefix):
        return image[len(prefix) :]
    if image.startswith("static/images/products/"):
        return image[len("static/images/products/") :]
    if image.startswith("images/products/"):
        return image[len("images/products/") :]
    return None


def _collect_local_images(directory: Path) -> set[str]:
    if not directory.exists():
        return set()
    files: set[str] = set()
    for file in directory.rglob("*"):
        if file.is_file():
            files.add(str(file.relative_to(directory)).replace("\\", "/"))
    return files


def _fallback_report(*, catalog_path: Path, images_dir: Path) -> CatalogReport:
    payload = _load_json(catalog_path)
    products = payload.get("products")
    if not isinstance(products, list):
        raise CatalogReportError("Catalog JSON must contain a 'products' list")

    built = len(products)
    found_descriptions = built

    available_images = _collect_local_images(images_dir)
    used_images: set[str] = set()
    for product in products:
        if not isinstance(product, dict):
            continue
        for image in _normalize_image_list(product.get("images")):
            local_image = _relative_image_path(image)
            if local_image:
                used_images.add(local_image)

    missing_images = sorted(used_images.difference(available_images))
    unmatched_images = sorted(available_images.difference(used_images))

    found_images = len(available_images)

    generated_at: datetime | None = None
    try:
        stat = catalog_path.stat()
        generated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    except FileNotFoundError as exc:  # pragma: no cover - guarded above
        raise CatalogReportError(f"Catalog file not found: {catalog_path}") from exc

    return CatalogReport(
        built=built,
        found_images=found_images,
        found_descriptions=found_descriptions,
        missing_images=missing_images,
        unmatched_images=unmatched_images,
        catalog_path=catalog_path,
        generated_at=generated_at,
    )


def get_catalog_report(
    *,
    summary_path: Path | None = None,
    report_path: Path | None = None,
    catalog_path: Path | None = None,
    images_dir: Path | None = None,
) -> CatalogReport:
    """Return catalog build metadata, falling back to products.json analysis."""

    resolved_catalog = Path(catalog_path or CATALOG_PATH)
    resolved_summary = Path(summary_path or BUILD_SUMMARY_PATH)
    resolved_report = Path(report_path or REPORT_PATH)
    resolved_images = Path(images_dir or IMAGES_DIR)

    if resolved_summary.exists():
        payload = _load_json(resolved_summary)
        return _parse_summary_payload(payload, fallback_catalog=resolved_catalog)

    if resolved_report.exists():
        payload = _load_json(resolved_report)
        return _parse_report_payload(payload, fallback_catalog=resolved_catalog)

    return _fallback_report(catalog_path=resolved_catalog, images_dir=resolved_images)


__all__ = [
    "CatalogReport",
    "CatalogReportError",
    "CATALOG_PATH",
    "IMAGES_DIR",
    "REPORT_PATH",
    "BUILD_SUMMARY_PATH",
    "get_catalog_report",
]
