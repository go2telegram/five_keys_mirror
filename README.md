# five_keys_bot

Ассистент Telegram для MITO-сообщества. Бот собирает заявки, выдаёт рекомендации и управляет подписками.

## Каталог

Для обновления каталога продуктов используйте импортёр. Он умеет работать как с локальными файлами, так и с медиарепозиторием на GitHub и проверяет согласованность данных, чтобы держать стабильные «38/38».

### Где лежат материалы каталога

- ✍️ Описания продуктов — в `app/catalog/descriptions/` (каждый продукт — отдельный `.txt`).
- 🖼️ Картинки — в `app/catalog/images/products/` (допускаются `.jpg/.jpeg/.png/.webp`).
- 🗂️ Сводка сборки появляется в `build_summary.json`, а также доступна в боте по `/catalog_report`.

Структуру каталогов можно расширять подпапками — главное, чтобы в них попадали файлы нужного типа.

### Быстрая сборка (online по умолчанию)

```bash
python tools/build_products.py build
python tools/build_products.py validate
```

Импортёр использует pinned SHA `1312d74492d26a8de5b8a65af38293fe6bf8ccc5` из медиарепозитория и подставляет RAW-URL вида `https://raw.githubusercontent.com/go2telegram/media/<sha>/media/products/...`. Так Telegram сразу подтянет изображения по ссылке. Параметр `--images-base` позволяет временно переключиться на другую ревизию или ветку (`main` и т.п.).

Флаги `--strict-images` и `--strict-descriptions` заставляют импортёр автоматически фиксировать новые артефакты в `build_summary.json` и падать, если что-то потеряно. Пара `--expect-count from=images --fail-on-mismatch` продолжает гарантировать, что количество собранных продуктов равно количеству картинок.

### Сборка локально (offline)

Если нужно полностью офлайн-собирание (например, при работе с новыми моками), переключите режим на локальный и укажите каталог с изображениями:

```bash
export IMAGES_MODE=catalog_local

python tools/build_products.py build \
  --descriptions-path "app/catalog/descriptions" \
  --images-dir "app/static/images/products" \
  --strict-images --strict-descriptions \
  --expect-count from=images --fail-on-mismatch

python tools/build_products.py validate
```

Можно также передать все параметры напрямую без изменения окружения.

### Отчётность и контроль «38/38»

После успешной сборки проверьте отчёт:

- локально изучите `build_summary.json` — в нём отражаются найденные описания, изображения, алиасы и предупреждения;
- в продовой среде запросите `/catalog_report` и убедитесь, что бот показывает `built=38`.

Команда `/catalog_reload` в Telegram подтянет свежий `products.json` без рестарта бота.

### Переключение онлайн/офлайн-режимов

В `.env` доступны переменные для тонкой настройки источников:

```env
IMAGES_MODE=catalog_remote   # или catalog_local для офлайн-сборки
IMAGES_BASE=.../media/products
IMAGES_DIR=app/static/images/products
QUIZ_IMAGE_MODE=remote       # переключите на local, чтобы слать картинки с диска
QUIZ_IMG_BASE=.../media/quizzes
```

Поменяли значение — перезапустите бота или перезапустите команду сборки, и новые настройки подтянутся автоматически.

### Run checks локально vs CI

В песочнице Codex все проверки выполняются офлайн, поэтому достаточно запустить:

```bash
python -m pip install -r requirements.txt
python tools/build_products.py validate
pytest -q
```

Шаги, требующие выхода в интернет (онлайн-сборка каталога и `tools/head_check.py`), остаются только в GitHub Actions. Там окружение
получает доступ к медиарепозиторию и гарантирует, что изображения по удалённым URL отвечают.

### FAQ

**Что делать при mismatch?**

Посмотрите секции `missing_images` и `unmatched_images` в `build_summary.json`. Убедитесь, что файлы попадают в нужные каталоги, названы по slug продукта и имеют одно из поддерживаемых расширений. После исправлений перезапустите сборку в строгом режиме.

**Как добавить alias?**

Импортёр сам генерирует базовые алиасы из slug. Чтобы добавить ручной псевдоним, пропишите его в списке `aliases` соответствующего блока описания либо добавьте вариант имени в названии файла/картинки. В следующей сборке alias появится в `products.json`.

Если quick fix нужен без пересборки каталога, можно добавить сопоставление в `app/catalog/aliases.json`. Этот файл загружается при старте бота и переопределяет алиасы в каталоге.

**Как нормализовать имена?**

Используйте `python tools/parse_descriptions.py --descriptions-path app/catalog/descriptions --out build/descriptions.json`, чтобы увидеть, какие slug и теги получаются из текущих названий. Скрипт показывает финальные `id`, поэтому легко понять, как переименовать файлы и изображения, чтобы они совпали.

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

