"""Meta-orchestrator for distributing tasks between cooperative agents.

The orchestrator keeps track of registered agents, pending tasks and the
assignment of jobs that are currently in-flight.  The goal is to ensure that the
load is spread evenly with respect to each agent capacity while honouring task
priorities.

The module exposes a singleton :data:`orchestrator_manager` that can be used by
other parts of the application (e.g. the admin tools or web handlers).
"""

from __future__ import annotations

import asyncio
import heapq
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(order=True)
class _QueuedTask:
    """Internal representation of a task waiting for an agent.

    The queue is implemented as a heap ordered primarily by *priority* (lower
    value means higher priority) and then by creation time to keep FIFO order for
    tasks with the same priority.
    """

    priority: int
    created_at: float
    task_id: str = field(compare=False)
    payload: Dict[str, Any] = field(compare=False, default_factory=dict)
    meta: Dict[str, Any] = field(compare=False, default_factory=dict)


@dataclass
class AssignedTask:
    """Public representation of a task that is currently processed."""

    task_id: str
    agent_id: str
    payload: Dict[str, Any]
    priority: int
    created_at: float
    assigned_at: float
    meta: Dict[str, Any]

    def in_progress_for(self) -> float:
        """Return how long (in seconds) the task has been processed."""

        return max(0.0, time.time() - self.assigned_at)

    def total_latency(self) -> float:
        """Return total latency since the task was created."""

        return max(0.0, time.time() - self.created_at)


@dataclass
class AgentState:
    """State of an orchestrator agent."""

    agent_id: str
    capacity: int = 1
    priority: int = 0
    active: bool = True
    assigned: Dict[str, AssignedTask] = field(default_factory=dict)
    last_heartbeat: float = field(default_factory=time.time)

    def has_capacity(self) -> bool:
        return self.active and len(self.assigned) < max(1, self.capacity)

    def utilisation(self) -> float:
        """Return utilisation ratio between 0 and 1."""

        if self.capacity <= 0:
            return 1.0
        return len(self.assigned) / self.capacity


