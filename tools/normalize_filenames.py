#!/usr/bin/env python3
"""Normalize image filenames to ASCII slugs without collisions."""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slugify import slugify  # noqa: E402


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--images-dir",
        required=True,
        type=Path,
        help="Directory that contains images to normalize.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only display the planned renames without changing files.",
    )
    return parser.parse_args(argv)


def _slugify_name(name: str) -> str:
    slug = slugify(name, lowercase=True, language="ru")
    return slug or "unnamed"


def _split_name(path: Path) -> tuple[str, str]:
    suffix = "".join(path.suffixes).lower()
    if suffix:
        stem = path.name[: -len(suffix)]
    else:
        stem = path.name
    return stem, suffix


def _generate_new_name(path: Path, taken: set[str]) -> str:
    stem, suffix = _split_name(path)
    base_slug = _slugify_name(stem)
    index = 0
    while True:
        suffix_part = "" if index == 0 else f"-{index}"
        candidate = f"{base_slug}{suffix_part}{suffix}"
        if candidate not in taken:
            return candidate
        index += 1


def build_plan(images_dir: Path) -> list[tuple[Path, Path]]:
    if not images_dir.exists() or not images_dir.is_dir():
        raise ValueError(f"Images directory does not exist: {images_dir}")

    files_by_directory: dict[Path, list[Path]] = defaultdict(list)
    for file in sorted(images_dir.rglob("*")):
        if file.is_file():
            files_by_directory[file.parent].append(file)

    plan: list[tuple[Path, Path]] = []
    for directory in sorted(files_by_directory):
        files = sorted(files_by_directory[directory], key=lambda item: item.name)
        taken: set[str] = {file.name for file in files}
        for file in files:
            taken.discard(file.name)
            new_name = _generate_new_name(file, taken)
            taken.add(new_name)
            if new_name != file.name:
                plan.append((file, file.with_name(new_name)))
    return plan


def _apply_plan(plan: list[tuple[Path, Path]]) -> None:
    temporary_paths: list[tuple[Path, Path]] = []
    for index, (source, target) in enumerate(plan):
        temp_name = f"__tmp_normalize__{uuid.uuid4().hex}_{index}{source.suffix}"
        temp_path = source.with_name(temp_name)
        while temp_path.exists():
            temp_name = f"__tmp_normalize__{uuid.uuid4().hex}_{index}{source.suffix}"
            temp_path = source.with_name(temp_name)
        source.rename(temp_path)
        temporary_paths.append((temp_path, target))

    for temp_path, target in temporary_paths:
        if target.exists():
            raise RuntimeError(f"Cannot rename {temp_path} to {target}: target already exists")
        temp_path.rename(target)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        plan = build_plan(args.images_dir)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    if not plan:
        print("No changes needed.")
        return 0

    print("Planned renames:")
    for source, target in plan:
        try:
            source_rel = source.relative_to(args.images_dir)
            target_rel = target.relative_to(args.images_dir)
        except ValueError:
            source_rel = source
            target_rel = target
        print(f"{source_rel} -> {target_rel}")

    if args.dry_run:
        return 0

    _apply_plan(plan)
    print("Renames complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
