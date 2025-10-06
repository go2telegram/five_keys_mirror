from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


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

    ENABLE_PREDICTIVE_PLANNER: bool = True
    FORECAST_METRICS: str = "rps,revenue_total,error_rate"
    FORECAST_DAYS: int = 7
    FORECAST_HOUR_LOCAL: int = 8
    FORECAST_MINUTE_LOCAL: int = 0

    # Прокси (если нужно)
    HTTP_PROXY_URL: str | None = None

    # OpenAI (если используешь ассистента)
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"

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
