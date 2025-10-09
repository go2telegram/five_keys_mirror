"""Utilities for working with Markdown payloads."""

from __future__ import annotations


def split_md(text: str, limit: int = 3500) -> list[str]:
    """Split Markdown text into telegram-friendly chunks."""

    if limit <= 0:
        raise ValueError("limit must be positive")

    payload = (text or "").strip()
    if not payload:
        return []

    chunks: list[str] = []
    current = ""

    def _flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for block in payload.split("\n\n"):
        fragment = block.strip()
        if not fragment:
            candidate = current + ("\n\n" if current else "")
            if len(candidate) > limit:
                _flush()
            else:
                current = candidate
            continue

        candidate = fragment if not current else f"{current}\n\n{fragment}"
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            _flush()

        if len(fragment) <= limit:
            current = fragment
            continue

        # Hard split the fragment when it exceeds the limit.
        start = 0
        while start < len(fragment):
            piece = fragment[start : start + limit]
            if len(piece) == limit:
                chunks.append(piece)
            else:
                current = piece
            start += limit

    if current.strip():
        chunks.append(current.strip())

    return chunks


__all__ = ["split_md"]
