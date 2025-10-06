"""Utilities for collecting metrics from remote Five Keys nodes."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable, Sequence

import httpx


@dataclass(slots=True)
class NetworkNode:
    """Configuration for a Five Keys node participating in the network."""

    name: str
    base_url: str
    latitude: float | None = None
    longitude: float | None = None
    region: str | None = None
    metrics_path: str = "/metrics"

    def metrics_url(self) -> str:
        """Return the fully qualified metrics URL for the node."""

        if self.metrics_path.startswith("http"):
            return self.metrics_path
        base = self.base_url.rstrip("/")
        path = self.metrics_path if self.metrics_path.startswith("/") else f"/{self.metrics_path}"
        return f"{base}{path}"


class NetworkCollector:
    """Collects metrics from all configured nodes on a fixed interval."""

    def __init__(
        self,
        nodes: Sequence[NetworkNode],
        *,
        refresh_interval: int = 60,
        request_timeout: float = 5.0,
        user_agent: str = "five-keys-network-collector/1.0",
    ) -> None:
        self._nodes: Sequence[NetworkNode] = nodes
        self._refresh_interval = max(5, refresh_interval)
        self._request_timeout = request_timeout
        self._user_agent = user_agent

        self._client: httpx.AsyncClient | None = None
        self._snapshot: dict[str, Any] = {
            "generated_at": None,
            "summary": {
                "online_nodes": 0,
                "offline_nodes": 0,
                "metrics": {},
            },
            "nodes": [],
        }
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    @property
    def nodes(self) -> Sequence[NetworkNode]:
        return self._nodes

    async def start(self) -> None:
        """Start the background refresh loop."""

        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._request_timeout, headers={"User-Agent": self._user_agent})
        if self._task is None:
            self._task = asyncio.create_task(self._auto_refresh())
        await self.refresh()

    async def close(self) -> None:
        """Stop background tasks and release resources."""

        self._stopping.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._client:
            await self._client.aclose()
            self._client = None
        self._stopping.clear()

    async def _auto_refresh(self) -> None:
        try:
            while not self._stopping.is_set():
                await self.refresh()
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=self._refresh_interval)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass

    async def refresh(self) -> dict[str, Any]:
        """Fetch fresh metrics from every node and update the snapshot."""

        async with self._lock:
            results = await asyncio.gather(*[self._fetch_node(node) for node in self._nodes], return_exceptions=True)
            nodes_payload: list[dict[str, Any]] = []
            for node, result in zip(self._nodes, results):
                if isinstance(result, Exception):
                    nodes_payload.append(
                        {
                            "name": node.name,
                            "region": node.region,
                            "latitude": node.latitude,
                            "longitude": node.longitude,
                            "status": "offline",
                            "latency_ms": None,
                            "metrics": {},
                            "error": str(result),
                        }
                    )
                else:
                    nodes_payload.append(result)

            summary = self._build_summary(nodes_payload)
            snapshot = {
                "generated_at": datetime.now(tz=UTC).isoformat(),
                "summary": summary,
                "nodes": nodes_payload,
            }
            self._snapshot = snapshot
            return snapshot

    async def snapshot(self) -> dict[str, Any]:
        """Return the latest cached snapshot."""

        async with self._lock:
            return deepcopy(self._snapshot)

    async def _fetch_node(self, node: NetworkNode) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("NetworkCollector.start() must be called before collecting metrics")

        start = asyncio.get_running_loop().time()
        try:
            response = await self._client.get(node.metrics_url())
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - we intentionally handle all issues the same way
            return {
                "name": node.name,
                "region": node.region,
                "latitude": node.latitude,
                "longitude": node.longitude,
                "status": "offline",
                "latency_ms": None,
                "metrics": {},
                "error": str(exc),
            }

        latency = (asyncio.get_running_loop().time() - start) * 1000
        metrics = payload if isinstance(payload, dict) else {}

        return {
            "name": node.name,
            "region": node.region,
            "latitude": node.latitude,
            "longitude": node.longitude,
            "status": "online",
            "latency_ms": round(latency, 2),
            "metrics": metrics,
            "error": None,
        }

    def _build_summary(self, nodes: Iterable[dict[str, Any]]) -> dict[str, Any]:
        metrics_aggregates: dict[str, list[float]] = defaultdict(list)
        online = 0
        offline = 0

        for node in nodes:
            if node["status"] == "online":
                online += 1
                for key, value in (node.get("metrics") or {}).items():
                    if isinstance(value, (int, float)):
                        metrics_aggregates[key].append(float(value))
            else:
                offline += 1

        metrics_summary: dict[str, dict[str, float]] = {}
        for key, values in metrics_aggregates.items():
            if not values:
                continue
            metrics_summary[key] = {
                "avg": round(sum(values) / len(values), 2),
                "max": round(max(values), 2),
                "min": round(min(values), 2),
            }

        return {
            "online_nodes": online,
            "offline_nodes": offline,
            "metrics": metrics_summary,
        }
