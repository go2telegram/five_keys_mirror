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

> 💡 На Windows перед первым запуском консоли выполните `chcp 65001` и
> `setx PYTHONIOENCODING utf-8`, чтобы избежать проблем с кодировкой.

В `.env` укажите `BOT_TOKEN`, `ADMIN_ID` и другие ключи. По умолчанию используется SQLite (`sqlite+aiosqlite:///./var/bot.db`),
поэтому убедитесь, что установлен драйвер `aiosqlite` (например, через `pip install -r requirements-dev.txt`).
Включение Tribute webhook-а опционально: задайте `RUN_TRIBUTE_WEBHOOK=true`, если нужен приём уведомлений от Tribute.

## Офлайн установка (Windows, Python 3.11)

1) В GitHub Actions запустите workflow **Build offline wheels (win_amd64, py311)** (*Actions → Build offline wheels → Run workflow*), скачайте артефакт `wheels-win_amd64-cp311.zip` и распакуйте его в каталог `./wheels` или любую другую папку (её можно передать через `-WheelsDir` или переменную окружения `WHEELS_DIR`).
2) Создайте и активируйте виртуальное окружение:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
3) Выполните офлайн-установку зависимостей из распакованных колёс (при необходимости укажите путь к внешнему каталогу):
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

## Обновление локальной копии (Windows)

Скрипт `scripts/update_local.cmd` запускает PowerShell-обновление двойным кликом и не закрывает окно при ошибках. Логи сохраняются в `./scripts/logs/update_*.log`.

Альтернативно можно выполнить PowerShell-скрипт напрямую:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\update_local.ps1 -Branch main -WheelsDir "C:\\dev\\_wheels"
```

Ключевые параметры:

- `-Branch` — ветка, которую нужно подтянуть (по умолчанию текущая).
- `-WheelsDir` — путь к каталогу с распакованными колёсами (по умолчанию `./wheels`, можно задать через `WHEELS_DIR`).
- `-NoRunBot` — выполнить обновление без старта `python -m app.main` (удобно для smoke-прогонов).

Скрипт создаёт/активирует `.venv`, подтягивает выбранную ветку (не трогая `wheels/`, `var/`, `logs/`, `dist/`), выполняет офлайн-установку, прогоняет миграции, проверяет БД, снимает вебхук и (если не передан `-NoRunBot`) запускает бота. В конце печатается путь к логу `Log: .\scripts\logs\update_YYYYMMDD_HHMMSS.log`.

## Типовые ошибки апдейтера

- `Offline wheels directory not found` — распакуйте `wheels-win_amd64-cp311.zip` в указанный каталог или передайте `-WheelsDir`.
- `No wheel files detected in ...` — проверьте, что в каталоге действительно лежат `.whl` из артефакта.
- `Missing package: <имя>` — соответствующего `.whl` нет в каталоге; добавьте его и повторите запуск.
- `db_check.py` сообщает `ok: false` — миграции не применились; повторите запуск или выполните `alembic upgrade head` вручную и изучите лог в `./scripts/logs`.
- `ParserError at offline_install.ps1` — файл был испорчен (не-ASCII или неверная кодировка). Апдейтер восстановит рабочую версию автоматически; при необходимости удалите файл и повторите `update_local.ps1`.

## База данных и миграции

Пример `.env`:

```
BOT_TOKEN=123:ABC
DB_URL=sqlite+aiosqlite:///./var/bot.db
TIMEZONE=Europe/Moscow
VELAVIE_URL=https://velavie.example/landing
RUN_TRIBUTE_WEBHOOK=false
TRIBUTE_API_KEY=change-me
TRIBUTE_LINK_BASIC=https://tribute.to/pay/basic
TRIBUTE_LINK_PRO=https://tribute.to/pay/pro
SUB_BASIC_PRICE=299 ₽/мес
SUB_PRO_PRICE=599 ₽/мес
```

Команды:

```bash
make upgrade                  # применить миграции (создаёт var/ автоматически)
make migrate msg="add table"  # сгенерировать миграцию
make db-check                 # предзапусковая проверка состояния БД
make dev                      # локальный запуск (python -m app.main)
make fmt                      # black + ruff --fix
make lint                     # ruff check
```

## Подписка MITO через Tribute

1. В Tribute задайте секрет для вебхуков и пропишите URL `https://<домен>${TRIBUTE_WEBHOOK_PATH}` (по умолчанию `/tribute/webhook`).
2. Сохраните ключ в `.env` (`TRIBUTE_API_KEY`) и включите приём уведомлений `RUN_TRIBUTE_WEBHOOK=true` (в продакшене бот поднимет aiohttp-сервер на `TRIBUTE_PORT`).
3. Укажите ссылки на оплату (`TRIBUTE_LINK_BASIC`, `TRIBUTE_LINK_PRO`) и подписи с ценами (`SUB_BASIC_PRICE`, `SUB_PRO_PRICE`) — они появятся в разделе «Подписка».
4. После оплаты Tribute присылает событие `new_subscription`: бот активирует тариф, сохранит событие и отправит пользователю кнопку «Открыть Premium». При отмене (`cancelled_subscription`) доступ закрывается в дату `expires_at`, а пользователю прилетит напоминание о продлении.
5. Для smoke-проверки достаточно запустить `pytest tests/test_tribute_stub.py` — там проверяется HMAC и базовый разбор payload.

