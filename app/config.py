from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_ID: int
    ADMIN_IDS: tuple[int, ...] = ()

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

    # --------- Tribute (подписки) ----------
    TRIBUTE_LINK_BASIC: str = ""
    TRIBUTE_LINK_PRO: str = ""

    TRIBUTE_API_KEY: str = ""
    TRIBUTE_WEBHOOK_PATH: str = "/tribute/webhook"
    WEB_HOST: str = "0.0.0.0"
    WEB_PORT: int = 8080

    PROMETHEUS_URL: str | None = None
    PROMETHEUS_BEARER_TOKEN: str | None = None

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

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def _parse_admin_ids(cls, v):
        if not v:
            return ()
        if isinstance(v, (list, tuple, set)):
            return tuple(int(item) for item in v)
        return tuple(
            int(item.strip())
            for item in str(v).split(",")
            if item and item.strip()
        )

    @property
    def admin_chat_ids(self) -> tuple[int, ...]:
        ids = {self.ADMIN_ID}
        ids.update(self.ADMIN_IDS)
        return tuple(sorted(ids))

    def is_admin(self, user_id: int) -> bool:
        return user_id == self.ADMIN_ID or user_id in self.ADMIN_IDS


settings = Settings()
