"""HTTP client utilities with retries and circuit breaker support."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Optional, TypeVar

import httpx

from app.config import settings

T = TypeVar("T")


class CircuitBreakerOpenError(RuntimeError):
    """Raised when the circuit breaker is open and rejects a call."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Circuit breaker '{name}' is open")
        self.name = name


class RetryableStatusError(httpx.HTTPError):
    """Internal error used to mark responses that should be retried."""

    def __init__(self, response: httpx.Response) -> None:
        message = f"Retryable response: {response.status_code}"
        super().__init__(message, request=response.request)
        self.response = response


@dataclass
class _CircuitState:
    failure_count: int = 0
    state: str = "closed"  # closed, open, half-open
    opened_at: float = 0.0
    open_count: int = 0
    open_until: float = 0.0
    half_open_in_flight: bool = False


class AsyncCircuitBreaker:
    """Simple asynchronous circuit breaker implementation."""

    def __init__(
        self,
        *,
        max_failures: int,
        base_delay: float,
        max_delay: float,
        name: str,
    ) -> None:
        if max_failures <= 0:
            raise ValueError("max_failures must be positive")
        if base_delay < 0 or max_delay < 0:
            raise ValueError("delay values must be non-negative")
        self._max_failures = max_failures
        self._base_delay = base_delay
        self._max_delay = max_delay if max_delay > 0 else 0.0
        self._name = name
        self._state = _CircuitState()
        self._lock = asyncio.Lock()

    async def call(self, func: Callable[[], Awaitable[T]]) -> T:
        await self._acquire_permission()
        try:
            result = await func()
        except Exception:
            await self._record_failure()
            raise
        else:
            await self._record_success()
            return result

    async def _acquire_permission(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._state.state == "open":
                if now >= self._state.open_until:
                    self._state.state = "half-open"
                    self._state.half_open_in_flight = False
                else:
                    raise CircuitBreakerOpenError(self._name)

            if self._state.state == "half-open":
                if self._state.half_open_in_flight:
                    raise CircuitBreakerOpenError(self._name)
                self._state.half_open_in_flight = True

    async def _record_failure(self) -> None:
        async with self._lock:
            if self._state.state == "half-open":
                self._trip_circuit()
                return

            self._state.failure_count += 1
            if self._state.failure_count >= self._max_failures:
                self._trip_circuit()

    async def _record_success(self) -> None:
        async with self._lock:
            self._state = _CircuitState()

    def _trip_circuit(self) -> None:
        now = time.monotonic()
        self._state.state = "open"
        self._state.failure_count = self._max_failures
        self._state.open_count += 1
        delay = self._base_delay * (2 ** max(0, self._state.open_count - 1))
        if self._max_delay:
            delay = min(delay, self._max_delay)
        self._state.opened_at = now
        self._state.open_until = now + delay
        self._state.half_open_in_flight = False

    async def reset(self) -> None:
        """Forcefully reset the breaker state (useful in tests)."""

        async with self._lock:
            self._state = _CircuitState()


@asynccontextmanager
async def async_http_client(
    *,
    base_url: str | httpx.URL | None = None,
    follow_redirects: bool = False,
    additional_options: Optional[dict[str, Any]] = None,
) -> AsyncIterator[httpx.AsyncClient]:
    """Create an AsyncClient with configured timeout and proxy options."""

    timeout = httpx.Timeout(
        timeout=settings.HTTP_TIMEOUT_TOTAL,
        connect=settings.HTTP_TIMEOUT_CONNECT,
        read=settings.HTTP_TIMEOUT_READ,
        write=settings.HTTP_TIMEOUT_WRITE,
    )
    options: dict[str, Any] = {
        "timeout": timeout,
        "follow_redirects": follow_redirects,
    }
    if base_url is not None:
        options["base_url"] = base_url
    if settings.HTTP_PROXY_URL:
        options["proxies"] = settings.HTTP_PROXY_URL
    if additional_options:
        options.update(additional_options)

    async with httpx.AsyncClient(**options) as client:
        yield client


async def request_with_retries(
    method: str,
    url: str,
    *,
    client: httpx.AsyncClient,
    circuit_breaker: AsyncCircuitBreaker,
    retries: int,
    backoff_factor: float,
    backoff_max: float,
    retry_statuses: Iterable[int] | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Execute an HTTP request with retry and circuit breaker protection."""

    attempts = max(1, int(retries) + 1)
    delay = max(0.0, backoff_factor)
    retryable_statuses = set(retry_statuses or [])
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        async def _attempt() -> httpx.Response:
            response = await client.request(method, url, **kwargs)
            if retryable_statuses and response.status_code in retryable_statuses:
                raise RetryableStatusError(response)
            return response

        try:
            return await circuit_breaker.call(_attempt)
        except CircuitBreakerOpenError:
            raise
        except RetryableStatusError as exc:
            last_error = exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = exc
        if attempt >= attempts:
            assert last_error is not None
            raise last_error

        if delay > 0:
            await asyncio.sleep(delay)
            next_delay = delay * 2 if delay else backoff_factor
            if backoff_max > 0:
                next_delay = min(next_delay, backoff_max)
            delay = next_delay
        elif backoff_factor > 0:
            delay = min(backoff_factor, backoff_max) if backoff_max > 0 else backoff_factor

    assert last_error is not None
    raise last_error


__all__ = [
    "AsyncCircuitBreaker",
    "CircuitBreakerOpenError",
    "async_http_client",
    "request_with_retries",
]
