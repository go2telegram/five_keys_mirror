#!/usr/bin/env python3
"""Utilities for building and validating the product catalog."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "app" / "catalog" / "products.json"
SCHEMA_PATH = ROOT / "app" / "catalog" / "schema.json"


class CatalogValidationError(RuntimeError):
    """Raised when the catalog schema validation fails."""


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _property_pointer(base: str, key: str) -> str:
    return f"{base}.{key}" if base != "$" else f"$.{key}"


def _index_pointer(base: str, index: int) -> str:
    return f"{base}[{index}]"


def _validate_node(value: Any, schema: Mapping[str, Any], pointer: str = "$") -> None:
    schema_type = schema.get("type")

    if isinstance(schema_type, str):
        if schema_type == "object":
            if not isinstance(value, Mapping):
                raise CatalogValidationError(
                    f"{pointer}: expected object, got {_type_name(value)}",
                )
            required = schema.get("required") or []
            for name in required:
                if name not in value:
                    raise CatalogValidationError(
                        f"{pointer}: missing required property '{name}'",
                    )
            properties = schema.get("properties")
            if isinstance(properties, Mapping):
                for name, subschema in properties.items():
                    if name in value:
                        _validate_node(value[name], subschema, _property_pointer(pointer, name))
            additional = schema.get("additionalProperties")
            if additional is False:
                allowed = set(properties.keys()) if isinstance(properties, Mapping) else set()
                extras = sorted(set(value.keys()) - allowed)
                if extras:
                    extras_formatted = ", ".join(extras)
                    raise CatalogValidationError(
                        f"{pointer}: unexpected properties: {extras_formatted}",
                    )
            return
        if schema_type == "array":
            if not isinstance(value, list):
                raise CatalogValidationError(
                    f"{pointer}: expected array, got {_type_name(value)}",
                )
            min_items = schema.get("minItems")
            if isinstance(min_items, int) and len(value) < min_items:
                raise CatalogValidationError(
                    f"{pointer}: expected at least {min_items} item(s)",
                )
            item_schema = schema.get("items")
            if isinstance(item_schema, Mapping):
                for index, item in enumerate(value):
                    _validate_node(item, item_schema, _index_pointer(pointer, index))
            return
        if schema_type == "string":
            if not isinstance(value, str):
                raise CatalogValidationError(
                    f"{pointer}: expected string, got {_type_name(value)}",
                )
            min_length = schema.get("minLength")
            if isinstance(min_length, int) and len(value) < min_length:
                raise CatalogValidationError(
                    f"{pointer}: string length must be at least {min_length}",
                )
            pattern = schema.get("pattern")
            if isinstance(pattern, str) and not re.fullmatch(pattern, value):
                raise CatalogValidationError(
                    f"{pointer}: string does not match required pattern",
                )
            return
        if schema_type == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise CatalogValidationError(
                    f"{pointer}: expected number, got {_type_name(value)}",
                )
            return
        if schema_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise CatalogValidationError(
                    f"{pointer}: expected integer, got {_type_name(value)}",
                )
            return
        if schema_type == "boolean":
            if not isinstance(value, bool):
                raise CatalogValidationError(
                    f"{pointer}: expected boolean, got {_type_name(value)}",
                )
            return

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        raise CatalogValidationError(
            f"{pointer}: value {value!r} is not allowed",
        )


def load_schema(path: Path | None = None) -> Mapping[str, Any]:
    schema_path = Path(path) if path is not None else SCHEMA_PATH
    try:
        raw = schema_path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - surfaced in CLI usage
        raise CatalogValidationError(f"Cannot read schema file {schema_path}: {exc}") from exc
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CatalogValidationError(
            f"Schema file {schema_path} is not valid JSON",
        ) from exc
    if not isinstance(schema, Mapping):
        raise CatalogValidationError("Catalog schema must be a JSON object")
    return schema


def load_catalog(path: Path | None = None) -> Mapping[str, Any]:
    catalog_path = Path(path) if path is not None else CATALOG_PATH
    try:
        raw = catalog_path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - surfaced in CLI usage
        raise CatalogValidationError(f"Cannot read catalog file {catalog_path}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CatalogValidationError(
            f"Catalog file {catalog_path} is not valid JSON",
        ) from exc
    if not isinstance(payload, Mapping):
        raise CatalogValidationError("Catalog root must be a JSON object")
    return payload


def validate_catalog_payload(
    payload: Mapping[str, Any],
    *,
    schema: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    schema_mapping = schema or load_schema()
    if not isinstance(schema_mapping, Mapping):
        raise CatalogValidationError("Catalog schema must be a JSON object")
    _validate_node(payload, schema_mapping, pointer="$")
    return payload


def validate_catalog(
    path: Path | None = None,
    *,
    schema_path: Path | None = None,
) -> Mapping[str, Any]:
    schema_mapping = load_schema(schema_path)
    payload = load_catalog(path)
    return validate_catalog_payload(payload, schema=schema_mapping)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate the catalog against the bundled JSON schema.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Path to the catalog JSON file (default: app/catalog/products.json)",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="Path to the JSON schema file (default: app/catalog/schema.json)",
    )
    args = parser.parse_args(argv)

    try:
        payload = validate_catalog(args.source, schema_path=args.schema)
    except CatalogValidationError as exc:
        parser.exit(status=1, message=f"error: {exc}\n")

    products = payload.get("products")
    count = len(products) if isinstance(products, list) else 0
    parser.exit(status=0, message=f"Catalog OK ({count} products)\n")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
