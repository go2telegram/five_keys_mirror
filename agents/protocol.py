"""Low level protocol primitives for the multi-agent collaboration layer."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Optional


class MessageKind(str, Enum):
    """Available kinds of agent-to-agent messages."""

    TASK = "task"
    RESULT = "result"
    CONSENSUS = "consensus"
    HEARTBEAT = "heartbeat"


@dataclass(slots=True)
class AgentMessage:
    """Envelope that is exchanged between agents."""

    kind: MessageKind
    sender: str
    task_id: str
    payload: Dict[str, Any]
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=lambda: time.time())

    def __post_init__(self) -> None:
        if isinstance(self.kind, str):
            self.kind = MessageKind(self.kind)
        self.timestamp = float(self.timestamp)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "sender": self.sender,
            "task_id": self.task_id,
            "payload": self.payload,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AgentMessage":
        return cls(
            kind=MessageKind(data["kind"]),
            sender=str(data["sender"]),
            task_id=str(data["task_id"]),
            payload=dict(data.get("payload", {})),
            message_id=str(data.get("message_id") or uuid.uuid4().hex),
            timestamp=float(data.get("timestamp") or time.time()),
        )

    @classmethod
    def from_json(cls, raw: str) -> "AgentMessage":
        return cls.from_dict(json.loads(raw))


@dataclass(slots=True)
class AgentPeer:
    """Information about a neighbouring agent."""

    identifier: str
    endpoint: str
    healthy: bool = False
    last_seen: Optional[float] = None
    last_error: Optional[str] = None

    def mark_success(self) -> None:
        self.healthy = True
        self.last_seen = time.time()
        self.last_error = None

    def mark_failure(self, error: str) -> None:
        self.healthy = False
        self.last_error = error
        self.last_seen = time.time()


Aggregator = Callable[["ConsensusState"], str]


@dataclass
class ConsensusOutcome:
    """Outcome of registering a response inside :class:`ConsensusState`."""

    ready: bool
    result: Optional[str]
    responses: Dict[str, str]
    missing: int
    already_final: bool = False


@dataclass
class ConsensusState:
    """Holds state for a distributed task until consensus is reached."""

    task_id: str
    owner: Optional[str]
    expected_participants: int
    task: str
    context: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    responses: Dict[str, str] = field(default_factory=dict)
    final_result: Optional[str] = None
    finalized_at: Optional[float] = None
    event: asyncio.Event = field(default_factory=asyncio.Event)

    def missing_participants(self) -> int:
        return max(self.expected_participants - len(self.responses), 0)

    def record_response(self, agent_id: str, response: str) -> None:
        self.responses[agent_id] = response

    def finalize(self, result: str) -> None:
        self.final_result = result
        self.finalized_at = time.time()
        if not self.event.is_set():
            self.event.set()


class ConsensusEngine:
    """Tracks distributed tasks and computes consensus for them."""

    def __init__(self, aggregator: Aggregator):
        self._aggregator = aggregator
        self._tasks: Dict[str, ConsensusState] = {}

    def expect(self, task_id: str, *, owner: Optional[str], participants: int, task: str, context: Optional[Mapping[str, Any]] = None) -> ConsensusState:
        state = self._tasks.get(task_id)
        if state is None:
            state = ConsensusState(
                task_id=task_id,
                owner=owner,
                expected_participants=max(participants, 1),
                task=task,
                context=dict(context or {}),
            )
            self._tasks[task_id] = state
            return state

        state.expected_participants = max(state.expected_participants, participants)
        if owner and not state.owner:
            state.owner = owner
        if task and not state.task:
            state.task = task
        if context:
            state.context.update(dict(context))
        return state

    def register_response(self, task_id: str, agent_id: str, response: str) -> ConsensusOutcome:
        state = self._tasks.get(task_id)
        if state is None:
            state = self.expect(task_id, owner=None, participants=1, task="", context={})
        if state.final_result is not None:
            return ConsensusOutcome(True, state.final_result, dict(state.responses), 0, already_final=True)

        state.record_response(agent_id, response)
        missing = state.missing_participants()

        if missing == 0 and state.responses:
            result = self._aggregator(state)
            state.finalize(result)
            return ConsensusOutcome(True, result, dict(state.responses), 0)

        return ConsensusOutcome(False, None, dict(state.responses), missing)

    def accept_final(self, task_id: str, result: str) -> ConsensusState:
        state = self._tasks.get(task_id)
        if state is None:
            state = self.expect(task_id, owner=None, participants=1, task="", context={})
        if not state.final_result:
            state.finalize(result)
        return state

    def get(self, task_id: str) -> Optional[ConsensusState]:
        return self._tasks.get(task_id)

    def forget(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)


def aggregate_responses(state: ConsensusState) -> str:
    """Default deterministic aggregation of agent responses."""

    lines: List[str] = []
    for agent_id in sorted(state.responses):
        lines.append(f"{agent_id}: {state.responses[agent_id]}")
    header = state.context.get("title") or state.task or "Consensus result"
    body = "\n".join(lines) if lines else "(no responses)"
    return f"🤝 {header}\n" + body


def parse_peers(raw: str) -> List[AgentPeer]:
    """Parse a comma-separated list of ``name=url`` pairs."""

    peers: List[AgentPeer] = []
    for chunk in [item.strip() for item in raw.split(",") if item.strip()]:
        if "=" in chunk:
            identifier, endpoint = chunk.split("=", 1)
        elif "://" in chunk:
            endpoint = chunk
            identifier = endpoint
        else:
            identifier = chunk
            endpoint = chunk
        peers.append(AgentPeer(identifier=identifier.strip(), endpoint=endpoint.strip()))
    return peers
