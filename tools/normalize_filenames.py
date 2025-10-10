"""Normalize product image filenames to slugified lowercase names."""

from __future__ import annotations

import argparse
from collections import defaultdict
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


def _ensure_unique_targets(
    changes: list[tuple[Path, Path]],
) -> list[tuple[Path, Path]]:
    """Resolve collisions between desired rename targets."""

    rename_sources = {src for src, _ in changes}
    used_targets: set[Path] = set()
    counters: defaultdict[tuple[Path, str, str], int] = defaultdict(int)
    normalized: list[tuple[Path, Path]] = []

    for src, desired in changes:
        candidate = desired
        key = (desired.parent, desired.stem, desired.suffix)
        while True:
            conflict_with_plan = candidate in used_targets
            conflict_with_disk = (
                candidate.exists()
                and candidate not in rename_sources
                and candidate != src
            )
            if not conflict_with_plan and not conflict_with_disk:
                break
            counters[key] += 1
            suffix = counters[key]
            candidate = desired.with_name(f"{desired.stem}-{suffix}{desired.suffix}")

        used_targets.add(candidate)
        normalized.append((src, candidate))

    return normalized


def _stage_and_apply(changes: list[tuple[Path, Path]]) -> None:
    """Rename files via temporary names to avoid clobbering."""

    staged: list[tuple[Path, Path]] = []
    for index, (src, _) in enumerate(changes):
        temp_counter = index
        temp = src.with_name(f".__normalize_tmp_{temp_counter}{src.suffix}")
        while temp.exists():
            temp_counter += 1
            temp = src.with_name(f".__normalize_tmp_{temp_counter}{src.suffix}")
        src.rename(temp)
        staged.append((src, temp))

    for (_, dst), (_, temp) in zip(changes, staged):
        dst.parent.mkdir(parents=True, exist_ok=True)
        temp.rename(dst)


def normalize(root: Path, apply: bool = False) -> list[tuple[Path, Path]]:
    changes = iter_files(root)
    if not changes:
        return changes

    normalized_changes = _ensure_unique_targets(changes)

    if apply:
        _stage_and_apply(normalized_changes)

    return normalized_changes


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
