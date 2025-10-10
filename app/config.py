from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: str = ""
    DEV_DRY_RUN: bool = False
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
    BASE_PRODUCT_URL: str = ""
    BASE_REGISTER_URL: str = ""
    LINK_AUTOBUILD: bool = True

    # Напоминания
    NOTIFY_HOUR_LOCAL: int = 9
    NOTIFY_WEEKDAYS: str | None = ""
    RETENTION_ENABLED: bool = False
    SCHEDULER_ENABLE_NUDGES: bool = True
    WEEKLY_PLAN_ENABLED: bool = True
    ANALYTICS_EXPORT_ENABLED: bool = True

    # Прокси (если нужно)
    HTTP_PROXY_URL: str | None = None

    # HTTP клиенты
    HTTP_TIMEOUT_CONNECT: float = 3.0
    HTTP_TIMEOUT_READ: float = 15.0
    HTTP_TIMEOUT_WRITE: float = 15.0
    HTTP_TIMEOUT_TOTAL: float = 30.0
    HTTP_RETRY_ATTEMPTS: int = 2
    HTTP_RETRY_BACKOFF_INITIAL: float = 0.5
    HTTP_RETRY_BACKOFF_MAX: float = 8.0
    HTTP_RETRY_STATUS_CODES: tuple[int, ...] = (500, 502, 503, 504)
    HTTP_CIRCUIT_BREAKER_MAX_FAILURES: int = 5
    HTTP_CIRCUIT_BREAKER_BASE_DELAY: float = 1.0
    HTTP_CIRCUIT_BREAKER_MAX_DELAY: float = 30.0

    # OpenAI (если используешь ассистента)
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"
    AI_PLAN_MODEL: str = "gpt-4o-mini"
    WEEKLY_PLAN_CRON: str = "mon@10"
    ANALYTICS_EXPORT_CRON: str | None = "0 21 * * *"
    ANALYTICS_EXPORT_PATH: str = "exports/analytics_snapshot.json"
    PLAN_ARCHIVE_DIR: str = "var/plans"

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

    ENVIRONMENT: str = Field(default="local")

    # Feature flags & rollout controls
    FF_NEW_ONBOARDING: bool = False
    FF_QUIZ_GUARD: bool = False
    FF_NAV_FOOTER: bool = False
    FF_MEDIA_PROXY: bool = False
    CANARY_PERCENT: int = Field(default=0, ge=0, le=100)
    FEATURE_FLAGS_FILE: str = Field(default="var/feature_flags.json")

    # Мониторинг/алерты
    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = Field(default=0.0, ge=0.0, le=1.0)
    HEARTBEAT_INTERVAL_MINUTES: int = Field(default=5, ge=1, le=60)

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

    @model_validator(mode="after")
    def _apply_stage_defaults(self) -> "Settings":
        env = (self.ENVIRONMENT or "").strip().lower()
        if env == "stage":
            stage_flags = {
                "FF_NEW_ONBOARDING",
                "FF_QUIZ_GUARD",
                "FF_NAV_FOOTER",
                "FF_MEDIA_PROXY",
            }
            for flag in stage_flags:
                if flag not in self.model_fields_set:
                    setattr(self, flag, True)
        return self

    @property
    def velavie_url(self) -> str:
        """Return the primary Velavie landing URL used across menus."""

        return self.VELAVIE_URL or self.VILAVI_REF_LINK_DISCOUNT or self.VILAVI_ORDER_NO_REG


settings = Settings()
