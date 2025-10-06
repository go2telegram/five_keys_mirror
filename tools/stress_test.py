#!/usr/bin/env python3
"""Async stress-test runner for five_keys_bot."""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Sequence

try:  # pragma: no cover - optional dependency for richer metrics
    import psutil  # type: ignore
except Exception:  # pragma: no cover - psutil is optional
    psutil = None


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@dataclass(slots=True)
class StressLimits:
    """Thresholds for the stress test to succeed."""

    max_duration: float
    max_avg_latency: float


@dataclass(slots=True)
class StressResult:
    """Aggregated metrics produced by the stress test."""

    total_updates: int
    total_time: float
    latencies: list[float]
    errors: list[str]
    cpu_percent: float | None
    memory_mb: float | None

    @property
    def avg_latency(self) -> float:
        return statistics.fmean(self.latencies) if self.latencies else 0.0


async def _run_stress(
    total_updates: int,
    concurrency: int,
    commands: Sequence[str],
    limits: StressLimits,
) -> StressResult:
    """Execute the stress scenario and collect metrics."""

    if not commands:
        raise ValueError("commands list cannot be empty")

    # Late imports so CLI overrides can inject env vars prior to loading settings.
    from aiogram import Dispatcher
    from aiogram.client.bot import Bot
    from aiogram.client.session.base import BaseSession
    from aiogram.enums import ChatType
    from aiogram.types import Chat, Message, Update, User

    from app.config import settings
    from app.db.session import init_db_safe
    from app.handlers import register_plugins
    from app.middlewares import register_middlewares
    from app.notifications import admin_notifier
    from app.products import sync_products

    # SQLite will be used automatically when DATABASE_URL is not provided.
    await init_db_safe(max_attempts=1)
    await sync_products()

    class DummySession(BaseSession):
        """Minimal session that short-circuits Telegram API calls."""

        def __init__(self) -> None:
            super().__init__()
            self._message_id = 0

        async def close(self) -> None:
            return None

        async def make_request(self, bot: Bot, method, timeout: int | None = None):  # type: ignore[override]
            from aiogram.methods import TelegramMethod
            from aiogram.types import Message as AiogramMessage

            if isinstance(method, TelegramMethod):  # pragma: no branch - simple guard
                result_type = getattr(method, "__returning__", None)
                if result_type is bool:
                    return True
                try:
                    is_message = isinstance(result_type, type) and issubclass(result_type, AiogramMessage)
                except TypeError:  # pragma: no cover - typing corner cases
                    is_message = False
                if is_message:
                    self._message_id += 1
                    chat_id = getattr(method, "chat_id", 0)
                    text = getattr(method, "text", "")
                    chat = Chat.model_construct(id=chat_id, type=ChatType.PRIVATE)
                    msg = AiogramMessage.model_construct(
                        message_id=self._message_id,
                        date=datetime.now(timezone.utc),
                        chat=chat,
                        text=text,
                    )
                    return msg.as_(bot)
            return True

        async def stream_content(
            self,
            url: str,
            headers: dict[str, object] | None = None,
            timeout: int = 30,
            chunk_size: int = 65536,
            raise_for_status: bool = True,
        ) -> AsyncGenerator[bytes, None]:  # type: ignore[override]
            if False:  # pragma: no cover - generator stub
                yield b""
            return

    bot = Bot(token=settings.BOT_TOKEN, session=DummySession())
    admin_notifier.bind(bot)

    dp = Dispatcher()
    register_middlewares(dp)
    register_plugins(dp)

    start_time = time.perf_counter()
    latencies: list[float] = []
    errors: list[str] = []
    process = psutil.Process() if psutil else None
    if process:
        process.cpu_percent(interval=None)

    queue: asyncio.Queue[int] = asyncio.Queue()
    for idx in range(total_updates):
        queue.put_nowait(idx)

    lock = asyncio.Lock()

    def build_update(update_id: int, user_seed: int, command: str) -> Update:
        user_id = 10_000 + user_seed
        user = User.model_construct(
            id=user_id,
            is_bot=False,
            first_name=f"Tester{user_seed}",
            username=f"tester{user_seed}",
        )
        chat = Chat.model_construct(id=user_id, type=ChatType.PRIVATE)
        message = Message.model_construct(
            message_id=update_id + 1,
            date=datetime.now(timezone.utc),
            chat=chat,
            from_user=user,
            text=command,
        ).as_(bot)
        return Update.model_construct(update_id=update_id, message=message).as_(bot)

    async def worker() -> None:
        while True:
            try:
                idx = queue.get_nowait()
            except asyncio.QueueEmpty:
                return

            command = commands[idx % len(commands)]
            update = build_update(idx, idx, command)
            started = time.perf_counter()
            try:
                await dp.feed_update(bot, update)
            except Exception as exc:  # noqa: BLE001 - surfaced in aggregate below
                async with lock:
                    errors.append(f"#{idx} {command}: {exc}")
            else:
                elapsed = time.perf_counter() - started
                async with lock:
                    latencies.append(elapsed)
            finally:
                queue.task_done()

    tasks = [asyncio.create_task(worker()) for _ in range(min(concurrency, total_updates))]
    await queue.join()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    total_time = time.perf_counter() - start_time
    cpu_percent = process.cpu_percent(interval=None) if process else None
    memory_mb = (process.memory_info().rss / (1024 ** 2)) if process else None

    await bot.session.close()

    result = StressResult(
        total_updates=total_updates,
        total_time=total_time,
        latencies=latencies,
        errors=errors,
        cpu_percent=cpu_percent,
        memory_mb=memory_mb,
    )

    verdict_messages: list[str] = []
    if result.errors:
        verdict_messages.append(f"Encountered {len(result.errors)} errors during processing")
    if result.total_time > limits.max_duration:
        verdict_messages.append(
            f"Total duration {result.total_time:.3f}s exceeded limit {limits.max_duration:.3f}s",
        )
    if result.avg_latency > limits.max_avg_latency:
        verdict_messages.append(
            f"Average latency {result.avg_latency * 1000:.1f}ms exceeded limit {limits.max_avg_latency * 1000:.1f}ms",
        )

    status = "PASSED" if not verdict_messages else "FAILED"
    print("Stress test", status)
    print(f"  Updates processed: {result.total_updates}")
    print(f"  Concurrency: {min(concurrency, total_updates)}")
    print(f"  Total time: {result.total_time:.3f}s")
    if result.latencies:
        print(f"  Avg latency: {result.avg_latency * 1000:.2f}ms")
        print(f"  Max latency: {max(result.latencies) * 1000:.2f}ms")
    if result.cpu_percent is not None:
        print(f"  CPU usage: {result.cpu_percent:.1f}%")
    if result.memory_mb is not None:
        print(f"  RSS memory: {result.memory_mb:.1f} MiB")
    if result.errors:
        print("  Errors:")
        for entry in result.errors[:10]:
            print(f"    - {entry}")
        if len(result.errors) > 10:
            print(f"    … and {len(result.errors) - 10} more")

    if verdict_messages:
        for message in verdict_messages:
            print(f"❌ {message}")
        raise SystemExit(1)

    return result


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a synthetic stress-test against five_keys_bot handlers")
    parser.add_argument("--updates", type=int, default=100, help="Number of updates to send (default: 100)")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="How many concurrent workers to spawn (default: 10)",
    )
    parser.add_argument(
        "--commands",
        default="/start,/panel",
        help="Comma-separated list of commands to cycle through",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=10.0,
        help="Fail if total processing time exceeds this number of seconds (default: 10)",
    )
    parser.add_argument(
        "--max-avg-latency",
        type=float,
        default=0.2,
        help="Fail if average latency exceeds this many seconds (default: 0.2)",
    )
    parser.add_argument("--bot-token", help="Override BOT_TOKEN environment variable")
    parser.add_argument(
        "--admin-id",
        type=int,
        help="Override ADMIN_ID environment variable",
    )
    parser.add_argument(
        "--callback-secret",
        help="Override CALLBACK_SECRET environment variable (optional)",
    )
    return parser.parse_args(argv)


async def async_main(argv: Sequence[str]) -> StressResult:
    args = parse_args(argv)

    if args.bot_token:
        os.environ.setdefault("BOT_TOKEN", args.bot_token)
    if args.admin_id is not None:
        os.environ.setdefault("ADMIN_ID", str(args.admin_id))
    if args.callback_secret:
        os.environ.setdefault("CALLBACK_SECRET", args.callback_secret)
    os.environ.setdefault("CALLBACK_SECRET", "stress-panel-secret")

    missing = [name for name in ("BOT_TOKEN", "ADMIN_ID") if not os.environ.get(name)]
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(f"Missing required environment variables: {joined}")

    commands = [cmd.strip() for cmd in args.commands.split(",") if cmd.strip()]
    limits = StressLimits(max_duration=args.max_duration, max_avg_latency=args.max_avg_latency)
    return await _run_stress(args.updates, args.concurrency, commands, limits)


def main() -> None:
    asyncio.run(async_main(sys.argv[1:]))


if __name__ == "__main__":
    main()
