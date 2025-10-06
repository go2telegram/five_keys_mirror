"""Utilities for building AI-powered diagnostic reports for operators."""
from __future__ import annotations

import asyncio
import json
import re
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

import httpx

from app.config import settings
from app.utils_openai import ai_generate

PROM_LINE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>[-+]?(?:\d+\.?\d*|\d*\.\d+)(?:[eE][-+]?\d+)?)"
)
LABEL_RE = re.compile(r"(?P<key>[\w:]+)\s*=\s*\"(?P<value>(?:[^\\\"]|\\.)*)\"")


@dataclass
class MetricSample:
    """Representation of a single Prometheus metric sample."""

    name: str
    labels: dict[str, str]
    value: float


@dataclass
class DiagnosticSnapshot:
    """Aggregated diagnostic data ready to be sent to the model."""

    fetched_at: datetime
    uptime_hours: float | None
    p95_ms: float | None
    error_counts: list[tuple[str, float]]
    hot_handlers: list[tuple[str, float]]
    anomalies: list[str]
    recent_log_tail: list[str]
    metrics_raw_excerpt: str
    metrics_source_error: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at.isoformat(),
            "uptime_hours": self.uptime_hours,
            "p95_ms": self.p95_ms,
            "error_counts": self.error_counts,
            "hot_handlers": self.hot_handlers,
            "anomalies": self.anomalies,
            "recent_log_tail": self.recent_log_tail,
            "metrics_source_error": self.metrics_source_error,
        }


