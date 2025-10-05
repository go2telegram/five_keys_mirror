import asyncio
import sys
from pathlib import Path

from app.instance_lock import AlreadyRunningError, InstanceLock
from app.main import main


def run() -> None:
    lock = InstanceLock(Path(".run") / "bot.lock")
    try:
        with lock:
            asyncio.run(main())
    except AlreadyRunningError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(12) from exc


if __name__ == "__main__":
    run()
