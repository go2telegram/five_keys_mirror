"""Networking utilities for the collaborative multi-agent layer."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple

import httpx
from aiohttp import web

from .protocol import (
    AgentMessage,
    AgentPeer,
    ConsensusEngine,
    ConsensusOutcome,
    MessageKind,
    aggregate_responses,
    parse_peers,
)

TaskExecutor = Callable[[str, Mapping[str, Any]], Awaitable[str]]


@dataclass
class TaskRecord:
    """Keeps audit information about a distributed task."""

    task_id: str
    owner: Optional[str]
    task: str
    context: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    responses: Dict[str, str] = field(default_factory=dict)
    result: Optional[str] = None
    finalized_at: Optional[float] = None
    status: str = "pending"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "owner": self.owner,
            "task": self.task,
            "context": self.context,
            "created_at": self.created_at,
            "responses": dict(self.responses),
            "result": self.result,
            "finalized_at": self.finalized_at,
            "status": self.status,
        }


class AgentNetwork:
    """Coordinates task exchange between neighbouring agents."""

    def __init__(
        self,
        *,
        agent_id: str,
        peers: List[AgentPeer] | None = None,
        executor: Optional[TaskExecutor] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        consensus_engine: Optional[ConsensusEngine] = None,
        consensus_participants: Optional[int] = None,
    ) -> None:
        self.agent_id = agent_id
        self._peers: Dict[str, AgentPeer] = {peer.identifier: peer for peer in peers or []}
        self._executor = executor
        self._client = http_client or httpx.AsyncClient(timeout=10.0)
        self._client_owner = http_client is None
        self._consensus = consensus_engine or ConsensusEngine(aggregate_responses)
        self._lock = asyncio.Lock()
        self._tasks: Dict[str, TaskRecord] = {}
        self._consensus_participants = consensus_participants or (len(self._peers) + 1)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_settings(cls, settings: Any, *, executor: Optional[TaskExecutor] = None) -> "AgentNetwork":
        raw_peers = getattr(settings, "AGENT_NEIGHBORS", "") or ""
        peers = parse_peers(raw_peers)
        consensus_participants = len(peers) + 1
        network = cls(
            agent_id=getattr(settings, "AGENT_ID", "agent"),
            peers=peers,
            executor=executor,
            consensus_participants=consensus_participants,
        )
        return network

    # ------------------------------------------------------------------
    # Properties and state inspection
    # ------------------------------------------------------------------
    @property
    def peers(self) -> List[AgentPeer]:
        return list(self._peers.values())

    @property
    def participants(self) -> int:
        return max(self._consensus_participants, 1)

    def set_participants(self, value: int) -> None:
        self._consensus_participants = max(value, 1)

    def register_executor(self, executor: TaskExecutor) -> None:
        self._executor = executor

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 5) -> List[TaskRecord]:
        records = sorted(self._tasks.values(), key=lambda rec: rec.created_at, reverse=True)
        return records[:limit]

    def peers_snapshot(self) -> List[Dict[str, Any]]:
        snapshot: List[Dict[str, Any]] = []
        for peer in self._peers.values():
            snapshot.append(
                {
                    "id": peer.identifier,
                    "endpoint": peer.endpoint,
                    "healthy": peer.healthy,
                    "last_seen": peer.last_seen,
                    "last_error": peer.last_error,
                }
            )
        return snapshot

    # ------------------------------------------------------------------
    # Core functionality
    # ------------------------------------------------------------------
    async def broadcast_task(self, task: str, context: Optional[Mapping[str, Any]] = None) -> str:
        task_id = uuid.uuid4().hex
        payload = {"task": task, "context": dict(context or {}), "owner": self.agent_id}
        message = AgentMessage(kind=MessageKind.TASK, sender=self.agent_id, task_id=task_id, payload=payload)
        async with self._lock:
            self._consensus.expect(task_id, owner=self.agent_id, participants=self.participants, task=task, context=payload["context"])
            self._ensure_task_record(task_id, owner=self.agent_id, task=task, context=payload["context"])
        await self._broadcast(message)
        await self._execute_task(message)
        return task_id

    async def dispatch_task(self, task: str, context: Optional[Mapping[str, Any]] = None, timeout: float = 30.0) -> Tuple[str, str]:
        task_id = await self.broadcast_task(task, context)
        result = await self.wait_for_consensus(task_id, timeout=timeout)
        if result is None:
            raise RuntimeError("Consensus did not produce a result")
        return task_id, result

    async def wait_for_consensus(self, task_id: str, timeout: float = 30.0) -> Optional[str]:
        state = self._consensus.get(task_id)
        if state is None:
            return None
        try:
            await asyncio.wait_for(state.event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        return state.final_result

    async def submit_result(
        self,
        task_id: str,
        result: str,
        *,
        owner: Optional[str],
        task: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> ConsensusOutcome:
        async with self._lock:
            state = self._consensus.expect(task_id, owner=owner, participants=self.participants, task=task or "", context=context or {})
            record = self._ensure_task_record(task_id, owner=state.owner, task=state.task, context=state.context)
            outcome = self._consensus.register_response(task_id, self.agent_id, result)
            record.responses[self.agent_id] = result
            if outcome.ready and outcome.result is not None:
                record.status = "consensus"
                record.result = outcome.result
                record.finalized_at = time.time()
        await self._notify_result(task_id, result, owner=owner)
        if outcome.ready and outcome.result and not outcome.already_final:
            await self._broadcast_consensus(task_id, outcome.result, owner=owner or state.owner)
        return outcome

    async def handle_exchange(self, message: AgentMessage) -> Dict[str, Any]:
        if message.kind is MessageKind.TASK:
            return await self._handle_task_message(message)
        if message.kind is MessageKind.RESULT:
            return await self._handle_result_message(message)
        if message.kind is MessageKind.CONSENSUS:
            return await self._handle_consensus_message(message)
        return {"ok": False, "error": "unsupported_kind"}

    async def aiohttp_handler(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        try:
            message = AgentMessage.from_dict(data)
        except Exception as exc:  # pragma: no cover - invalid envelope guard
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        result = await self.handle_exchange(message)
        return web.json_response(result)

    async def close(self) -> None:
        if self._client_owner:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _broadcast(self, message: AgentMessage) -> None:
        tasks = [self._send_to_peer(peer, message) for peer in self._peers.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _broadcast_consensus(self, task_id: str, result: str, *, owner: Optional[str]) -> None:
        payload = {"result": result, "owner": owner}
        message = AgentMessage(kind=MessageKind.CONSENSUS, sender=self.agent_id, task_id=task_id, payload=payload)
        await self._broadcast(message)

    async def _notify_result(self, task_id: str, result: str, *, owner: Optional[str]) -> None:
        payload = {"result": result, "owner": owner}
        message = AgentMessage(kind=MessageKind.RESULT, sender=self.agent_id, task_id=task_id, payload=payload)
        await self._broadcast(message)

    async def _send_to_peer(self, peer: AgentPeer, message: AgentMessage) -> None:
        url = peer.endpoint.rstrip("/") + "/agent_exchange"
        try:
            response = await self._client.post(url, json=message.to_dict())
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network errors in integration tests
            peer.mark_failure(str(exc))
        else:
            peer.mark_success()

    async def _execute_task(self, message: AgentMessage) -> None:
        if not self._executor:
            return
        payload = message.payload
        task = payload.get("task", "")
        context = payload.get("context", {})
        owner = payload.get("owner")
        try:
            result = await self._executor(task, context)
        except Exception as exc:  # pragma: no cover - executor failure is reported as result
            result = f"⚠️ executor error: {exc}"
        await self.submit_result(message.task_id, result, owner=owner, task=task, context=context)

    async def _handle_task_message(self, message: AgentMessage) -> Dict[str, Any]:
        payload = message.payload
        owner = payload.get("owner", message.sender)
        task = payload.get("task", "")
        context = payload.get("context", {})
        async with self._lock:
            self._consensus.expect(message.task_id, owner=owner, participants=self.participants, task=task, context=context)
            self._ensure_task_record(message.task_id, owner=owner, task=task, context=context)
        asyncio.create_task(self._execute_task(message))
        return {"ok": True, "task_id": message.task_id}

    async def _handle_result_message(self, message: AgentMessage) -> Dict[str, Any]:
        payload = message.payload
        owner = payload.get("owner")
        result = payload.get("result", "")
        async with self._lock:
            state = self._consensus.expect(message.task_id, owner=owner, participants=self.participants, task="", context={})
            record = self._ensure_task_record(message.task_id, owner=state.owner, task=state.task, context=state.context)
            record.responses[message.sender] = result
            outcome = self._consensus.register_response(message.task_id, message.sender, result)
            if outcome.ready and outcome.result is not None and not outcome.already_final:
                record.status = "consensus"
                record.result = outcome.result
                record.finalized_at = time.time()
        if outcome.ready and outcome.result and not outcome.already_final:
            await self._broadcast_consensus(message.task_id, outcome.result, owner=owner)
        return {"ok": True, "status": "recorded", "ready": outcome.ready}

    async def _handle_consensus_message(self, message: AgentMessage) -> Dict[str, Any]:
        payload = message.payload
        result = payload.get("result", "")
        owner = payload.get("owner")
        async with self._lock:
            state = self._consensus.accept_final(message.task_id, result)
            record = self._ensure_task_record(message.task_id, owner=state.owner or owner, task=state.task, context=state.context)
            record.status = "consensus"
            record.result = state.final_result
            record.finalized_at = state.finalized_at
        return {"ok": True, "status": "synced"}

    def _ensure_task_record(self, task_id: str, *, owner: Optional[str], task: str, context: Mapping[str, Any]) -> TaskRecord:
        record = self._tasks.get(task_id)
        if record is None:
            record = TaskRecord(task_id=task_id, owner=owner, task=task, context=dict(context))
            self._tasks[task_id] = record
        else:
            if owner and not record.owner:
                record.owner = owner
            if task and not record.task:
                record.task = task
            if context:
                record.context.update(dict(context))
        return record


def create_default_executor(agent_id: str, generator: Optional[Callable[[str], Awaitable[str]]] = None) -> TaskExecutor:
    """Return a simple deterministic task executor."""

    if generator is not None:
        async def _executor(task: str, context: Mapping[str, Any]) -> str:
            prompt = context.get("prompt") or task
            return await generator(prompt)

        return _executor

    async def _executor(task: str, context: Mapping[str, Any]) -> str:
        topic = context.get("topic") or context.get("title")
        if topic:
            return f"{topic}: {task} — анализ агента {agent_id}"
        return f"{task} — анализ агента {agent_id}"

    return _executor
