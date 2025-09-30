# five_keys_bot

Ассистент Telegram для MITO-сообщества. Бот собирает заявки, выдаёт рекомендации и управляет подписками.

## Требования

- Python 3.11+
- venv или любая другая система виртуальных окружений
- Docker (для продового запуска)

## Установка (dev)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt  # включает aiosqlite для SQLite
cp .env.example .env
```

В `.env` укажите `BOT_TOKEN`, `ADMIN_ID` и другие ключи. По умолчанию используется SQLite (`sqlite+aiosqlite:///./var/bot.db`),
поэтому убедитесь, что установлен драйвер `aiosqlite` (например, через `pip install -r requirements-dev.txt`).
Включение Tribute webhook-а опционально: задайте `RUN_TRIBUTE_WEBHOOK=true`, если нужен приём уведомлений от Tribute.

## Офлайн установка (Windows, Python 3.11)

1) В GitHub Actions запустите workflow **Build offline wheels (win_amd64, py311)** (*Actions → Build offline wheels → Run workflow*), скачайте артефакт `wheels-win_amd64-cp311.zip` и распакуйте его в каталог `./wheels`.
2) Создайте и активируйте виртуальное окружение:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
3) Выполните офлайн-установку зависимостей из распакованных колёс:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\offline_install.ps1 -WheelsDir .\wheels
   ```
4) Подготовьте `.env` с ключами (`BOT_TOKEN`, `DB_URL=sqlite+aiosqlite:///./var/bot.db`, `TIMEZONE`, `ADMIN_ID`).
5) Примените миграции и убедитесь, что проверка БД проходит успешно:
   ```powershell
   mkdir var
   alembic upgrade head
   python scripts\db_check.py  # ok должно быть true
   ```
6) Запустите бота:
   ```powershell
   python -m app.main
   ```

## База данных и миграции

Пример `.env`:

```
BOT_TOKEN=123:ABC
DB_URL=sqlite+aiosqlite:///./var/bot.db
TIMEZONE=Europe/Moscow
```

Команды:

```bash
make upgrade                  # применить миграции (создаёт var/ автоматически)
make migrate msg="add table"  # сгенерировать миграцию
make db-check                 # предзапусковая проверка состояния БД
make dev                      # локальный запуск (python -m app.main)
```

## Запуск бота локально

```bash
make dev
```

Команда вызовет `init_db()`, выполнит миграции и запустит polling.
Tribute webhook поднимется только если в `.env` указан `RUN_TRIBUTE_WEBHOOK=true`.

## Admin CRUD

Для администратора доступны команды управления базой (нужен `ADMIN_ID` или `ADMIN_USER_IDS` в `.env`):

- `/admin_help` — справка по доступным операциям.
- `/users [page] [query]` — список пользователей (пагинация, поиск по username/id).
- `/user <id>` — карточка пользователя и подписки.
- `/sub_get <id>` / `/sub_set <id> <plan> <days>` / `/sub_del <id>` — управление подписками.
- `/refs <id> [period]` — список рефералов (периоды `7d`, `30d`, `all`).
- `/ref_convert <invited_id> [bonus_days]` — отметить конверсию и начислить бонусные дни рефереру.

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
