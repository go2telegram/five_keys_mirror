"""Utility helpers for collecting router topology information."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from aiogram import Router
from aiogram.dispatcher.event.handler import HandlerObject

__all__ = [
    "RouterSnapshot",
    "capture_router_map",
    "get_router_map",
    "write_router_map",
]


@dataclass
class HandlerSnapshot:
    callback: str
    filters: list[str]


@dataclass
class EventSnapshot:
    event: str
    handlers: list[HandlerSnapshot]


@dataclass
class RouterSnapshot:
    name: str
    handlers_count: int
    patterns: list[EventSnapshot]


_ROUTER_MAP: list[RouterSnapshot] = []


def _format_callback(handler: HandlerObject) -> str:
    callback = getattr(handler, "callback", None)
    if callback is None:
        return "<unknown>"
    module = getattr(callback, "__module__", "")
    qualname = getattr(callback, "__qualname__", repr(callback))
    if module:
        return f"{module}.{qualname}"
    return qualname


def _format_filters(handler: HandlerObject) -> list[str]:
    filters: list[str] = []
    for flt in getattr(handler, "filters", []) or []:
        name = getattr(flt, "__class__", type(flt)).__name__
        filters.append(name)
    return filters


def _build_event_snapshot(event: str, observer) -> EventSnapshot | None:
    handlers: list[HandlerSnapshot] = []
    for handler in getattr(observer, "handlers", []) or []:
        handlers.append(
            HandlerSnapshot(
                callback=_format_callback(handler),
                filters=_format_filters(handler),
            )
        )
    if not handlers:
        return None
    return EventSnapshot(event=event, handlers=handlers)


def _describe_router(router: Router) -> RouterSnapshot:
    patterns: list[EventSnapshot] = []
    handlers_count = 0
    for event, observer in (router.observers or {}).items():
        snapshot = _build_event_snapshot(event, observer)
        if snapshot is None:
            continue
        patterns.append(snapshot)
        handlers_count += len(snapshot.handlers)
    return RouterSnapshot(
        name=router.name or router.__class__.__name__,
        handlers_count=handlers_count,
        patterns=patterns,
    )


def capture_router_map(routers: Sequence[Router]) -> list[RouterSnapshot]:
    global _ROUTER_MAP
    _ROUTER_MAP = [_describe_router(router) for router in routers]
    return _ROUTER_MAP


def get_router_map() -> list[RouterSnapshot]:
    return list(_ROUTER_MAP)


def write_router_map(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable: list[dict[str, Any]] = []
    for router in _ROUTER_MAP:
        serializable.append(
            {
                "name": router.name,
                "handlers_count": router.handlers_count,
                "patterns": [
                    {
                        "event": event.event,
                        "handlers": [
                            {
                                "callback": handler.callback,
                                "filters": handler.filters,
                            }
                            for handler in event.handlers
                        ],
                    }
                    for event in router.patterns
                ],
            }
        )
    path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