class TaskOrchestrator:
    """Central orchestrator coordinating task distribution between agents."""

    def __init__(self) -> None:
        self._agents: Dict[str, AgentState] = {}
        self._pending: List[_QueuedTask] = []
        self._lock = asyncio.Lock()

        # Metrics
        self._tasks_distributed_total: int = 0
        self._latency_samples: List[float] = []

    # ------------------------------------------------------------------
    # Agent management
    # ------------------------------------------------------------------
    async def register_agent(
        self, agent_id: str, *, capacity: int = 1, priority: int = 0
    ) -> AgentState:
        """Register (or update) an agent in the orchestrator.

        If the agent already exists its capacity/priority will be updated and it
        will be marked as active.
        """

        async with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                agent = AgentState(agent_id=agent_id, capacity=capacity, priority=priority)
                self._agents[agent_id] = agent
            else:
                agent.capacity = capacity
                agent.priority = priority
                agent.active = True
            agent.last_heartbeat = time.time()
            await self._assign_pending_locked()
            return agent

    async def heartbeat(
        self,
        agent_id: str,
        *,
        capacity: Optional[int] = None,
        priority: Optional[int] = None,
        active: Optional[bool] = None,
    ) -> AgentState:
        """Update agent heartbeat and optional parameters."""

        async with self._lock:
            agent = self._agents.setdefault(agent_id, AgentState(agent_id=agent_id))
            if capacity is not None:
                agent.capacity = capacity
            if priority is not None:
                agent.priority = priority
            if active is not None:
                agent.active = active
            agent.last_heartbeat = time.time()
            await self._assign_pending_locked()
            return agent

    async def unregister_agent(self, agent_id: str) -> None:
        """Remove agent from orchestrator and re-queue its tasks."""

        async with self._lock:
            agent = self._agents.pop(agent_id, None)
            if not agent:
                return
            for task in agent.assigned.values():
                heapq.heappush(
                    self._pending,
                    _QueuedTask(
                        priority=task.priority,
                        created_at=task.created_at,
                        task_id=task.task_id,
                        payload=task.payload,
                        meta=task.meta,
                    ),
                )
            await self._assign_pending_locked()

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------
    async def submit_task(
        self,
        task_id: str,
        payload: Dict[str, Any],
        *,
        priority: int = 0,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[AssignedTask]:
        """Submit a task to the orchestrator.

        Returns the assignment if the task was immediately dispatched to an
        agent, otherwise ``None`` (the task remains queued until an agent becomes
        available).
        """

        created_at = time.time()
        record = _QueuedTask(
            priority=priority,
            created_at=created_at,
            task_id=task_id,
            payload=payload,
            meta=meta or {},
        )

        async with self._lock:
            heapq.heappush(self._pending, record)
            return await self._assign_pending_locked(single_task_id=task_id)

    async def complete_task(
        self,
        agent_id: str,
        task_id: str,
        *,
        success: bool = True,
    ) -> Optional[AssignedTask]:
        """Mark task as completed and update metrics.

        Returns the :class:`AssignedTask` instance if it existed.
        """

        async with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                return None
            task = agent.assigned.pop(task_id, None)
            if not task:
                return None

            if success:
                elapsed = time.time() - task.created_at
                self._latency_samples.append(elapsed)
                # keep a rolling window of 200 samples to avoid unlimited growth
                if len(self._latency_samples) > 200:
                    self._latency_samples = self._latency_samples[-200:]

            await self._assign_pending_locked()
            return task

    # ------------------------------------------------------------------
    # Introspection / metrics
    # ------------------------------------------------------------------
    async def get_status_snapshot(self) -> Dict[str, Any]:
        """Return an immutable snapshot of the orchestrator state."""

        async with self._lock:
            agents = []
            for agent in sorted(
                self._agents.values(),
                key=lambda a: (a.priority * -1, a.utilisation(), a.agent_id),
            ):
                agents.append(
                    {
                        "agent_id": agent.agent_id,
                        "active": agent.active,
                        "capacity": agent.capacity,
                        "priority": agent.priority,
                        "utilisation": round(agent.utilisation(), 3),
                        "assigned_tasks": [
                            {
                                "task_id": task.task_id,
                                "priority": task.priority,
                                "payload": task.payload,
                                "assigned_at": task.assigned_at,
                                "in_progress_for": round(task.in_progress_for(), 3),
                                "total_latency": round(task.total_latency(), 3),
                                "meta": task.meta,
                            }
                            for task in agent.assigned.values()
                        ],
                        "last_heartbeat": agent.last_heartbeat,
                    }
                )

            pending = [
                {
                    "task_id": entry.task_id,
                    "priority": entry.priority,
                    "payload": entry.payload,
                    "created_at": entry.created_at,
                    "meta": entry.meta,
                }
                for entry in sorted(self._pending)
            ]

            metrics = {
                "tasks_distributed_total": self._tasks_distributed_total,
                "avg_task_latency": self.avg_task_latency,
            }

            return {
                "agents": agents,
                "pending_tasks": pending,
                "metrics": metrics,
            }

    @property
    def tasks_distributed_total(self) -> int:
        return self._tasks_distributed_total

    @property
    def avg_task_latency(self) -> float:
        if not self._latency_samples:
            return 0.0
        return sum(self._latency_samples) / len(self._latency_samples)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _assign_pending_locked(
        self, *, single_task_id: Optional[str] = None
    ) -> Optional[AssignedTask]:
        """Assign pending tasks to available agents.

        ``single_task_id`` allows retrieving the assignment for a specific task
        that has just been enqueued.
        """

        if not self._pending or not self._agents:
            return None

        assignment: Optional[AssignedTask] = None

        def agent_sort_key(agent: AgentState) -> tuple[float, int, str]:
            """Sort agents by utilisation and priority."""

            return (agent.utilisation(), -agent.priority, agent.agent_id)

        while self._pending:
            available_agents = sorted(
                (agent for agent in self._agents.values() if agent.has_capacity()),
                key=agent_sort_key,
            )

            if not available_agents:
                break

            task = heapq.heappop(self._pending)
            agent = available_agents[0]

            assigned = AssignedTask(
                task_id=task.task_id,
                agent_id=agent.agent_id,
                payload=task.payload,
                priority=task.priority,
                created_at=task.created_at,
                assigned_at=time.time(),
                meta=task.meta,
            )

            agent.assigned[task.task_id] = assigned
            agent.last_heartbeat = time.time()
            self._tasks_distributed_total += 1

            if task.task_id == single_task_id:
                assignment = assigned

        return assignment


# Singleton orchestrator used across the application
orchestrator_manager = TaskOrchestrator()

__all__ = ["AssignedTask", "AgentState", "TaskOrchestrator", "orchestrator_manager"]
