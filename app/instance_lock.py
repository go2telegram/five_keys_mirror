from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class AlreadyRunningError(RuntimeError):
    """Raised when another instance of the bot is already running."""

    def __init__(self, pid: Optional[int] = None) -> None:
        self.pid = pid
        message = "Bot is already running"
        if pid is not None:
            message = f"{message} (PID {pid})"
        super().__init__(message)


def _is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


@dataclass
class InstanceLock:
    path: Path
    acquired: bool = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        if self.path.exists():
            existing_pid = self._read_pid()
            if existing_pid is not None and _is_process_running(existing_pid):
                raise AlreadyRunningError(existing_pid)

        self.path.write_text(str(os.getpid()))
        self.acquired = True

    def release(self) -> None:
        if not self.acquired:
            return

        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        finally:
            self.acquired = False

    def __enter__(self) -> "InstanceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    def _read_pid(self) -> Optional[int]:
        try:
            content = self.path.read_text().strip()
        except OSError:
            return None

        if not content:
            return None

        try:
            return int(content)
        except ValueError:
            return None