class DiagnosticAssistant:
    """Collects metrics/logs and asks the AI model for insights."""

    def __init__(
        self,
        metrics_url: str | None,
        error_log_path: str | None,
        cache_ttl: int = 60,
    ) -> None:
        self._metrics_url = metrics_url
        self._error_log_path = Path(error_log_path) if error_log_path else None
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, str]] = {}
        self._cache_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._snapshot_cache: tuple[float, DiagnosticSnapshot] | None = None

    async def doctor_tldr(self) -> str:
        """Return TL;DR for the last 24 hours (1–2 paragraphs)."""

        return await self._get_cached("doctor", self._generate_doctor_tldr)

    async def suggest_fixes(self) -> str:
        """Return 3–7 actionable suggestions."""

        return await self._get_cached("suggest", self._generate_suggest_fixes)

    async def _get_cached(self, key: str, factory: Callable[[], Awaitable[str]]) -> str:
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and now - cached[0] < self._cache_ttl:
            return cached[1]

        lock = self._cache_locks[key]
        async with lock:
            cached = self._cache.get(key)
            now = time.monotonic()
            if cached and now - cached[0] < self._cache_ttl:
                return cached[1]
            value = await factory()
            self._cache[key] = (time.monotonic(), value)
            return value

    async def _generate_doctor_tldr(self) -> str:
        snapshot = await self._get_snapshot()
        prompt = self._build_doctor_prompt(snapshot)

        if settings.OPENAI_API_KEY:
            response = await ai_generate(prompt, sys=(
                "Ты — SRE инженер. Кратко проанализируй данные за последние 24 часа. "
                "Ответь насыщенно цифрами, но не более чем в двух абзацах."
            ))
            if response and not response.startswith("⚠️"):
                return response

        return self._fallback_doctor(snapshot)

    async def _generate_suggest_fixes(self) -> str:
        snapshot = await self._get_snapshot()
        prompt = self._build_suggest_prompt(snapshot)

        if settings.OPENAI_API_KEY:
            response = await ai_generate(prompt, sys=(
                "Ты — опытный инженер эксплуатации. Предложи точные действия."
            ))
            if response and not response.startswith("⚠️"):
                return response

        return self._fallback_suggest(snapshot)

    async def _get_snapshot(self) -> DiagnosticSnapshot:
        now = time.monotonic()
        cached = self._snapshot_cache
        if cached and now - cached[0] < self._cache_ttl:
            return cached[1]

        metrics_text, metrics_error = await self._fetch_metrics()
        samples = parse_prometheus(metrics_text) if metrics_text else []
        log_tail = await self._read_log_tail(limit=50)

        uptime = extract_uptime(samples)
        p95 = extract_p95(samples)
        top_errors = extract_error_counts(samples, log_tail)
        hot_handlers = extract_hot_handlers(samples)
        anomalies = extract_anomalies(samples, log_tail)

        snapshot = DiagnosticSnapshot(
            fetched_at=datetime.now(timezone.utc),
            uptime_hours=uptime,
            p95_ms=p95,
            error_counts=top_errors,
            hot_handlers=hot_handlers,
            anomalies=anomalies,
            recent_log_tail=log_tail,
            metrics_raw_excerpt=_build_metrics_excerpt(samples),
            metrics_source_error=metrics_error,
        )

        self._snapshot_cache = (time.monotonic(), snapshot)
        return snapshot

    async def _fetch_metrics(self) -> tuple[str | None, str | None]:
        if not self._metrics_url:
            return None, "METRICS_URL не задан"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self._metrics_url)
                resp.raise_for_status()
                text = resp.text
                return text, None
        except Exception as exc:
            return None, f"Не удалось получить метрики: {exc}"

    async def _read_log_tail(self, *, limit: int = 50) -> list[str]:
        if not self._error_log_path:
            return []
        path = self._error_log_path
        if not path.exists() or not path.is_file():
            return []

        def _read() -> list[str]:
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                return lines[-limit:]
            except Exception:
                return []

        return await asyncio.to_thread(_read)

    def _build_doctor_prompt(self, snapshot: DiagnosticSnapshot) -> str:
        payload = snapshot.as_payload()
        payload["metrics_raw_excerpt"] = snapshot.metrics_raw_excerpt
        context = json.dumps(payload, ensure_ascii=False, indent=2)
        instructions = (
            "На основе данных подготовь лаконичный TL;DR о состоянии сервиса за последние 24 часа. "
            "Структура: абзац с аптаймом/производительностью, второй абзац — про ошибки и аномалии. "
            "Если данных не хватает, явно укажи это."
        )
        return f"{instructions}\n\nКонтекст:\n{context}"

    def _build_suggest_prompt(self, snapshot: DiagnosticSnapshot) -> str:
        payload = snapshot.as_payload()
        payload["metrics_raw_excerpt"] = snapshot.metrics_raw_excerpt
        context = json.dumps(payload, ensure_ascii=False, indent=2)
        instructions = (
            "Проанализируй данные и предложи 3-7 конкретных действий для инженера. "
            "Каждый пункт формулируй в повелительном наклонении и ссылайся на цифры, если они есть."
        )
        return f"{instructions}\n\nКонтекст:\n{context}"

    def _fallback_doctor(self, snapshot: DiagnosticSnapshot) -> str:
        parts: list[str] = []
        perf_bits: list[str] = []
        if snapshot.uptime_hours is not None:
            perf_bits.append(f"аптайм ~{snapshot.uptime_hours:.1f} ч")
        if snapshot.p95_ms is not None:
            perf_bits.append(f"P95 ≈ {snapshot.p95_ms:.0f} мс")
        if snapshot.hot_handlers:
            top = ", ".join(
                f"{name} ({value:.0f})" for name, value in snapshot.hot_handlers[:3]
            )
            perf_bits.append(f"нагрузка: {top}")
        if perf_bits:
            parts.append("; ".join(perf_bits))
        else:
            parts.append("Данных по производительности недостаточно.")

        err_bits: list[str] = []
        if snapshot.error_counts:
            err_bits.append(
                "Ошибки: "
                + "; ".join(f"{name} ×{count:.0f}" for name, count in snapshot.error_counts[:3])
            )
        if snapshot.anomalies:
            err_bits.append("Аномалии: " + "; ".join(snapshot.anomalies[:3]))
        if snapshot.metrics_source_error:
            err_bits.append(snapshot.metrics_source_error)
        if not err_bits:
            err_bits.append("Аномалий не выявлено по доступным данным.")
        parts.append(" ".join(err_bits))

        return "\n\n".join(parts[:2])

    def _fallback_suggest(self, snapshot: DiagnosticSnapshot) -> str:
        suggestions: list[str] = []

        if snapshot.p95_ms is not None and snapshot.p95_ms > 500:
            suggestions.append(
                "Увеличь бюджет на оптимизацию долгих запросов: проверь таймауты и кеши по трассам с высоким P95"
            )
        if snapshot.hot_handlers:
            hot = snapshot.hot_handlers[0]
            suggestions.append(
                f"Профилируй хендлер {hot[0]} — у него наибольшая нагрузка ({hot[1]:.0f})"
            )
        if snapshot.error_counts:
            err_name, err_count = snapshot.error_counts[0]
            suggestions.append(
                f"Разбери ошибку {err_name}: зафиксировано {err_count:.0f} случаев в логах/метриках"
            )
        if snapshot.anomalies:
            suggestions.append(
                "Проверь аномалии: " + "; ".join(snapshot.anomalies[:2])
            )
        if snapshot.metrics_source_error:
            suggestions.append("Восстанови сбор метрик — сейчас: " + snapshot.metrics_source_error)
        if not suggestions:
            suggestions.extend([
                "Проверь дашборды и тайминги базовых хендлеров",
                "Уточни свежие ошибки в журнале и поставь алерты",
                "Перепроверь ротацию логов и резервные копии",
            ])

        # Ensure 3-7 suggestions by padding with general advice.
        extra_pool = [
            "Обнови алерты: добавь триггеры на рост P95 и 5xx",
            "Проверь индексы в БД и фрагментацию горячих таблиц",
            "Сверь текущие таймауты балансировщика с профилем нагрузки",
            "Пересоздай деградационный прогон в staging и сравни метрики",
        ]
        for item in extra_pool:
            if len(suggestions) >= 7:
                break
            if item not in suggestions:
                suggestions.append(item)

        return "\n".join(f"• {s}" for s in suggestions[:7])


