"""Normalize product image filenames to slugified lowercase names."""

from __future__ import annotations

import argparse
from pathlib import Path

from slugify import slugify


def iter_files(root: Path) -> list[tuple[Path, Path]]:
    changes: list[tuple[Path, Path]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        new_name = slugify(path.stem, lowercase=True, language="ru")
        if not new_name:
            continue
        target = path.with_name(f"{new_name}{path.suffix.lower()}")
        if target != path:
            changes.append((path, target))
    return changes


def normalize(root: Path, apply: bool = False) -> list[tuple[Path, Path]]:
    changes = iter_files(root)
    if apply:
        for src, dst in changes:
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        default="app/static/images/products",
        help="каталог с изображениями (по умолчанию app/static/images/products)",
    )
    parser.add_argument("--apply", action="store_true", help="переименовать файлы вместо dry-run")
    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.exists():
        parser.error(f"Каталог {root} не найден")

    changes = normalize(root, apply=args.apply)
    if not changes:
        print("✔️ Все имена файлов уже нормализованы")
        return 0

    action = "Переименовано" if args.apply else "Нужно переименовать"
    print(f"{action} {len(changes)} файлов:")
    for src, dst in changes:
        print(f" - {src.name} → {dst.name}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
