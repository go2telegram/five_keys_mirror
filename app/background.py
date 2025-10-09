"""Simple in-process background queue for heavy asynchronous tasks."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Optional

Job = Callable[[], Awaitable[None]]


class BackgroundQueue:
    """A tiny asyncio-based worker pool backed by a FIFO queue."""

    def __init__(self, *, workers: int = 1) -> None:
        self._workers = max(1, workers)
        self._queue: asyncio.Queue[Optional[Job]] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []
        self._started = False
        self._log = logging.getLogger("background")

    @property
    def started(self) -> bool:
        return self._started

    async def start(self, workers: int | None = None) -> None:
        if workers is not None and workers > 0:
            self._workers = workers
        if self._started:
            return
        self._started = True
        for index in range(self._workers):
            task = asyncio.create_task(
                self._worker(),
                name=f"background-worker-{index+1}",
            )
            self._tasks.append(task)

    async def stop(self) -> None:
        if not self._started:
            return
        for _ in range(self._workers):
            await self._queue.put(None)
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        self._started = False
        self._queue = asyncio.Queue()

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            if job is None:
                self._queue.task_done()
                break
            try:
                await job()
            except Exception:  # pragma: no cover - defensive logging
                self._log.exception("background job failed")
            finally:
                self._queue.task_done()

    def submit(self, job: Job) -> bool:
        if not self._started:
            return False
        self._queue.put_nowait(job)
        return True


background_queue = BackgroundQueue(workers=2)


async def start_background_queue(workers: int | None = None) -> BackgroundQueue:
    await background_queue.start(workers=workers)
    return background_queue


async def stop_background_queue() -> None:
    await background_queue.stop()


__all__ = [
    "BackgroundQueue",
    "background_queue",
    "start_background_queue",
    "stop_background_queue",
]
