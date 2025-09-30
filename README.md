# five_keys_bot

Ассистент Telegram для MITO-сообщества. Бот собирает заявки, выдаёт рекомендации и управляет подписками.

## Требования

- Python 3.11+
- Poetry или venv (пример ниже использует `python -m venv`)
- Docker (для продового запуска)

## Установка (dev)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

В `.env` укажите `BOT_TOKEN`, `ADMIN_ID` и другие ключи. По умолчанию используется SQLite (`sqlite+aiosqlite:///./var/bot.db`).

## Миграции

```bash
alembic upgrade head      # применить
alembic downgrade -1      # откатить одну миграцию
alembic revision -m "msg" # создать новую
```

Перед первым запуском создайте папку `var/` (скрипты делают это автоматически) и прогоните `alembic upgrade head`.

## Запуск бота локально

```bash
python -m app.main
```

Команда вызовет `init_db()`, выполнит миграции и поднимет polling + aiohttp webhook сервер Tribute.

## Тесты

```bash
pytest
```

## Docker (prod)

1. Создайте `.env` с параметрами Postgres (`DB_URL=postgresql+asyncpg://...`).
2. Запустите:
   ```bash
   docker compose up --build
   ```

Docker-compose поднимет Postgres, выполнит миграции и запустит бота от non-root пользователя.

## Структура

- `app/db` — модели и сессии SQLAlchemy.
- `app/repo` — репозитории для async-доступа.
- `alembic` — миграции.
- `app/handlers` — aiogram-роутеры.
- `tests/` — юнит-тесты репозиториев.

## Полезное

- `python -m app.main` — основной вход.
- `alembic current` — проверить версию схемы.
- `make dev` / `make migrate msg=...` — см. Makefile.
