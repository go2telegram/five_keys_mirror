from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: str = ""
    ADMIN_ID: int = 0
    ADMIN_USER_IDS: list[int] = Field(default_factory=list)
    LEADS_CHAT_ID: int | None = None

    DB_URL: str = "sqlite+aiosqlite:///./var/bot.db"
    REDIS_URL: str | None = None
    TIMEZONE: str = "Europe/Moscow"

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

    # --------- Tribute (подписки) ----------
    TRIBUTE_LINK_BASIC: str = ""
    TRIBUTE_LINK_PRO: str = ""

    TRIBUTE_API_KEY: str = ""
    TRIBUTE_WEBHOOK_PATH: str = "/tribute/webhook"
    WEB_HOST: str = "0.0.0.0"
    WEB_PORT: int = 8080
    RUN_TRIBUTE_WEBHOOK: bool = False
    TRIBUTE_PORT: int = 8080

    DEBUG_COMMANDS: bool = False

    # как распознать план по имени из вебхука
    SUB_BASIC_MATCH: str = "basic"
    SUB_PRO_MATCH: str = "pro"

    SUB_BASIC_PRICE: str = "299 ₽/мес"
    SUB_PRO_PRICE: str = "599 ₽/мес"
    # --------------------------------------

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)

    # пример «исправления» случайно оставленного leads_chat_id в окружении
    @field_validator("ADMIN_ID", mode="before")
    @classmethod
    def _fix_admin_id(cls, v):
        # просто показать приём — админ id должен быть int
        if v in (None, ""):
            return 0
        return int(v)

    @field_validator("ADMIN_USER_IDS", mode="before")
    @classmethod
    def _parse_admin_ids(cls, v):
        if v in (None, "", []):
            return []
        if isinstance(v, (list, tuple, set)):
            return [int(item) for item in v]
        parts = [part.strip() for part in str(v).split(",") if part.strip()]
        return [int(part) for part in parts]


settings = Settings()
