from __future__ import annotations

from typing import Iterable, List

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_ID: int
    ADMIN_IDS: List[int] = Field(default_factory=list)
    CALLBACK_SECRET: str | None = None

    DATABASE_URL: str | None = None
    REDIS_URL: str | None = None
    LOG_PATH: str | None = None
    DEBUG: bool = False
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
    def _parse_admin_ids(cls, value: Iterable[int] | str | int | None):
        if value is None or value == "":
            return []
        if isinstance(value, (list, tuple, set)):
            return [int(item) for item in value]
        if isinstance(value, int):
            return [int(value)]
        if isinstance(value, str):
            # поддерживаем разные разделители: запятая, пробел, точка с запятой
            parts = [part.strip() for part in value.replace(";", ",").split(",")]
            return [int(part) for part in parts if part]
        raise TypeError("Unsupported type for ADMIN_IDS")

    @model_validator(mode="after")
    def _ensure_admin_ids(self) -> "Settings":
        ids = set(self.ADMIN_IDS)
        ids.add(self.ADMIN_ID)
        self.ADMIN_IDS = sorted(ids)
        return self

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.ADMIN_IDS

    def get_callback_secret(self) -> str:
        return self.CALLBACK_SECRET or self.BOT_TOKEN


settings = Settings()
