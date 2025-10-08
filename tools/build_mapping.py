#!/usr/bin/env python3
"""Build mapping between catalog descriptions and image assets."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass
class ImageEntry:
    file: str
    variants: list[str]


@dataclass
class DescriptionEntry:
    product_id: str
    title: str
    short: str
    description: str
    usage: str
    contra: str
    tags: list[str]
    buy_url: str | None
    category_slug: str | None
    available: bool

    @property
    def slug(self) -> str:
        return self.product_id


@dataclass
class CatalogEntry:
    image_file: str | None
    product_id: str
    title: str
    short: str
    description: str
    usage: str
    contra: str
    tags: list[str]
    buy_url: str | None
    status: str
    notes: str
    available: bool


def _load_json(path: Path) -> list[dict]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - surfaced as SystemExit
        raise SystemExit(f"Cannot read {path}: {exc}") from exc
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:  # pragma: no cover - surfaced as SystemExit
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, list):
        raise SystemExit(f"JSON root must be a list in {path}")
    return data


def _ensure_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise SystemExit("Expected a list of strings for variants")


def _normalize_tags(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    raise SystemExit("Tags must be provided as a list")


def load_images(path: Path) -> list[ImageEntry]:
    items: list[ImageEntry] = []
    for raw in _load_json(path):
        if not isinstance(raw, Mapping):
            raise SystemExit("Image index items must be objects")
        file = raw.get("file")
        if not isinstance(file, str):
            raise SystemExit("Image entry must include a file path")
        variants = _ensure_list(raw.get("variants"))
        items.append(ImageEntry(file=file, variants=variants))
    return items


def load_descriptions(path: Path) -> list[DescriptionEntry]:
    items: list[DescriptionEntry] = []
    for raw in _load_json(path):
        if not isinstance(raw, Mapping):
            raise SystemExit("Description index items must be objects")
        product_id = raw.get("id") or raw.get("slug")
        if not isinstance(product_id, str):
            raise SystemExit("Description entry must include id or slug")
        title = str(raw.get("title", "")).strip()
        short = str(raw.get("short", "")).strip()
        description = str(raw.get("description", "")).strip()
        usage = str(raw.get("usage", "")).strip()
        contra = str(raw.get("contra", "")).strip()
        tags = _normalize_tags(raw.get("tags"))
        buy_url = raw.get("buy_url")
        if buy_url is not None and not isinstance(buy_url, str):
            raise SystemExit("buy_url must be a string if provided")
        category_slug = raw.get("category_slug")
        if category_slug is not None and not isinstance(category_slug, str):
            raise SystemExit("category_slug must be a string if provided")
        available = bool(raw.get("available", True))
        items.append(
            DescriptionEntry(
                product_id=product_id.strip(),
                title=title,
                short=short,
                description=description,
                usage=usage,
                contra=contra,
                tags=tags,
                buy_url=buy_url.strip() if isinstance(buy_url, str) else None,
                category_slug=category_slug.strip() if isinstance(category_slug, str) else None,
                available=available,
            )
        )
    return items


def _canonical(value: str) -> str:
    return value.strip().lower()


def _without_chars(value: str, chars: str) -> str:
    result = value
    for ch in chars:
        result = result.replace(ch, "")
    return result


def _slugify(value: str) -> str:
    chars: list[str] = []
    for ch in value.lower():
        if ch.isalnum():
            chars.append(ch)
        else:
            chars.append("-")
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "item"


def ensure_utm(url: str | None, *, product_id: str, category_slug: str | None) -> str | None:
    if not url:
        return url
    parsed = urlsplit(url)
    query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
    defaults = {
        "utm_source": "tg_bot",
        "utm_medium": "catalog",
        "utm_campaign": category_slug or "catalog",
        "utm_content": product_id,
    }
    updated = False
    for key, value in defaults.items():
        if key not in query_items or not query_items[key]:
            query_items[key] = value
            updated = True
    if not updated and parsed.query:
        return url
    query = urlencode(query_items, doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def _iter_image_tokens(entry: ImageEntry) -> Iterable[str]:
    seen: set[str] = set()
    candidates = list(entry.variants)
    path = Path(entry.file)
    if path.stem:
        candidates.append(path.stem)
    for value in candidates:
        token = _canonical(value)
        if token and token not in seen:
            seen.add(token)
            yield token
            compact = _without_chars(token, "-_")
            if compact not in seen:
                seen.add(compact)
                yield compact
            swapped = token.replace("-", "_")
            if swapped not in seen:
                seen.add(swapped)
                yield swapped


def _build_candidate_map(descriptions: Sequence[DescriptionEntry]) -> dict[str, list[DescriptionEntry]]:
    mapping: dict[str, list[DescriptionEntry]] = {}
    for desc in descriptions:
        forms = {
            _canonical(desc.slug),
            _canonical(desc.slug.replace("-", "_")),
            _without_chars(_canonical(desc.slug), "-"),
            _without_chars(_canonical(desc.slug), "-_"),
        }
        for form in forms:
            if not form:
                continue
            mapping.setdefault(form, []).append(desc)
    return mapping


def _match_description(
    image: ImageEntry,
    descriptions: Sequence[DescriptionEntry],
    candidate_map: Mapping[str, list[DescriptionEntry]],
    used: set[str],
) -> DescriptionEntry | None:
    tokens = list(_iter_image_tokens(image))
    for token in tokens:
        for candidate in candidate_map.get(token, []):
            if candidate.product_id not in used:
                return candidate
    best_ratio = 0.0
    best_candidate: DescriptionEntry | None = None
    for token in tokens:
        for candidate in descriptions:
            if candidate.product_id in used:
                continue
            ratio = SequenceMatcher(None, token, _canonical(candidate.slug)).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_candidate = candidate
    if best_candidate and best_ratio >= 0.75:
        return best_candidate
    return None


def build_catalog_entries(
    images: Sequence[ImageEntry],
    descriptions: Sequence[DescriptionEntry],
) -> list[CatalogEntry]:
    candidate_map = _build_candidate_map(descriptions)
    used: set[str] = set()
    entries: list[CatalogEntry] = []
    for image in images:
        matched = _match_description(image, descriptions, candidate_map, used)
        if matched:
            used.add(matched.product_id)
            url = ensure_utm(
                matched.buy_url,
                product_id=matched.product_id,
                category_slug=matched.category_slug,
            )
            entry = CatalogEntry(
                image_file=image.file,
                product_id=matched.product_id,
                title=matched.title or matched.product_id,
                short=matched.short,
                description=matched.description,
                usage=matched.usage,
                contra=matched.contra,
                tags=list(matched.tags),
                buy_url=url,
                status="ok",
                notes="",
                available=matched.available,
            )
            entries.append(entry)
        else:
            base_name = next(iter(image.variants), Path(image.file).stem)
            product_id = _slugify(base_name or image.file)
            title = base_name.replace("_", " ").replace("-", " ").strip() or product_id
            entry = CatalogEntry(
                image_file=image.file,
                product_id=product_id,
                title=title,
                short="",
                description="",
                usage="",
                contra="",
                tags=["unmatched_image"],
                buy_url=None,
                status="placeholder",
                notes="No matching description",
                available=False,
            )
            entries.append(entry)
    for desc in descriptions:
        if desc.product_id in used:
            continue
        url = ensure_utm(
            desc.buy_url,
            product_id=desc.product_id,
            category_slug=desc.category_slug,
        )
        entry = CatalogEntry(
            image_file=None,
            product_id=desc.product_id,
            title=desc.title or desc.product_id,
            short=desc.short,
            description=desc.description,
            usage=desc.usage,
            contra=desc.contra,
            tags=list(desc.tags),
            buy_url=url,
            status="missing_image",
            notes="No matching image",
            available=False,
        )
        entries.append(entry)
    return entries


def write_csv(path: Path, entries: Sequence[CatalogEntry]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["image_file", "product_id", "title", "status", "order_velavie_link", "notes"])
        for entry in entries:
            writer.writerow([
                entry.image_file or "",
                entry.product_id,
                entry.title,
                entry.status,
                entry.buy_url or "",
                entry.notes,
            ])


def write_txt(path: Path, entries: Sequence[CatalogEntry]) -> None:
    blocks: list[str] = []
    for entry in entries:
        tags = ", ".join(entry.tags)
        block = "\n".join(
            [
                f"=== {entry.product_id} | {entry.title} ===",
                f"image: {entry.image_file or ''}",
                f"order: {entry.buy_url or ''}",
                f"short: {entry.short}",
                f"description: {entry.description}",
                f"usage: {entry.usage}",
                f"contra: {entry.contra}",
                f"tags: {tags}",
            ]
        )
        blocks.append(block)
    text = "\n\n".join(blocks)
    path.write_text(text, encoding="utf-8")


def run(
    *,
    images_path: Path,
    descriptions_path: Path,
    csv_path: Path,
    txt_path: Path,
    expect_images: int | None = None,
) -> list[CatalogEntry]:
    images = load_images(images_path)
    descriptions = load_descriptions(descriptions_path)
    entries = build_catalog_entries(images, descriptions)
    write_csv(csv_path, entries)
    write_txt(txt_path, entries)
    if expect_images is not None and len(entries) != expect_images:
        raise SystemExit(1)
    return entries


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--descriptions", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--txt", type=Path, required=True)
    parser.add_argument("--expect-images", type=int)
    parser.add_argument("--fail-on-mismatch", action="store_true", help="Reserved for compatibility")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        run(
            images_path=args.images,
            descriptions_path=args.descriptions,
            csv_path=args.csv,
            txt_path=args.txt,
            expect_images=args.expect_images,
        )
    except SystemExit as exc:
        raise
    except Exception as exc:  # pragma: no cover - surfaced as SystemExit
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
