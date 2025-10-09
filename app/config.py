from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: str = ""
    ADMIN_ID: int = 0
    ADMIN_USER_IDS: list[int] | str = Field(default_factory=list)
    LEADS_CHAT_ID: int | None = None

    DB_URL: str = "sqlite+aiosqlite:///./var/bot.db"
    MIGRATE_ON_START: bool = Field(
        default=True,
        validation_alias=AliasChoices("MIGRATE_ON_START", "DB_MIGRATE_ON_START"),
    )
    REDIS_URL: str | None = None
    TIMEZONE: str = "Europe/Moscow"

    # CRM/экспорт
    CRM_EXPORT_MODE: str = Field(default="csv")
    CRM_EXPORT_CSV_PATH: str = Field(default="exports/crm_leads.csv")
    GOOGLE_SHEET_ID: str | None = None
    GOOGLE_WORKSHEET_TITLE: str = Field(default="Leads")
    GOOGLE_SERVICE_ACCOUNT_FILE: str | None = None
    GOOGLE_SERVICE_ACCOUNT_INFO: str | None = None

    # Логи
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"

    # Партнёрские/коммерческие ссылки
    VILAVI_REF_LINK_DISCOUNT: str = ""
    VILAVI_ORDER_NO_REG: str = ""
    VELAVIE_URL: str = ""

    # Напоминания
    NOTIFY_HOUR_LOCAL: int = 9
    NOTIFY_WEEKDAYS: str | None = ""
    RETENTION_ENABLED: bool = False

    # Прокси (если нужно)
    HTTP_PROXY_URL: str | None = None

    # OpenAI (если используешь ассистента)
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Каталог и квизы: онлайн/офлайн режимы
    IMAGES_MODE: str = "catalog_remote"
    IMAGES_BASE: str = "https://raw.githubusercontent.com/go2telegram/media/1312d74492d26a8de5b8a65af38293fe6bf8ccc5/media/products"
    IMAGES_DIR: str = "app/static/images/products"
    QUIZ_IMAGE_MODE: str = "remote"
    QUIZ_IMG_BASE: str = "https://raw.githubusercontent.com/go2telegram/media/1312d74492d26a8de5b8a65af38293fe6bf8ccc5/media/quizzes"

    # --------- Tribute (подписки) ----------
    TRIBUTE_LINK_BASIC: str = ""
    TRIBUTE_LINK_PRO: str = ""

    TRIBUTE_API_KEY: str = ""
    TRIBUTE_WEBHOOK_PATH: str = "/tribute/webhook"
    SERVICE_HOST: str = "127.0.0.1"
    HEALTH_PORT: int = 8080
    WEB_HOST: str = "0.0.0.0"
    WEB_PORT: int = 8080
    RUN_TRIBUTE_WEBHOOK: bool = False
    TRIBUTE_PORT: int = 8080

    DEBUG_COMMANDS: bool = False

    # Мониторинг/алерты
    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = Field(default=0.0, ge=0.0, le=1.0)

    # Админ-панель / FastAPI dashboard
    DASHBOARD_ENABLED: bool = True
    DASHBOARD_HOST: str = "0.0.0.0"
    DASHBOARD_PORT: int = 8081
    DASHBOARD_TOKEN: str = ""

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
        case_sensitive=False,
    )

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

    @property
    def velavie_url(self) -> str:
        """Return the primary Velavie landing URL used across menus."""

        return self.VELAVIE_URL or self.VILAVI_REF_LINK_DISCOUNT or self.VILAVI_ORDER_NO_REG


settings = Settings()