Скрипт `scripts/update_local.cmd` запускает PowerShell-обновление двойным кликом и не закрывает окно при ошибках. Логи сохраняются в `./scripts/logs/update_*.log`. После обновления в `app/build_info.py` фиксируется ветка/коммит и время сборки, а в журнале появляются строки вида `build: branch=... commit=...`.

Альтернативно можно выполнить PowerShell-скрипт напрямую:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\update_local.ps1 -Branch main -WheelsDir "C:\\dev\\_wheels"
```

Ключевые параметры:

- `-Branch` — ветка, которую нужно подтянуть (по умолчанию текущая).
- `-WheelsDir` — путь к каталогу с распакованными колёсами (по умолчанию `./wheels`, можно задать через `WHEELS_DIR`).
- `-NoRunBot` — выполнить обновление без старта `python -m app.main` (удобно для smoke-прогонов).

Скрипт создаёт/активирует `.venv`, подтягивает выбранную ветку (не трогая `wheels/`, `var/`, `logs/`, `dist/`), выполняет офлайн-установку, прогоняет миграции, проверяет БД, снимает вебхук и (если не передан `-NoRunBot`) запускает бота. В конце печатается путь к логу `Log: .\scripts\logs\update_YYYYMMDD_HHMMSS.log`.

## Логи и аудит

Бот пишет журналы в консоль и в файлы (по умолчанию `./logs/bot.log` и `./logs/errors.log`). Поведение настраивается переменными окружения:

```
LOG_LEVEL=INFO   # DEBUG/INFO/WARNING/ERROR
LOG_DIR=logs     # каталог для файлов журнала
```

Полезные команды в PowerShell:

```powershell
Get-Content .\logs\bot.log -Wait -Encoding UTF8     # потоковое наблюдение за основным логом
Get-Content .\logs\errors.log -Tail 50 -Encoding UTF8

Для быстрой проверки окружения и статуса бота используйте `scripts/doctor.ps1`:

```
powershell -ExecutionPolicy Bypass -File .\scripts\doctor.ps1
```

Скрипт выводит состояние venv, ветки Git, наличие audit-middleware, корректность CRLF в PowerShell-скриптах и статус Telegram вебхука.
```

В файле `bot.log` фиксируются все сообщения и колбэки (префиксы `MSG` и `CB`), а также служебные маркеры:

- `logging initialized...` — запуск конфигурации логов и пути к файлам;
- `build: branch=... commit=...` / `aiogram=...` / `allowed_updates=['message', 'callback_query']` — бот стартует с ожидаемыми параметрами;
- `Audit middleware registered` и `startup event fired` — аудит точно подключён и сработал хук старта;
- каждые ~60 секунд heartbeat: `heartbeat alive tz=... pending_tasks=...`;
- префикс `UPD kind=Update ...` появляется даже до разбора сообщения, затем идут `MSG ... msg_id=...` и `CB ... cb_id=...`.

Если какой-то маркер отсутствует или бот не отвечает на `/ping`, выполните `scripts/doctor.ps1` — скрипт подскажет, какие проверки не пройдены и что сделать дальше.

Аудит подключён как `dp.update.outer_middleware`, поэтому в журнал попадают любые типы апдейтов. В `errors.log` собираются предупреждения и ошибки. Если нужно временно повысить детализацию, установите `LOG_LEVEL=DEBUG` и перезапустите бота.

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
MIGRATE_ON_START=true
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

## Каталог продуктов
Источник описаний: репозиторий `go2telegram/media` → `media/descriptions/*.txt`
Картинки: `go2telegram/media` → `media/products/*`

Сборка/валидация:
```bash
make build-products
make validate-products
```
Каталог: `app/catalog/products.json` (валидируется схемой `app/data/products.schema.json`).
CI автоматически собирает/валидирует каталог на каждом PR/commit.

## Быстрый запуск (dev)
```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export BOT_TOKEN="xxx" HEALTH_PORT=8080
python run.py
```
Проверки:
- `GET http://localhost:8080/ping` → ok
- `GET http://localhost:8080/metrics` → Prometheus-метрики
- В боте: `/version`, `/catalog`, `/product <id>`

## Главное меню

Все разделы доступны из встроенной клавиатуры (`/start` → две колонки):

- 🧠 Меню тестов — `tests:menu`
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

## Минимальный маршрут для нового пользователя

1. Отправьте `/start`, чтобы получить приветствие и главное меню.
2. Пройдите любой квиз или калькулятор — по завершении бот сохранит план и предложит карточки продуктов с кнопками «Купить», «PDF-план», «Заказать со скидкой» и «Консультация».
3. Нажмите «🧾 PDF отчёт», чтобы сразу выгрузить последнюю рекомендацию в формате PDF.
4. Перейдите в «🎫 Подписка» или «💎 Премиум», чтобы увидеть доступные тарифы и оформить расширенный доступ через Tribute.
5. Используйте «🔔 Уведомления» для включения напоминаний и не забывайте возвращаться домой через встроенную кнопку «🏠 Домой» — она доступна в каждом разделе.

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
