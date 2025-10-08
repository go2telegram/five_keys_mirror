"""Minimal YAML loader for quiz tests (subset of YAML 1.2)."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any


class YAMLError(Exception):
    """Generic YAML parsing error."""


@dataclass
class _Line:
    text: str
    indent: int


class _Parser:
    def __init__(self, text: str) -> None:
        lines = []
        for raw in text.splitlines():
            stripped = raw.rstrip()
            if not stripped.strip():
                continue
            indent = len(stripped) - len(stripped.lstrip(" "))
            lines.append(_Line(text=stripped.lstrip(), indent=indent))
        self._lines = lines
        self._index = 0

    def parse(self) -> Any:
        if not self._lines:
            return None
        return self._parse_block(self._lines[0].indent)

    def _peek(self) -> _Line | None:
        if self._index >= len(self._lines):
            return None
        return self._lines[self._index]

    def _consume(self) -> _Line:
        line = self._lines[self._index]
        self._index += 1
        return line

    def _parse_block(self, indent: int) -> Any:
        line = self._peek()
        if line is None:
            return None
        if line.indent < indent:
            return None
        if line.text.startswith("- "):
            return self._parse_sequence(indent)
        return self._parse_mapping(indent)

    def _parse_sequence(self, indent: int) -> list[Any]:
        items: list[Any] = []
        while True:
            line = self._peek()
            if line is None or line.indent < indent or not line.text.startswith("- "):
                break
            self._consume()
            remainder = line.text[2:].strip()
            if not remainder:
                value = self._parse_block(indent + 2)
                items.append(value)
                continue
            if ":" in remainder:
                key, value_part = remainder.split(":", 1)
                item: dict[str, Any] = {}
                key = key.strip()
                value_part = value_part.strip()
                if value_part:
                    item[key] = _parse_scalar(value_part)
                else:
                    item[key] = self._parse_block(indent + 2)
                self._parse_mapping_into(indent + 2, item)
                items.append(item)
            else:
                items.append(_parse_scalar(remainder))
        return items

    def _parse_mapping(self, indent: int) -> dict[str, Any]:
        mapping: dict[str, Any] = {}
        self._parse_mapping_into(indent, mapping)
        return mapping

    def _parse_mapping_into(self, indent: int, mapping: dict[str, Any]) -> None:
        while True:
            line = self._peek()
            if line is None or line.indent < indent:
                return
            if line.text.startswith("- "):
                return
            if line.indent != indent:
                raise YAMLError(f"Unexpected indentation at line: {line.text}")
            self._consume()
            if ":" not in line.text:
                raise YAMLError(f"Invalid mapping entry: {line.text}")
            key, value_part = line.text.split(":", 1)
            key = key.strip()
            value_part = value_part.strip()
            if value_part:
                mapping[key] = _parse_scalar(value_part)
            else:
                mapping[key] = self._parse_block(indent + 2)


def _parse_scalar(value: str) -> Any:
    if not value:
        return None
    if value[0] in {'"', "'"} and value[-1] == value[0]:
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"null", "none", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if value[0] in "[{":
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:  # pragma: no cover - defensive
            raise YAMLError(f"Cannot parse literal: {value}") from exc
    try:
        if value.startswith("0") and value != "0":
            raise ValueError
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def safe_load(stream: Any) -> Any:
    """Parse YAML text into Python objects (minimal subset)."""

    if hasattr(stream, "read"):
        text = stream.read()
    else:
        text = str(stream)
    parser = _Parser(text)
    return parser.parse()


__all__ = ["safe_load", "YAMLError"]