Если вебхук временно недоступен, пользователь всё равно может инициировать проверку через кнопку «🔁 Проверить статус» — бот поднимет данные из базы и покажет текущее состояние подписки.

## Линтинг и pre-commit

### Установка хуков

```bash
make hooks
```

Альтернатива для Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_dev.ps1
```

Скрипт установит `pre-commit`, активирует хуки и при первом запуске прогонит их по всему репозиторию. Если нужно только поставить хуки без полного прогона, добавьте параметр `-InstallOnly`.

### Ручной запуск проверок

```bash
ruff check . --fix
black .
pre-commit run --all-files
```

Комбинация `ruff --fix` и `black` повторяет CI. Для проверки без модификаций используйте `black --check .`.

### Что делать при замечаниях

- `end-of-file-fixer` — добавьте завершающую пустую строку (файлы `*.json`/`*.yml` должны заканчиваться переводом строки).
- `mixed-line-ending` — убедитесь, что `*.ps1` используют CRLF, а YAML/JSON — LF (правила описаны в `.editorconfig`).
- `check-yaml`/`check-json` — проверьте, что каждый ключ содержит `:` и соблюдён отступ в два пробела для вложенных блоков.
- после обновления версий хуков выполняйте `pre-commit autoupdate` и коммитьте изменения `.pre-commit-config.yaml`.

CI автоматически применяет автоисправления к PR: отдельная job прогоняет `ruff --fix`, `black` и `pre-commit run --all-files`, а затем коммитит результат, если появились изменения. Если после автофикса остаются ошибки, их нужно исправить вручную.

## Запуск бота локально

```bash
make dev
```

Команда вызовет `init_db()`, выполнит миграции и запустит polling.
Tribute webhook поднимется только если в `.env` указан `RUN_TRIBUTE_WEBHOOK=true`.

Для локальной диагностики можно включить команду `/ping`, добавив `DEBUG_COMMANDS=true` в `.env`. По умолчанию эта команда скрыта.

## Гарантированный `/start`

Маршрут `/start` состоит из двух слоёв:

- «тонкий» хендлер сразу отвечает приветствием и клавиатурой (`kb_main()`), поэтому пользователь мгновенно видит меню даже при
  проблемах с базой;
- фоновая задача выполняет «толстую» бизнес-логику (создание пользователя, обработка рефералов, предложение включить
  уведомления) и логирует ошибки через `logging.exception("start_full failed")`, не блокируя ответ.

В тестах (`tests/test_updates_smoke.py`) есть проверка, что Dispatcher подписан на `message` и `callback_query`, а стартовый
хендлер отправляет приветствие даже при сбое БД. Для возврата домой из любого раздела используйте `kb_back_home()`, а команда
`/ping` доступна только при `DEBUG_COMMANDS=true`.

## Главное меню

Все разделы доступны из встроенной клавиатуры (`/start` → две колонки):

- ⚡ Тест энергии — `quiz:energy`
- 📐 Калькуляторы — `calc:menu`
- 💊 Подбор продуктов — `pick:menu`
- 🎁 Регистрация — `reg:open`
- 💎 Премиум — `premium:menu`
- 👤 Профиль — `profile:open`
- 🔗 Реф. ссылка — `ref:menu`
- 🎫 Подписка — `sub:menu`
- 🧭 Навигатор — `nav:root`
- 🧾 PDF отчёт — `report:last`
- 🔔 Уведомления — `notify:help`

## Быстрый smoke-чек `/start`

1. Запустите бота локально через `make dev` (или `python -m app.main`).
2. Отправьте `/start` → убедитесь, что приходит приветствие и клавиатура из списка выше.
3. Нажмите пару кнопок: если раздел не готов, бот покажет заглушку с кнопкой «Домой».
4. Установите `DEBUG_COMMANDS=true` в `.env` и перезапустите бота → команда `/ping` должна отвечать `pong ✅`.
5. Верните `DEBUG_COMMANDS=false` — `/ping` снова недоступен.

## Квизы и продуктовые карточки

После завершения любого квиза бот показывает подборку продуктов из каталога: у каждого товара есть название, короткое описание,
ключевые свойства и подсказка «как поможет сейчас» с учётом контекста (энергия, сон, стресс, ЖКТ, иммунитет). Первые изображения
отправляются галереей, а под карточками размещается клавиатура действий:

- «Купить …» — прямая ссылка на продукт;
- «PDF-план» — вызов `report:last` с персональным отчётом;
- «Заказать со скидкой» — открывает Velavie-страницу из `VELAVIE_URL`;
- «Домой» — возврат в главное меню.

Если медиакаталог временно недоступен, бот выводит дружелюбное сообщение и предлагает вернуться домой через отдельную кнопку.

## Калькуляторы

В разделах «MSD идеальный вес» и «ИМТ» бот просит ввести исходные данные, а затем показывает:

- краткое описание результата с пояснением;
- список шагов «Что можно сделать уже сегодня»;
- карточки рекомендованных продуктов с кнопками «Купить», «PDF-план», «Заказать со скидкой», «Назад» и «Домой».

Последний расчёт сохраняется в базе — его можно скачать в PDF через пункт «🧾 PDF отчёт» главного меню.

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
