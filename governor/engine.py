from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Deque, Dict, List, Mapping, Optional, Tuple

import yaml


@dataclass(slots=True)
class Rule:
    idx: int
    condition: str
    action_key: str
    action_value: Any


@dataclass(slots=True)
class RuleState:
    active: bool = False
    last_triggered: Optional[dt.datetime] = None
    last_cleared: Optional[dt.datetime] = None


@dataclass(slots=True)
class HistoryEntry:
    ts: dt.datetime
    rule_condition: str
    action: Dict[str, Any]
    details: str


@dataclass(slots=True)
class ActionContext:
    bot: Any
    admin_chat_id: Optional[int]
    metrics: Mapping[str, Any]
    rule_condition: str


ActionHandler = Callable[[Any, ActionContext], Awaitable[str] | str]


class GovernorEngine:
    """Выполняет DSL-правила самоуправления."""

    def __init__(
        self,
        *,
        rules_path: Path,
        metrics_provider: Callable[[], Mapping[str, Any]],
        action_handlers: Mapping[str, ActionHandler],
        log_path: Path,
        history_limit: int = 50,
    ) -> None:
        self.rules_path = rules_path
        self.metrics_provider = metrics_provider
        self._action_handlers: Dict[str, ActionHandler] = dict(action_handlers)
        self.log_path = log_path
        self._logger = logging.getLogger("governor")
        self._configure_logger()
        self._history: Deque[HistoryEntry] = deque(maxlen=history_limit)
        self._rules: List[Rule] = []
        self._rule_state: Dict[int, RuleState] = {}
        self._rules_mtime: Optional[float] = None
        self._last_run: Optional[dt.datetime] = None
        self.reload_rules(force=True)

    def _configure_logger(self) -> None:
        if any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == str(self.log_path) for h in self._logger.handlers):
            return
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(self.log_path, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        self._logger.addHandler(handler)

    def reload_rules(self, force: bool = False) -> None:
        try:
            mtime = self.rules_path.stat().st_mtime
        except FileNotFoundError:
            mtime = None
        if not force and mtime is not None and self._rules_mtime == mtime:
            return
        if not self.rules_path.exists():
            self._rules = []
            self._rule_state = {}
            self._rules_mtime = mtime
            return

        data = self.rules_path.read_text(encoding="utf-8")
        raw_rules = yaml.safe_load(data) or []
        parsed_rules: List[Rule] = []
        for idx, raw in enumerate(raw_rules):
            if not isinstance(raw, Mapping):
                continue
            condition = str(raw.get("if", "")).strip()
            action_block = raw.get("do")
            if not condition or not isinstance(action_block, Mapping) or not action_block:
                continue
            action_items = list(action_block.items())
            action_key, action_value = action_items[0]
            action_key = str(action_key)
            parsed_rules.append(Rule(idx=idx, condition=condition, action_key=action_key, action_value=action_value))

        self._rules = parsed_rules
        new_state: Dict[int, RuleState] = {}
        for rule in self._rules:
            new_state[rule.idx] = self._rule_state.get(rule.idx, RuleState())
        self._rule_state = new_state
        self._rules_mtime = mtime

    @staticmethod
    def _parse_condition(condition: str) -> Tuple[str, str, float]:
        tokens = condition.split()
        if len(tokens) != 3:
            raise ValueError(f"Unsupported condition: {condition}")
        metric, op, threshold_raw = tokens
        try:
            threshold: float = float(threshold_raw)
        except ValueError as exc:
            raise ValueError(f"Unsupported threshold value in condition '{condition}'") from exc
        return metric, op, threshold

    @staticmethod
    def _compare(actual: float, op: str, threshold: float) -> bool:
        if op == ">":
            return actual > threshold
        if op == ">=":
            return actual >= threshold
        if op == "<":
            return actual < threshold
        if op == "<=":
            return actual <= threshold
        if op == "==":
            return actual == threshold
        if op == "!=":
            return actual != threshold
        raise ValueError(f"Unsupported operator '{op}' in condition")

    async def run(self, *, bot: Any, admin_chat_id: Optional[int]) -> None:
        self.reload_rules()
        metrics = dict(self.metrics_provider() or {})
        now = dt.datetime.utcnow()
        self._last_run = now
        for rule in self._rules:
            state = self._rule_state.setdefault(rule.idx, RuleState())
            try:
                metric_name, op, threshold = self._parse_condition(rule.condition)
            except ValueError as exc:
                self._logger.warning("Skip rule %s: %s", rule.condition, exc)
                continue
            actual_value = metrics.get(metric_name)
            if actual_value is None:
                state.active = False
                continue
            try:
                actual = float(actual_value)
            except (TypeError, ValueError):
                self._logger.warning("Metric '%s' is not numeric: %s", metric_name, actual_value)
                state.active = False
                continue

            try:
                is_violated = self._compare(actual, op, threshold)
            except ValueError as exc:
                self._logger.warning("Skip rule %s: %s", rule.condition, exc)
                continue

            if is_violated and not state.active:
                action = self._action_handlers.get(rule.action_key)
                if not action:
                    self._logger.warning("No handler for action '%s'", rule.action_key)
                    continue
                context = ActionContext(bot=bot, admin_chat_id=admin_chat_id, metrics=metrics, rule_condition=rule.condition)
                details = await self._execute_action(action, rule.action_value, context)
                state.active = True
                state.last_triggered = now
                self._history.appendleft(
                    HistoryEntry(
                        ts=now,
                        rule_condition=rule.condition,
                        action={rule.action_key: rule.action_value},
                        details=details,
                    )
                )
                self._logger.info(
                    "Triggered rule '%s' (metric %s=%.4f) -> %s",
                    rule.condition,
                    metric_name,
                    actual,
                    details,
                )
            elif not is_violated and state.active:
                state.active = False
                state.last_cleared = now

    async def _execute_action(self, handler: ActionHandler, value: Any, context: ActionContext) -> str:
        result = handler(value, context)
        if asyncio.iscoroutine(result):
            return await result  # type: ignore[return-value]
        return str(result)

    def get_status(self) -> Dict[str, Any]:
        rules_status: List[Dict[str, Any]] = []
        for rule in self._rules:
            state = self._rule_state.get(rule.idx, RuleState())
            rules_status.append(
                {
                    "if": rule.condition,
                    "do": {rule.action_key: rule.action_value},
                    "active": state.active,
                    "last_triggered": state.last_triggered.isoformat() if state.last_triggered else None,
                    "last_cleared": state.last_cleared.isoformat() if state.last_cleared else None,
                }
            )
        history_items = [
            {
                "ts": entry.ts.isoformat(),
                "rule": entry.rule_condition,
                "action": entry.action,
                "details": entry.details,
            }
            for entry in list(self._history)
        ]
        return {
            "last_run_at": self._last_run.isoformat() if self._last_run else None,
            "rules": rules_status,
            "history": history_items,
        }

