"""Validate that quiz assets referenced in YAML exist and are non-empty."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - optional dependency guard
    yaml = None  # type: ignore[assignment]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "app" / "quiz" / "data"
IMAGE_ROOT = PROJECT_ROOT / "app" / "static" / "images" / "quiz"
QUIZ_IMAGE_MODE = os.getenv("QUIZ_IMAGE_MODE", "remote").strip().lower()


def main() -> int:
    if yaml is None:
        print("WARN PyYAML is not installed; skipping quiz asset validation.")
        return 0

    if not DATA_DIR.exists():
        print(f"WARN No quiz data directory found at {DATA_DIR}")
        return 0

    total_files = 0
    missing = 0

    for yaml_path in sorted(DATA_DIR.glob("*.yaml")):
        with yaml_path.open(encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh) or {}

        quiz_name = yaml_path.stem

        cover = data.get("cover")
        missing += _check_asset(quiz_name, "cover", cover)
        if cover:
            total_files += 1

        for question in data.get("questions", []) or []:
            qid = question.get("id", "<unknown>")
            image_path = question.get("image")
            missing += _check_asset(quiz_name, f"question {qid}", image_path)
            if image_path:
                total_files += 1

    print(
        f"Quiz asset validation completed. Checked {total_files} referenced "
        f"files, {missing} issues found."
    )
    return 0


def _check_asset(quiz: str, label: str, path_str: str | None) -> int:
    if not path_str:
        print(f"WARN [{quiz}] {label}: no image path provided")
        return 1

    normalized = str(path_str).strip()
    if QUIZ_IMAGE_MODE != "local":
        if normalized.startswith("http://") or normalized.startswith("https://"):
            return 0
        # относительный путь в remote-режиме — будет отправлен по URL
        if not Path(normalized).is_absolute():
            return 0

    raw = Path(normalized)
    candidates: list[Path] = []

    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(PROJECT_ROOT / raw)
        if raw.parts[:4] == ("app", "static", "images", "quiz"):
            candidates.append(PROJECT_ROOT / Path(*raw.parts))
        normalized = _normalize_relative(raw)
        candidates.append(IMAGE_ROOT / normalized)
        candidates.extend(_flexible_variants(normalized))

    for candidate in candidates:
        if candidate.exists():
            try:
                size = candidate.stat().st_size
            except OSError as exc:
                print(f"WARN [{quiz}] {label}: cannot access {candidate} ({exc})")
                return 1
            if size <= 0:
                print(f"WARN [{quiz}] {label}: file is empty at {candidate}")
                return 1
            return 0

    print(f"WARN [{quiz}] {label}: file not found (searched {len(candidates)} locations)")
    return 1


def _normalize_relative(path: Path) -> Path:
    if path.is_absolute():
        try:
            return path.relative_to(IMAGE_ROOT)
        except ValueError:
            try:
                return path.relative_to(PROJECT_ROOT)
            except ValueError:
                return Path(path.name)

    parts = path.parts
    if len(parts) >= 4 and parts[:4] == ("app", "static", "images", "quiz"):
        return Path(*parts[4:])
    return path


def _flexible_variants(relative: Path) -> list[Path]:
    results: list[Path] = []
    stem = relative.stem if relative.suffix else relative.name
    parent = IMAGE_ROOT / relative.parent if relative.parent != Path(".") else IMAGE_ROOT
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        results.append(parent / f"{stem}{ext}")
    return results


if __name__ == "__main__":
    sys.exit(main())

