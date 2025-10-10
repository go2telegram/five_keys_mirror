import httpx

from app.http_client import (
    AsyncCircuitBreaker,
    CircuitBreakerOpenError,
    async_http_client,
    request_with_retries,
)

from app.config import settings

DEFAULT_SYSTEM_PROMPT = "Ты — эксперт по здоровью, пиши кратко и по делу на русском."


async def ai_generate(prompt: str, sys: str = DEFAULT_SYSTEM_PROMPT):
    if not settings.OPENAI_API_KEY:
        return "⚠️ OpenAI API ключ не настроен."
    circuit_breaker = OPENAI_CIRCUIT_BREAKER
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": sys},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
    }
    try:
        async with async_http_client(base_url=settings.OPENAI_BASE) as client:
            response = await request_with_retries(
                "POST",
                "/chat/completions",
                client=client,
                circuit_breaker=circuit_breaker,
                retries=settings.HTTP_RETRY_ATTEMPTS,
                backoff_factor=settings.HTTP_RETRY_BACKOFF_INITIAL,
                backoff_max=settings.HTTP_RETRY_BACKOFF_MAX,
                retry_statuses=settings.HTTP_RETRY_STATUS_CODES,
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
    except CircuitBreakerOpenError:
        return "⚠️ Сервис OpenAI временно недоступен, попробуйте позже."
    except httpx.HTTPError as exc:
        return f"⚠️ Ошибка генерации: {exc}"
    except Exception as exc:  # noqa: BLE001 - fallback for unexpected errors
        return f"⚠️ Ошибка генерации: {exc}"


OPENAI_CIRCUIT_BREAKER = AsyncCircuitBreaker(
    max_failures=settings.HTTP_CIRCUIT_BREAKER_MAX_FAILURES,
    base_delay=settings.HTTP_CIRCUIT_BREAKER_BASE_DELAY,
    max_delay=settings.HTTP_CIRCUIT_BREAKER_MAX_DELAY,
    name="openai",
)
