from typing import Any

import httpx
import pytest

from app import utils_openai
from app.config import settings
from app.http_client import AsyncCircuitBreaker, async_http_client


@pytest.mark.asyncio
async def test_async_http_client_uses_configured_timeouts(monkeypatch):
    monkeypatch.setattr(settings, "HTTP_TIMEOUT_CONNECT", 1.2, raising=False)
    monkeypatch.setattr(settings, "HTTP_TIMEOUT_READ", 3.4, raising=False)
    monkeypatch.setattr(settings, "HTTP_TIMEOUT_WRITE", 5.6, raising=False)
    monkeypatch.setattr(settings, "HTTP_TIMEOUT_TOTAL", 7.8, raising=False)

    async with async_http_client() as client:
        timeout_dict = client.timeout.as_dict()
        assert timeout_dict["connect"] == pytest.approx(1.2)
        assert timeout_dict["read"] == pytest.approx(3.4)
        assert timeout_dict["write"] == pytest.approx(5.6)
        assert timeout_dict["pool"] == pytest.approx(7.8)


@pytest.mark.asyncio
async def test_ai_generate_network_degradation(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test", raising=False)
    monkeypatch.setattr(settings, "HTTP_RETRY_ATTEMPTS", 1, raising=False)
    monkeypatch.setattr(settings, "HTTP_RETRY_BACKOFF_INITIAL", 0.1, raising=False)
    monkeypatch.setattr(settings, "HTTP_RETRY_BACKOFF_MAX", 0.2, raising=False)
    monkeypatch.setattr(settings, "HTTP_CIRCUIT_BREAKER_MAX_FAILURES", 2, raising=False)
    monkeypatch.setattr(settings, "HTTP_CIRCUIT_BREAKER_BASE_DELAY", 5.0, raising=False)
    monkeypatch.setattr(settings, "HTTP_CIRCUIT_BREAKER_MAX_DELAY", 5.0, raising=False)

    breaker = AsyncCircuitBreaker(
        max_failures=2,
        base_delay=5.0,
        max_delay=5.0,
        name="test-openai",
    )
    monkeypatch.setattr(utils_openai, "OPENAI_CIRCUIT_BREAKER", breaker, raising=False)

    calls: list[dict[str, Any]] = []

    async def failing_request(self: httpx.AsyncClient, method: str, url: str, **kwargs: Any):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        raise httpx.ReadTimeout("boom")

    monkeypatch.setattr(httpx.AsyncClient, "request", failing_request, raising=False)

    sleeps: list[float] = []

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    monkeypatch.setattr("app.http_client.asyncio.sleep", fake_sleep)

    first_response = await utils_openai.ai_generate("привет")
    assert first_response.startswith("⚠️ Ошибка генерации")
    assert len(calls) == 2  # first attempt + retry
    assert sleeps == [pytest.approx(0.1)]

    second_response = await utils_openai.ai_generate("ещё раз")
    assert "временно недоступен" in second_response
    assert len(calls) == 2  # circuit breaker prevented additional calls
