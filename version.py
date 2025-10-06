"""Helpers for reporting the current build/version."""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache
def git_rev() -> str:
    """Return the current git revision or BUILD_SHA environment override."""
    build_sha = os.getenv("BUILD_SHA")
    if build_sha:
        return build_sha

    repo_root = Path(__file__).resolve().parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"
    return result.stdout.strip() or "unknown"
