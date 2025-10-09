#!/usr/bin/env python3
"""Pre-commit hook to prevent committing generated artifacts."""

from __future__ import annotations

import sys
from pathlib import Path

BLOCKED_FILES = {
    Path("app/build_info.py"): "auto-generated build metadata (use tools/write_build_info.py instead)",
}

BLOCKED_PREFIXES = [
    (
        Path("alembic/versions"),
        "_alembic_tmp_",
        "temporary Alembic artifact — remove with /doctor?repair",
    ),
]


def main(argv: list[str]) -> int:
    repo_root = Path.cwd()
    problems: list[str] = []

    for arg in argv:
        path = Path(arg)
        if not path.is_absolute():
            path = repo_root / path
        try:
            rel_path = path.relative_to(repo_root)
        except ValueError:
            rel_path = Path(arg)

        reason = BLOCKED_FILES.get(rel_path)
        if reason:
            problems.append(f"- {rel_path}: {reason}")
            continue

        for prefix, name_prefix, prefix_reason in BLOCKED_PREFIXES:
            try:
                if rel_path.is_relative_to(prefix) and rel_path.name.startswith(name_prefix):
                    problems.append(f"- {rel_path}: {prefix_reason}")
                    break
            except AttributeError:
                # Python < 3.9 fallback (not expected, but keep safe)
                rel_parts = rel_path.parts
                prefix_parts = prefix.parts
                if rel_parts[: len(prefix_parts)] == prefix_parts and rel_path.name.startswith(name_prefix):
                    problems.append(f"- {rel_path}: {prefix_reason}")
                    break

    if problems:
        print("Commit blocked: remove generated artifacts before committing:")
        print("\n".join(problems))
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    sys.exit(main(sys.argv[1:]))
