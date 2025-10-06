"""Handlers package with plugin auto-registration."""
from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterable
from typing import Any

from aiogram import Dispatcher, Router

__all__ = ["register_plugins"]


def _iter_module_routers(module: Any) -> Iterable[Router]:
    maybe_single = getattr(module, "router", None)
    if isinstance(maybe_single, Router):
        yield maybe_single

    maybe_many = getattr(module, "routers", None)
    if isinstance(maybe_many, Iterable) and not isinstance(maybe_many, (str, bytes)):
        for item in maybe_many:
            if isinstance(item, Router):
                yield item

    getter = getattr(module, "get_routers", None)
    if callable(getter):
        routers = getter()
        if isinstance(routers, Router):
            yield routers
        elif isinstance(routers, Iterable) and not isinstance(routers, (str, bytes)):
            for item in routers:
                if isinstance(item, Router):
                    yield item


def register_plugins(dp: Dispatcher) -> None:
    """Auto-discover handler routers and register them in the dispatcher."""
    seen: set[int] = set()
    package_path = __name__

    for module_info in pkgutil.walk_packages(__path__, prefix=f"{package_path}."):
        module = importlib.import_module(module_info.name)
        for router in _iter_module_routers(module):
            router_id = id(router)
            if router_id in seen:
                continue
            dp.include_router(router)
            seen.add(router_id)
