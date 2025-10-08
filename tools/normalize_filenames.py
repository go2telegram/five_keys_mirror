#!/usr/bin/env python3
"""Normalize image filenames to ASCII slugs without collisions."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slugify import slugify  # noqa: E402


def _normalize_for_output(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    return str(relative).replace("\\", "/")


@dataclass(frozen=True)
class PlannedRename:
    source: Path
    target: Path
    collision_index: int
    base_slug: str

    def as_report_entry(self, root: Path) -> dict[str, object]:
        return {
            "source": _normalize_for_output(self.source, root),
            "target": _normalize_for_output(self.target, root),
            "collision_index": self.collision_index,
            "base_slug": self.base_slug,
        }


@dataclass(frozen=True)
class NormalizationPlan:
    images_dir: Path
    renames: list[PlannedRename]
    total_files: int

    @property
    def collisions(self) -> int:
        return sum(1 for rename in self.renames if rename.collision_index > 0)


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
    parser.add_argument(
        "--report",
        type=Path,
        help="Write a JSON report with the planned actions to this path.",
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


def _generate_new_name(path: Path, taken: set[str]) -> tuple[str, str, int]:
    stem, suffix = _split_name(path)
    base_slug = _slugify_name(stem)
    index = 0
    while True:
        suffix_part = "" if index == 0 else f"-{index}"
        candidate = f"{base_slug}{suffix_part}{suffix}"
        if candidate not in taken:
            return candidate, base_slug, index
        index += 1


def build_plan(images_dir: Path) -> NormalizationPlan:
    images_dir = images_dir.resolve()
    if not images_dir.exists() or not images_dir.is_dir():
        raise ValueError(f"Images directory does not exist: {images_dir}")

    files_by_directory: dict[Path, list[Path]] = defaultdict(list)
    for file in sorted(images_dir.rglob("*")):
        if file.is_file():
            files_by_directory[file.parent].append(file)

    renames: list[PlannedRename] = []
    for directory in sorted(files_by_directory):
        files = sorted(files_by_directory[directory], key=lambda item: item.name)
        taken: set[str] = {file.name for file in files}
        for file in files:
            taken.discard(file.name)
            new_name, base_slug, collision_index = _generate_new_name(file, taken)
            taken.add(new_name)
            if new_name != file.name:
                renames.append(
                    PlannedRename(
                        source=file,
                        target=file.with_name(new_name),
                        collision_index=collision_index,
                        base_slug=base_slug,
                    )
                )
    total_files = sum(len(files) for files in files_by_directory.values())
    return NormalizationPlan(images_dir=images_dir, renames=renames, total_files=total_files)


def _apply_plan(plan: NormalizationPlan) -> None:
    temporary_paths: list[tuple[Path, Path]] = []
    for index, rename in enumerate(plan.renames):
        source = rename.source
        target = rename.target
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


def _build_report(plan: NormalizationPlan, *, applied: bool) -> dict[str, object]:
    return {
        "images_dir": str(plan.images_dir),
        "total_files": plan.total_files,
        "planned_renames": len(plan.renames),
        "collisions": plan.collisions,
        "applied": applied,
        "renames": [rename.as_report_entry(plan.images_dir) for rename in plan.renames],
    }


def _write_report(path: Path, plan: NormalizationPlan, *, applied: bool) -> None:
    payload = _build_report(plan, applied=applied)
    path = path.expanduser()
    if parent := path.parent:
        parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report written to {path}")


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        plan = build_plan(args.images_dir)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    if not plan.renames:
        print("No changes needed.")
        if args.report:
            _write_report(args.report, plan, applied=False)
        return 0

    print("Planned renames:")
    for rename in plan.renames:
        source_rel = _normalize_for_output(rename.source, plan.images_dir)
        target_rel = _normalize_for_output(rename.target, plan.images_dir)
        note = ""
        if rename.collision_index:
            note = f"  [collision resolved as -{rename.collision_index}]"
        print(f"{source_rel} -> {target_rel}{note}")

    print(f"Total files scanned: {plan.total_files}")
    if plan.collisions:
        print(
            f"Planned renames: {len(plan.renames)} (collisions resolved: {plan.collisions})"
        )
    else:
        print(f"Planned renames: {len(plan.renames)}")

    if args.dry_run:
        print("Dry run: no changes applied.")
        if args.report:
            _write_report(args.report, plan, applied=False)
        return 0

    _apply_plan(plan)
    print(f"Renames complete: {len(plan.renames)} files updated.")
    if plan.collisions:
        print(f"Collisions resolved: {plan.collisions}")
    if args.report:
        _write_report(args.report, plan, applied=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
