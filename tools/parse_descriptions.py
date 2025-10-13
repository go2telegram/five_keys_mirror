"""CLI tool to parse product descriptions into a normalized index."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.build_products as bp  # noqa: E402
from tools.build_products import (  # noqa: E402
    ProductBlock,
    _alias_variants,
    _canonical_title,
    _join_paragraphs,
    _normalize_space,
    _refine_slug,
    _section_for_line,
    _slug,
    _split_blocks,
    _split_sentences,
    _tokenize_slug,
    quote_url,
)

ORDER_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _iter_description_texts(path: Path) -> Iterator[tuple[str, str]]:
    if path.is_file():
        if path.suffix.lower() != ".txt":
            return
        yield str(path), path.read_text(encoding="utf-8")
        return
    if path.is_dir():
        for file_path in sorted(
            p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".txt"
        ):
            yield str(file_path), file_path.read_text(encoding="utf-8")


def _normalize_url(url: str | None) -> str:
    if not url:
        return ""
    cleaned = url.strip()
    if not cleaned:
        return ""
    if not ORDER_URL_RE.match(cleaned):
        cleaned = "https://" + cleaned.lstrip("/")
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = cleaned.strip()
    return quote_url(cleaned)


def _collect_section(block: ProductBlock) -> dict[str, str]:
    if not block.lines:
        return {}
    section_data: dict[str, list[str]] = defaultdict(list)
    body: list[str] = []
    current = "body"
    for line in block.lines[1:]:
        if not line:
            if current == "body":
                body.append("")
            else:
                section_data[current].append("")
            continue
        section = _section_for_line(line)
        if section:
            current = section[0]
            if section[1]:
                section_data[current].append(section[1])
            continue
        if current == "body":
            body.append(line)
        else:
            section_data[current].append(line)
    description = _join_paragraphs(body)
    sentences = _split_sentences(_normalize_space(description))
    short = " ".join(sentences[:2]) if sentences else description
    usage = _join_paragraphs([part for part in section_data.get("usage", []) if part])
    contra = _join_paragraphs([part for part in section_data.get("contra", []) if part])
    composition = _join_paragraphs([part for part in section_data.get("composition", []) if part])
    data: dict[str, str] = {
        "description": description,
        "short": short,
    }
    if usage:
        data["usage"] = usage
    if contra:
        data["contra"] = contra
    if composition:
        data["composition"] = composition
    return data


def _build_record(block: ProductBlock) -> dict[str, object]:
    if not block.lines:
        raise ValueError(f"Empty block in {block.origin}")
    title = block.lines[0]
    canonical_title = _canonical_title(block.lines)
    product_id = _refine_slug(_slug(canonical_title))
    tags = sorted({token for token in _tokenize_slug(product_id) if token})
    aliases = _alias_variants(product_id)
    section_data = _collect_section(block)
    description = section_data.get("description", "")
    short = section_data.get("short") or description or title
    section_data["short"] = short
    buy_url = _normalize_url(block.url)
    data = {
        "title": title,
        "id": product_id,
        "buy_url": buy_url,
        "tags": tags,
        "aliases": aliases,
    }
    data.update(section_data)
    overrides = bp.DESCRIPTION_OVERRIDES.get(product_id)
    if overrides:
        if "buy_url" in overrides:
            data["buy_url"] = overrides["buy_url"]
        for key, value in overrides.items():
            if key != "buy_url":
                data[key] = value
    return data


def build_index(descriptions_path: Path | str) -> list[dict[str, object]]:
    path = Path(descriptions_path)
    if not path.exists():
        raise FileNotFoundError(descriptions_path)
    records: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for origin, text in _iter_description_texts(path):
        for block in _split_blocks(text, origin=origin):
            record = _build_record(block)
            key = (record["id"], record["buy_url"])
            if not record["buy_url"]:
                continue
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    records.sort(key=lambda item: item["title"].lower())
    return records


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse product descriptions")
    parser.add_argument(
        "--descriptions-path", required=True, help="Path to descriptions file or directory"
    )
    parser.add_argument("--out", required=True, help="Path to write resulting JSON index")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = _parse_args(argv)
    records = build_index(Path(args.descriptions_path))
    if not records:
        raise SystemExit("No descriptions parsed")
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
