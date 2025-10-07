#!/usr/bin/env python3
"""Static audit for inline callback coverage."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _main_menu_callbacks() -> set[str]:
    path = ROOT / "app" / "keyboards.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    callbacks: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            super().__init__()
            self._inside = False

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            was_inside = self._inside
            if node.name == "kb_main":
                self._inside = True
                self.generic_visit(node)
                self._inside = was_inside
                return
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            if self._inside and isinstance(node.func, ast.Attribute) and node.func.attr == "button":
                for kw in node.keywords:
                    if kw.arg == "callback_data" and isinstance(kw.value, ast.Constant):
                        callbacks.add(str(kw.value.value))
            self.generic_visit(node)

    Visitor().visit(tree)
    return callbacks


def _handler_callbacks() -> tuple[set[str], list[str]]:
    target = ROOT / "app" / "handlers"
    equals: set[str] = set()
    prefixes: list[str] = []

    pattern_eq = re.compile(r"F\.data\s*==\s*([\"'])(.+?)\1")
    pattern_in = re.compile(r"F\.data\.in_\(\{([^}]+)\}\)")
    pattern_pref = re.compile(r"F\.data\.startswith\((['\"])(.+?)\1\)")

    for path in target.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in pattern_eq.finditer(text):
            equals.add(match.group(2))
        for match in pattern_in.finditer(text):
            for part in match.group(1).split(","):
                part = part.strip()
                if part and part not in {""}:
                    equals.add(part.strip("\"'"))
        for match in pattern_pref.finditer(text):
            prefixes.append(match.group(2))
    return equals, prefixes


def main() -> int:
    callbacks = sorted(_main_menu_callbacks())
    equals, prefixes = _handler_callbacks()

    missing = []
    for cb in callbacks:
        if cb in equals:
            continue
        if any(cb.startswith(pref) for pref in prefixes):
            continue
        missing.append(cb)

    if missing:
        print("Missing handlers for callbacks:")
        for item in missing:
            print(f"  - {item}")
        return 1

    print("Callbacks OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
