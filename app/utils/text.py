"""Text helpers for Telegram-safe Markdown output."""

from __future__ import annotations

from typing import Iterator


def split_md(text: str, limit: int = 3500) -> Iterator[str]:
    """Yield Markdown chunks that respect Telegram's message length limits."""

    if not text:
        return

    limit = max(limit, 1)
    lines = text.splitlines()
    chunk: list[str] = []
    length = 0

    for line in lines:
        line = line.rstrip()
        line_len = len(line)
        if length and length + 1 + line_len > limit:
            yield "\n".join(chunk).strip()
            chunk = []
            length = 0
        if line_len > limit:
            start = 0
            while start < line_len:
                end = min(start + limit, line_len)
                yield line[start:end]
                start = end
            continue
        if length:
            chunk.append(line)
            length += 1 + line_len
        else:
            chunk.append(line)
            length = line_len
    if chunk:
        yield "\n".join(chunk).strip()
