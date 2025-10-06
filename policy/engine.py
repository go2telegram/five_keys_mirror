"""Tools for generating self-imposed behavioural policies based on metrics."""
from __future__ import annotations
import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


@dataclass(slots=True)
class PolicyRecord:
    """Representation of a single policy directive."""

    policy_id: str
    title: str
    directive: str
    priority: str
    rationale: str
    status: str = "active"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.policy_id,
            "title": self.title,
            "directive": self.directive,
            "priority": self.priority,
            "rationale": self.rationale,
            "status": self.status,
        }


@dataclass
class PolicySnapshot:
    """Single entry to persist into history."""

    ts: datetime
    metrics: Dict[str, Any]
    policies: List[PolicyRecord]
    rationales: List[str]
    source: str

    def to_json(self) -> str:
        payload = {
            "ts": self.ts.isoformat(),
            "metrics": self.metrics,
            "policies": [p.to_dict() for p in self.policies],
            "rationales": self.rationales,
            "source": self.source,
        }
        return json.dumps(payload, ensure_ascii=False)


class PolicyEngine:
    """Simple rule engine that derives self-governing policies from metrics."""

    def __init__(
        self,
        history_path: Path | None = None,
        *,
        enabled: bool = True,
    ) -> None:
        self.history_path = history_path or Path(__file__).with_name("history.jsonl")
        self.enabled = enabled
        self.metrics: Dict[str, Any] = {}
        self._policies: Dict[str, PolicyRecord] = {}
        self._rationales: List[str] = []
        self._last_updated: datetime | None = None
        self._thresholds = {
            "error_rate": {
                "warn": 0.08,
                "limit": 0.12,
                "critical": 0.25,
                "recovery": 0.05,
            },
            "response_latency": {
                "warn": 4.0,
                "limit": 6.0,
                "critical": 8.0,
                "recovery": 3.0,
            },
        }
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_path.exists():
            self.history_path.touch()
        self._load_latest()

    # ------------------------------------------------------------------
    # public API
    def set_enabled(self, value: bool) -> None:
        """Toggle the engine without losing accumulated context."""

        self.enabled = value

    def update_metrics(self, metrics: Dict[str, Any], *, source: str = "manual") -> Dict[str, Any]:
        """Merge new metric values and trigger evaluation."""

        if not metrics:
            return self.get_status()

        if not self.enabled:
            return self.get_status()

        # Persist numeric values as floats where possible to simplify comparisons.
        for key, value in metrics.items():
            try:
                metrics[key] = float(value)
            except (TypeError, ValueError):
                # keep as-is if conversion fails (for counters, states, etc.)
                pass

        self.metrics.update(metrics)
        return self.evaluate(source=source)

    def evaluate(self, *, source: str = "system") -> Dict[str, Any]:
        """Evaluate current metrics and refresh policies."""

        if not self.enabled:
            return self.get_status()

        new_policies: Dict[str, PolicyRecord] = {}
        rationales: List[str] = []

        error_rate = self.metrics.get("error_rate")
        if isinstance(error_rate, (int, float)):
            err_thresholds = self._thresholds["error_rate"]
            if error_rate >= err_thresholds["critical"]:
                new_policies["autoresend_backoff"] = PolicyRecord(
                    policy_id="autoresend_backoff",
                    title="Снизить авторассылку",
                    directive="decrease_autoresend",
                    priority="high",
                    rationale=(
                        "Критический рост error_rate: "
                        f"{error_rate:.1%} ≥ {err_thresholds['critical']:.0%}."
                    ),
                )
                rationales.append(
                    "Ошибка доставки сообщений выходит за критический порог — требуется"
                    " снизить темп авторассылки и провести расследование." 
                )
            elif error_rate >= err_thresholds["limit"]:
                new_policies["autoresend_backoff"] = PolicyRecord(
                    policy_id="autoresend_backoff",
                    title="Снизить авторассылку",
                    directive="decrease_autoresend",
                    priority="medium",
                    rationale=(
                        "Доля ошибок "
                        f"{error_rate:.1%} превышает допустимый предел"
                        f" {err_thresholds['limit']:.0%}."
                    ),
                    status="monitor",
                )
                rationales.append(
                    "Ошибки выше нормы — ограничиваем авторассылку и усиливаем мониторинг."
                )
            elif error_rate <= err_thresholds["recovery"] and "autoresend_backoff" in self._policies:
                rationales.append(
                    "error_rate стабилизирован — можно вернуть прежний темп авторассылки."
                )

        latency = self.metrics.get("response_latency")
        if isinstance(latency, (int, float)):
            latency_thresholds = self._thresholds["response_latency"]
            if latency >= latency_thresholds["critical"]:
                new_policies["assistant_latency_investigation"] = PolicyRecord(
                    policy_id="assistant_latency_investigation",
                    title="Расследовать задержки ассистента",
                    directive="audit_pipeline",
                    priority="high",
                    rationale=(
                        "Время ответа ассистента "
                        f"{latency:.1f}s ≥ {latency_thresholds['critical']:.1f}s."
                    ),
                )
                rationales.append(
                    "Ответы ассистента приходят слишком медленно — требуется расследование"
                    " и временное ограничение нагрузки."
                )
            elif latency >= latency_thresholds["limit"]:
                new_policies["assistant_latency_investigation"] = PolicyRecord(
                    policy_id="assistant_latency_investigation",
                    title="Расследовать задержки ассистента",
                    directive="audit_pipeline",
                    priority="medium",
                    rationale=(
                        "Время ответа ассистента "
                        f"{latency:.1f}s превышает предел {latency_thresholds['limit']:.1f}s."
                    ),
                    status="monitor",
                )
                rationales.append(
                    "Ответы замедлены — включаем расследование и мягкие ограничения."
                )
            elif (
                latency <= latency_thresholds["recovery"]
                and "assistant_latency_investigation" in self._policies
            ):
                rationales.append(
                    "Задержки нормализовались — расследование можно завершить."
                )

        if not new_policies and not rationales:
            rationales.append("Метрики в пределах целевых значений.")

        changed = set(new_policies) != set(self._policies)
        for key, value in new_policies.items():
            if key in self._policies and self._policies[key].to_dict() == value.to_dict():
                continue
            changed = True
            break

        self._policies = new_policies
        self._rationales = rationales
        self._last_updated = datetime.now(timezone.utc)

        if changed:
            self._append_history(
                PolicySnapshot(
                    ts=self._last_updated,
                    metrics=self.metrics.copy(),
                    policies=list(self._policies.values()),
                    rationales=self._rationales[:],
                    source=source,
                )
            )

        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        """Return the current status of the engine."""

        return {
            "enabled": self.enabled,
            "last_updated": self._last_updated.isoformat() if self._last_updated else None,
            "metrics": self.metrics,
            "policies": [p.to_dict() for p in self._policies.values()],
            "rationales": list(self._rationales),
        }

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the most recent history entries up to ``limit``."""

        entries: deque[Dict[str, Any]] = deque(maxlen=limit)
        if not self.history_path.exists():
            return []

        with self.history_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return list(entries)

    # ------------------------------------------------------------------
    # internal helpers
    def _load_latest(self) -> None:
        """Load the last snapshot to restore state between restarts."""

        if not self.history_path.exists():
            return

        last_entry: Dict[str, Any] | None = None
        with self.history_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    last_entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

        if not last_entry:
            return

        for item in last_entry.get("policies", []):
            if not isinstance(item, dict) or "id" not in item:
                continue
            self._policies[item["id"]] = PolicyRecord(
                policy_id=item["id"],
                title=item.get("title", ""),
                directive=item.get("directive", ""),
                priority=item.get("priority", "medium"),
                rationale=item.get("rationale", ""),
                status=item.get("status", "active"),
            )

        self.metrics = last_entry.get("metrics", {})
        self._rationales = last_entry.get("rationales", [])
        ts = last_entry.get("ts")
        if ts:
            try:
                self._last_updated = datetime.fromisoformat(ts)
            except ValueError:
                self._last_updated = None

    def _append_history(self, snapshot: PolicySnapshot) -> None:
        with self.history_path.open("a", encoding="utf-8") as fp:
            fp.write(snapshot.to_json())
            fp.write("\n")


__all__ = ["PolicyEngine"]
