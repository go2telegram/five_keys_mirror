from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from pathlib import Path


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_ID: int

    DATABASE_URL: str | None = None
    REDIS_URL: str | None = None
    TZ: str = "Europe/Moscow"

    # Партнёрские/коммерческие ссылки
    VILAVI_REF_LINK_DISCOUNT: str = ""
    VILAVI_ORDER_NO_REG: str = ""

    # Напоминания
    NOTIFY_HOUR_LOCAL: int = 9
    NOTIFY_WEEKDAYS: str | None = ""

    # Прокси (если нужно)
    HTTP_PROXY_URL: str | None = None

    # OpenAI (если используешь ассистента)
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Самооптимизация конфигураций
    ENABLE_SELF_OPTIMIZATION: bool = False
    OPTIMIZER_BATCH_CHOICES: str = "4,8,16"
    OPTIMIZER_TIMEOUT_CHOICES: str = "8000,12000,16000"
    OPTIMIZER_MEMORY_CHOICES: str = "512,768,1024"
    OPTIMIZER_INTERVAL_SECONDS: int = 300
    OPTIMIZER_REQUIRED_IMPROVEMENT: float = 0.1
    OPTIMIZER_MIN_SAMPLES: int = 3
    OPTIMIZER_METRICS_URL: str = "http://localhost:8000/metrics"
    OPTIMIZER_HTTP_TIMEOUT: float = 2.0
    OPTIMIZER_TARGET_LATENCY_MS: int = 1200
    OPTIMIZER_MEMORY_BUDGET_MB: int = 1024

    # --------- Tribute (подписки) ----------
    TRIBUTE_LINK_BASIC: str = ""
    TRIBUTE_LINK_PRO: str = ""

    TRIBUTE_API_KEY: str = ""
    TRIBUTE_WEBHOOK_PATH: str = "/tribute/webhook"
    WEB_HOST: str = "0.0.0.0"
    WEB_PORT: int = 8080

    # как распознать план по имени из вебхука
    SUB_BASIC_MATCH: str = "basic"
    SUB_PRO_MATCH: str = "pro"

    SUB_BASIC_PRICE: str = "299 ₽/мес"
    SUB_PRO_PRICE: str = "599 ₽/мес"
    # --------------------------------------

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False
    )

    # пример «исправления» случайно оставленного leads_chat_id в окружении
    @field_validator("ADMIN_ID", mode="before")
    @classmethod
    def _fix_admin_id(cls, v):
        # просто показать приём — админ id должен быть int
        return int(v)


settings = Settings()

RUNTIME_CONFIG_DEFAULTS = {
    "BATCH_SIZE": 8,
    "TIMEOUT_MS": 12000,
    "MEMORY_LIMIT_MB": 768,
}

try:
    from optimizer.config_tuner import JSONConfigRepository

    _runtime_repo = JSONConfigRepository(Path("optimizer/runtime_config.json"), RUNTIME_CONFIG_DEFAULTS)
    settings.RUNTIME_CONFIG = _runtime_repo.read()
except Exception:
    settings.RUNTIME_CONFIG = dict(RUNTIME_CONFIG_DEFAULTS)



def get_runtime_config() -> dict[str, int]:
    """Return the latest configuration selected by the optimizer."""

    return dict(getattr(settings, "RUNTIME_CONFIG", RUNTIME_CONFIG_DEFAULTS))