def parse_prometheus(text: str | None) -> list[MetricSample]:
    if not text:
        return []
    samples: list[MetricSample] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = PROM_LINE_RE.match(line)
        if not match:
            continue
        name = match.group("name")
        value_str = match.group("value")
        try:
            value = float(value_str)
        except ValueError:
            continue
        labels_raw = match.group("labels")
        labels: dict[str, str] = {}
        if labels_raw:
            labels = {
                m.group("key"): _unescape_label(m.group("value"))
                for m in LABEL_RE.finditer(labels_raw)
            }
        samples.append(MetricSample(name=name, labels=labels, value=value))
    return samples


def _unescape_label(value: str) -> str:
    return bytes(value, "utf-8").decode("unicode_escape")


def extract_uptime(samples: Sequence[MetricSample]) -> float | None:
    best: float | None = None
    for s in samples:
        name = s.name.lower()
        if "uptime" in name:
            if best is None or s.value > best:
                best = s.value
        elif s.labels.get("metric") == "uptime":
            if best is None or s.value > best:
                best = s.value
    if best is None:
        return None
    if best > 0 and best < 7:  # seconds? convert to hours heuristically
        return best
    # assume seconds and convert to hours
    return best / 3600.0


def extract_p95(samples: Sequence[MetricSample]) -> float | None:
    candidates: list[float] = []
    for s in samples:
        name = s.name.lower()
        if "p95" in name:
            candidates.append(s.value)
        elif s.labels.get("quantile") in {"0.95", "0.9"}:
            candidates.append(s.value)
    if not candidates:
        return None
    value = max(candidates)
    # Heuristic: convert seconds to ms if value < 60
    if value < 60:
        return value * 1000.0
    return value


def extract_error_counts(
    samples: Sequence[MetricSample], log_tail: Sequence[str]
) -> list[tuple[str, float]]:
    counter: Counter[str] = Counter()
    for s in samples:
        name = s.name.lower()
        if "error" in name or "exception" in name:
            label_name = s.labels.get("type") or s.labels.get("error") or s.labels.get("code")
            key = label_name or s.name
            counter[key] += s.value
        status = s.labels.get("status")
        if status and status.startswith("5"):
            key = f"HTTP {status}"
            counter[key] += s.value
    log_counter = Counter()
    error_pattern = re.compile(r"([A-Za-z_]*Error|Exception|HTTP\s?\d{3})")
    for line in log_tail:
        for match in error_pattern.findall(line):
            log_counter[match] += 1
    for key, count in log_counter.items():
        counter[key] += count
    most_common = counter.most_common(5)
    return [(name, float(count)) for name, count in most_common]


def extract_hot_handlers(samples: Sequence[MetricSample]) -> list[tuple[str, float]]:
    totals: dict[str, list[float]] = defaultdict(list)
    for s in samples:
        handler = s.labels.get("handler") or s.labels.get("endpoint") or s.labels.get("path")
        if not handler:
            continue
        name = s.name.lower()
        if any(key in name for key in ("request", "duration", "latency", "calls")):
            totals[handler].append(s.value)
    scores: list[tuple[str, float]] = []
    for handler, values in totals.items():
        if not values:
            continue
        score = statistics.fmean(values)
        scores.append((handler, score))
    scores.sort(key=lambda item: item[1], reverse=True)
    return scores[:5]


def extract_anomalies(
    samples: Sequence[MetricSample], log_tail: Sequence[str]
) -> list[str]:
    anomalies: list[str] = []
    for s in samples:
        name = s.name.lower()
        if "anomaly" in name or "alert" in name or "incident" in name:
            if s.value and s.value > 0:
                label = s.labels.get("type") or s.labels.get("alert") or s.labels.get("name")
                detail = f"{label or s.name}: {s.value:g}"
                anomalies.append(detail)
    pattern = re.compile(r"ANOMALY: (?P<msg>.+)")
    for line in log_tail:
        m = pattern.search(line)
        if m:
            anomalies.append(m.group("msg"))
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for item in anomalies:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique[:5]


def _build_metrics_excerpt(samples: Sequence[MetricSample], limit: int = 20) -> str:
    if not samples:
        return ""
    entries = []
    for sample in samples[:limit]:
        labels = ", ".join(f"{k}={v}" for k, v in sample.labels.items())
        if labels:
            entries.append(f"{sample.name}{{{labels}}} = {sample.value}")
        else:
            entries.append(f"{sample.name} = {sample.value}")
    return "\n".join(entries)


# Instantiate a shared assistant instance for reuse across handlers.
diagnostic_assistant = DiagnosticAssistant(
    metrics_url=getattr(settings, "METRICS_URL", None),
    error_log_path=getattr(settings, "ERROR_LOG_PATH", "errors.log"),
    cache_ttl=getattr(settings, "ADMIN_AI_CACHE_SECONDS", 60),
)
