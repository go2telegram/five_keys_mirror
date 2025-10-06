"""Runtime helpers to expose the active agent network."""

from __future__ import annotations

from typing import Optional

from .network import AgentNetwork


_active_network: Optional[AgentNetwork] = None


def set_network(network: Optional[AgentNetwork]) -> None:
    global _active_network
    _active_network = network


def get_network() -> Optional[AgentNetwork]:
    return _active_network


def is_enabled() -> bool:
    return _active_network is not None
