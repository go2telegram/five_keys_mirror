"""Инструменты дипломатического обмена между кластерами Five Keys."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List
import datetime as dt

import yaml


class DiplomacyError(RuntimeError):
    """Базовое исключение модуля дипломатии."""


class ContractNotFound(DiplomacyError):
    """Конфигурация дипломатических контрактов не найдена."""


class ContractValidationError(DiplomacyError):
    """Контракт найден, но не удовлетворяет требованиям протокола."""


@dataclass(slots=True)
class StrategyReport:
    """Результат выполнения одной стратегии обмена."""

    name: str
    status: str
    summary: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HandshakeReport:
    """Итог дипломатического рукопожатия."""

    timestamp: str
    primary_network: str
    counterpart: str
    strategies: List[StrategyReport]
    concluded: bool
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["strategies"] = [s.to_dict() for s in self.strategies]
        return data

    @property
    def successful_strategies(self) -> List[str]:
        return [s.name for s in self.strategies if s.status == "ok"]


class DiplomacyHandshake:
    """Оркестратор дипломатического обмена между сетями."""

    def __init__(self, contracts_path: str | Path | None = None):
        self.contracts_path = Path(contracts_path or Path(__file__).resolve().parent / "contracts.yml")
        self._contracts = self._load_contracts()
        self._history: List[HandshakeReport] = []
        self._strategy_map = {
            "knowledge_exchange": self._run_knowledge_exchange,
            "trade_agreement": self._run_trade_agreement,
            "alert_sharing": self._run_alert_sharing,
        }

    # ----------------------------
    # Публичное API
    # ----------------------------
    def perform_handshake(self) -> HandshakeReport:
        networks = self._contracts.get("networks", [])
        if len(networks) < 2:
            raise ContractValidationError("В contracts.yml должно быть описано минимум две сети.")

        primary, counterpart = networks[0], networks[1]
        strategies_declared = self._contracts.get("strategies") or [
            "knowledge_exchange",
            "trade_agreement",
        ]

        reports: List[StrategyReport] = []
        context: Dict[str, Any] = {
            "primary_title": primary.get("title", primary.get("id")),
            "counterpart_title": counterpart.get("title", counterpart.get("id")),
        }

        for name in strategies_declared:
            handler = self._strategy_map.get(name)
            if not handler:
                reports.append(
                    StrategyReport(
                        name=name,
                        status="skipped",
                        summary="Стратегия не поддерживается текущей версией протокола.",
                    )
                )
                continue

            report = handler(primary, counterpart)
            reports.append(report)

        # Успешным считаем рукопожатие, если выполнены знания и торговля
        required = {"knowledge_exchange", "trade_agreement"}
        succeeded = {rep.name for rep in reports if rep.status == "ok"}
        concluded = required.issubset(succeeded)

        handshake_report = HandshakeReport(
            timestamp=dt.datetime.utcnow().isoformat(),
            primary_network=primary.get("id", "primary"),
            counterpart=counterpart.get("id", "counterpart"),
            strategies=reports,
            concluded=concluded,
            context=context,
        )
        self._history.append(handshake_report)
        return handshake_report

    @property
    def last_report(self) -> HandshakeReport | None:
        return self._history[-1] if self._history else None

    def iter_history(self) -> Iterable[HandshakeReport]:
        yield from self._history

    # ----------------------------
    # Внутренние инструменты
    # ----------------------------
    def _load_contracts(self) -> Dict[str, Any]:
        if not self.contracts_path.exists():
            raise ContractNotFound(
                f"Файл {self.contracts_path} не найден. Создайте contracts.yml с описанием сетей."
            )
        with self.contracts_path.open("r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp) or {}
        if "networks" not in data:
            raise ContractValidationError("contracts.yml должен содержать ключ 'networks'.")
        return data

    def _run_knowledge_exchange(self, primary: Dict[str, Any], counterpart: Dict[str, Any]) -> StrategyReport:
        knowledge_a = set(primary.get("knowledge_base", []) or [])
        knowledge_b = set(counterpart.get("knowledge_base", []) or [])

        combined = sorted(knowledge_a | knowledge_b)
        new_for_primary = sorted(knowledge_b - knowledge_a)
        new_for_counterpart = sorted(knowledge_a - knowledge_b)

        summary_parts = [
            f"Всего знаний в общем пуле: {len(combined)}.",
            f"Новые для ядра: {len(new_for_primary)}.",
            f"Новые для партнёра: {len(new_for_counterpart)}.",
        ]

        payload = {
            "shared_topics": combined,
            "new_for_primary": new_for_primary,
            "new_for_counterpart": new_for_counterpart,
        }
        return StrategyReport(
            name="knowledge_exchange",
            status="ok",
            summary=" ".join(summary_parts),
            payload=payload,
        )

    def _run_trade_agreement(self, primary: Dict[str, Any], counterpart: Dict[str, Any]) -> StrategyReport:
        primary_trade = primary.get("trade_profile", {}) or {}
        counterpart_trade = counterpart.get("trade_profile", {}) or {}

        primary_exports = primary_trade.get("exports", {}) or {}
        primary_imports = primary_trade.get("imports", {}) or {}
        counterpart_exports = counterpart_trade.get("exports", {}) or {}
        counterpart_imports = counterpart_trade.get("imports", {}) or {}

        outbound_matches = self._match_goods(primary_exports, counterpart_imports)
        inbound_matches = self._match_goods(counterpart_exports, primary_imports)

        total_outbound = sum(item[1] for item in outbound_matches)
        total_inbound = sum(item[1] for item in inbound_matches)
        balance = total_outbound - total_inbound

        summary_parts = [
            f"Экспорт ядра → партнёр: {total_outbound} условных единиц.",
            f"Импорт ядром от партнёра: {total_inbound} условных единиц.",
            f"Баланс: {'+' if balance >= 0 else ''}{balance}.",
        ]

        payload = {
            "outbound_contracts": self._serialize_matches(outbound_matches),
            "inbound_contracts": self._serialize_matches(inbound_matches),
            "balance": balance,
        }

        status = "ok" if outbound_matches or inbound_matches else "deferred"
        if status == "deferred":
            summary_parts.append("Совпадающих товарных позиций не найдено — требуется уточнение контрактов.")

        return StrategyReport(
            name="trade_agreement",
            status=status,
            summary=" ".join(summary_parts),
            payload=payload,
        )

    def _run_alert_sharing(self, primary: Dict[str, Any], counterpart: Dict[str, Any]) -> StrategyReport:
        alerts_primary = list(primary.get("alerts", []) or [])
        alerts_counterpart = list(counterpart.get("alerts", []) or [])
        combined = alerts_primary + [a for a in alerts_counterpart if a not in alerts_primary]

        summary = (
            f"Передано {len(alerts_primary)} внутренних алертов, получено {len(alerts_counterpart)} от партнёра."
        )
        payload = {
            "forwarded": alerts_primary,
            "received": alerts_counterpart,
            "merged": combined,
        }
        return StrategyReport(
            name="alert_sharing",
            status="ok",
            summary=summary,
            payload=payload,
        )

    @staticmethod
    def _match_goods(exports: Dict[str, Any], imports: Dict[str, Any]) -> List[tuple[str, int]]:
        matches: List[tuple[str, int]] = []
        for good, export_value in exports.items():
            if good not in imports:
                continue
            try:
                export_numeric = int(export_value)
                import_numeric = int(imports[good])
            except (TypeError, ValueError):
                continue
            matches.append((good, min(export_numeric, import_numeric)))
        return matches

    @staticmethod
    def _serialize_matches(matches: List[tuple[str, int]]) -> List[Dict[str, Any]]:
        return [
            {"good": good, "volume": volume}
            for good, volume in matches
        ]


__all__ = [
    "DiplomacyHandshake",
    "DiplomacyError",
    "ContractNotFound",
    "ContractValidationError",
    "StrategyReport",
    "HandshakeReport",
]
