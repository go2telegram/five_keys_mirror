#!/usr/bin/env python3
"""Generate a diff report between two product catalog JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:  # pragma: no cover - surfaced as SystemExit
        raise SystemExit(f"Cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:  # pragma: no cover - surfaced as SystemExit
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc


def _ensure_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit(f"Expected an object {context}")
    return value


def _load_products(path: Path) -> dict[str, dict[str, Any]]:
    data = _ensure_mapping(_read_json(path), context=f"at root of {path}")
    if "products" not in data:
        raise SystemExit(f"Missing 'products' key in {path}")
    products = data["products"]
    if not isinstance(products, list):
        raise SystemExit(f"'products' must be a list in {path}")

    catalog: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(products):
        if not isinstance(item, dict):
            raise SystemExit(f"Product at index {index} in {path} must be an object")
        product_id = item.get("id")
        if not isinstance(product_id, str) or not product_id.strip():
            raise SystemExit(f"Product at index {index} in {path} must include a non-empty id")
        if product_id in catalog:
            raise SystemExit(f"Duplicate product id '{product_id}' in {path}")
        catalog[product_id] = item
    return catalog


def _normalize_tags(product: dict[str, Any]) -> list[str]:
    value = product.get("tags")
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    raise SystemExit("Tags must be provided as a list")


def _normalize_title(product: dict[str, Any]) -> str:
    value = product.get("title", "")
    return str(value)


def _normalize_image(product: dict[str, Any]) -> str | None:
    value = product.get("image")
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise SystemExit("Image must be a string if provided")


def _normalize_order(product: dict[str, Any]) -> Any:
    def _normalize(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [_normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: _normalize(subvalue) for key, subvalue in value.items()}
        raise SystemExit("Order must consist of JSON-compatible values")

    return _normalize(product.get("order"))


def _order_to_display(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    return json.dumps(value, ensure_ascii=False)


def _format_tags(tags: Iterable[str]) -> str:
    return json.dumps(list(tags), ensure_ascii=False)


def _append_key_value(lines: list[str], key: str, value: str) -> None:
    parts = value.splitlines() or [""]
    lines.append(f"  {key}: {parts[0]}")
    for part in parts[1:]:
        lines.append(f"    {part}")


def _append_value(lines: list[str], prefix: str, value: str) -> None:
    parts = value.splitlines() or [""]
    lines.append(f"  {prefix}: {parts[0]}")
    for part in parts[1:]:
        lines.append(f"    {part}")


def _append_diff(lines: list[str], label: str, old_value: str, new_value: str) -> None:
    lines.append(f"{label}:")
    _append_value(lines, "old", old_value)
    _append_value(lines, "new", new_value)


def _write_report(
    out_path: Path,
    *,
    added: list[tuple[str, dict[str, Any]]],
    removed: list[tuple[str, dict[str, Any]]],
    changed: list[tuple[str, list[str]]],
) -> None:
    lines: list[str] = []

    def _section(title: str) -> None:
        if lines:
            lines.append("")
        lines.append(title)
        lines.append("=" * len(title))

    _section("ADDED")
    if added:
        for product_id, product in added:
            lines.append(f"- {product_id}")
            _append_key_value(lines, "title", _normalize_title(product) or "—")
            _append_key_value(lines, "image", _normalize_image(product) or "—")
            order_display = _order_to_display(_normalize_order(product)) if product.get("order") is not None else "—"
            _append_key_value(lines, "order", order_display)
            _append_key_value(lines, "tags", _format_tags(_normalize_tags(product)))
    else:
        lines.append("(none)")

    _section("REMOVED")
    if removed:
        for product_id, product in removed:
            lines.append(f"- {product_id}")
            _append_key_value(lines, "title", _normalize_title(product) or "—")
            _append_key_value(lines, "image", _normalize_image(product) or "—")
            order_display = _order_to_display(_normalize_order(product)) if product.get("order") is not None else "—"
            _append_key_value(lines, "order", order_display)
            _append_key_value(lines, "tags", _format_tags(_normalize_tags(product)))
    else:
        lines.append("(none)")

    _section("CHANGED")
    if changed:
        for product_id, diffs in changed:
            lines.append(f"- {product_id}")
            lines.extend(f"  {diff}" for diff in diffs)
    else:
        lines.append("(none)")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a diff report between two catalog JSON files.")
    parser.add_argument("--old", required=True, help="Path to the reference catalog JSON file.")
    parser.add_argument("--new", required=True, help="Path to the new catalog JSON file.")
    parser.add_argument("--out", required=True, help="Path to write the diff report.")
    args = parser.parse_args()

    old_products = _load_products(Path(args.old))
    new_products = _load_products(Path(args.new))

    added_ids = sorted(set(new_products) - set(old_products))
    removed_ids = sorted(set(old_products) - set(new_products))
    shared_ids = sorted(set(old_products) & set(new_products))

    added = [(product_id, new_products[product_id]) for product_id in added_ids]
    removed = [(product_id, old_products[product_id]) for product_id in removed_ids]

    changed: list[tuple[str, list[str]]] = []
    for product_id in shared_ids:
        old = old_products[product_id]
        new = new_products[product_id]

        diffs: list[str] = []

        old_title = _normalize_title(old)
        new_title = _normalize_title(new)
        if old_title != new_title:
            _append_diff(diffs, "title", old_title or "—", new_title or "—")

        old_image = _normalize_image(old)
        new_image = _normalize_image(new)
        if old_image != new_image:
            _append_diff(diffs, "image", old_image or "—", new_image or "—")

        old_order = _normalize_order(old)
        new_order = _normalize_order(new)
        if old_order != new_order:
            old_display = _order_to_display(old_order) if old.get("order") is not None else "—"
            new_display = _order_to_display(new_order) if new.get("order") is not None else "—"
            _append_diff(diffs, "order", old_display, new_display)

        old_tags = _normalize_tags(old)
        new_tags = _normalize_tags(new)
        if old_tags != new_tags:
            _append_diff(diffs, "tags", _format_tags(old_tags), _format_tags(new_tags))

        if diffs:
            changed.append((product_id, diffs))

    _write_report(Path(args.out), added=added, removed=removed, changed=changed)


if __name__ == "__main__":
    main()
