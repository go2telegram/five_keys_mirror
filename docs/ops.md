# Эксплуатация, SLO и Runbook

## Service Level Objectives

| Цель | Метрика | Порог | Способ измерения |
|------|---------|-------|------------------|
| Доступность Telegram-бота | Успешные ответы на `/start` | ≥ 99.5 % за 30 дней | Каждые 5 минут synthetic-check: отправить `/start`, убедиться в ответе `WELCOME` из `app/texts.py`. Ошибки >0.5 % от общего числа — инцидент. |
| Доставка напоминаний | Кол-во сообщений, отправленных `send_nudges` | ≥ 97 % пользователей с `subs=True` | Логировать результат джобы `send_nudges` из `app/scheduler/jobs.py`. Сравнивать с числом активных подписчиков `app/storage.USERS`. |
| Вебхук Tribute | Успешные HTTP 2xx ответы | 100 % | Мониторинг access-логов `aiohttp` сервера в `app/main.py` (роут `settings.TRIBUTE_WEBHOOK_PATH`). Ошибка => incident. |

## Runbook (Production)

### 1. Первичная проверка

1. Посмотри на дашборд synthetic-check. Если `/start` падает, вручную отправь `/start` боту.
2. Проверь логи сервиса (`journalctl -u five-keys-bot` или docker logs).
3. Убедись, что процесс запущен и слушает вебхук: `curl http://<host>:<port><TRIBUTE_WEBHOOK_PATH>` должен вернуть `405` (ожидаемый ответ от aiohttp). Параметры берутся из `app/config.py` и `app/main.py`.

### 2. Telegram-подключение

1. Убедись, что токен `BOT_TOKEN` валиден (`app/config.py`).
2. Перезапусти процесс: `systemctl restart five-keys-bot` или `docker compose restart bot`.
3. Повтори synthetic-check `/start`. Если ответа нет — создавай инцидент P1.

### 3. Планировщик рассылок

1. Выполни `python -m app.scheduler.jobs` в интерактивной оболочке, чтобы вручную вызвать `send_nudges` (можно через `python - <<'PY' ...`).
2. Проверь, что `settings.NOTIFY_WEEKDAYS` и `settings.NOTIFY_HOUR_LOCAL` заданы корректно (`app/scheduler/service.py`).
3. Если APScheduler не стартует, убедись, что `start_scheduler(bot)` вызывается в `app/main.py` и нет исключения при импорте.

### 4. Tribute webhook и платежи

1. Посмотри последние вызовы `/tribute/webhook` в логах.
2. Проверяй HMAC: `settings.TRIBUTE_API_KEY` должен совпадать с ключом из Tribute (`app/handlers/tribute_webhook.py`).
3. Если webhook недоступен, временно отключи автопродление в Tribute и уведомь владельцев.

### 5. Коммуникация

- Еscalate в чат on-call, если недоступность > 15 минут.
- Фиксируй все действия в Incident doc.

## Метрики и наблюдаемость

- **Synthetic `/start`** — ответ на команду из `app/handlers/start.py`. Логируй статус.
- **События `storage.EVENTS`** — их можно дампить через `/admin events` (см. `app/storage.py` и `app/handlers/admin.py`).
- **Лиды `storage.LEADS`** — количество новых заявок за сутки.
- **Job latency** — время выполнения `send_nudges`. Добавь лог вокруг вызова.
- **Ошибки Tribute** — HTTP статус и сообщение исключения из `app/handlers/tribute_webhook.py`.

## How-to Dev

1. Создай `.env` на основе боевого, содержащий как минимум `BOT_TOKEN`, `ADMIN_ID`, `TRIBUTE_API_KEY`, `TRIBUTE_LINK_*`, `OPENAI_API_KEY` (если используешь ассистента). Все переменные документированы в `app/config.py`.
2. Установи dev-зависимости: `pip install -r requirements.txt`.
3. Запусти бота локально: `python -m app.main`.
4. Для работы планировщика локально оставь консоль открытой — APScheduler запускается внутри `start_scheduler` (`app/scheduler/service.py`).
5. Для генерации PDF планов требуются шрифты из `app/fonts/`. Проверь пути в `app/pdf_report.py`.
6. API-доки: `pdoc -o docs/api app`, затем `mkdocs serve`.

## Change Management

- Каждое изменение, влияющее на UX или логику в `app/handlers`, сопровождается обновлением документации.
- Перед релизом прогоняй smoke-тест: `/start`, прохождение любого квиза, заявка на консультацию.
