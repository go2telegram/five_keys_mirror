"""Generate build metadata module."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BUILD_MODULE_PATH = Path("app/build_info.py")


def _git_output(*args: str) -> str:
    try:
        result = subprocess.check_output(args, stderr=subprocess.DEVNULL)
        return result.decode().strip()
    except Exception:  # pragma: no cover - fallback when git unavailable
        return "unknown"


def _detect_branch() -> str:
    branch = _git_output("git", "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD" or not branch:
        branch = _git_output("git", "describe", "--tags", "--always")
    return branch or "unknown"


def _detect_commit() -> str:
    commit = _git_output("git", "rev-parse", "HEAD")
    return commit or "unknown"


def _detect_version() -> str:
    version = _git_output("git", "describe", "--tags", "--always")
    return version or "unknown"


def _build_time() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main() -> None:
    branch = _detect_branch()
    commit = _detect_commit()
    version = _detect_version()
    build_time = _build_time()

    content = (
        '"""Auto-generated build metadata."""\n\n'
        f"VERSION = {json.dumps(version)}\n"
        f"GIT_BRANCH = {json.dumps(branch)}\n"
        f"GIT_COMMIT = {json.dumps(commit)}\n"
        f"BUILD_TIME = {json.dumps(build_time)}\n"
        "BUILD = {\n"
        f"    \"version\": {json.dumps(version)},\n"
        f"    \"commit\": {json.dumps(commit)},\n"
        f"    \"timestamp\": {json.dumps(build_time)},\n"
        "}\n"
    )

    BUILD_MODULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BUILD_MODULE_PATH.write_text(content, encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    main()
