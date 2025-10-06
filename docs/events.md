# События и атрибуция

## Источник данных

События сохраняются в памяти в списке `EVENTS` (`app/storage.py`). Добавление происходит через `save_event`, который используется в разных хендлерах (например, `/start`, подписки, уведомления).

```python
from app.storage import save_event
save_event(user_id, source, "action", payload={...})
```

Каждая запись содержит:

- `ts` — время в UTC (`datetime.utcnow().isoformat()`).
- `user_id` — Telegram ID пользователя (может быть `None` для системных событий).
- `source` — источник или реф-код (например, `ref_123`).
- `action` — название события (`start`, `notify_on`, `purchase` и т.д.).
- `payload` — произвольный JSON.

## Где используются

- **/start** (`app/handlers/start.py`) — сохраняет `start`, `ref_join`, `notify_on/off`.
- **Форма лида** (`app/handlers/lead.py`) — добавляет заявки в `LEADS`, но событие можно записать вручную.
- **Webhook Tribute** (`app/handlers/tribute_webhook.py`) — стоит логировать `subscription_activated`/`cancelled` (добавь при необходимости).

## Экспорт и аудит

1. Используй админ-хендлер (`app/handlers/admin.py`) — добавь команду `/admin events` для выгрузки последних N событий.
2. Для ручного экспорта выполни интерактивно:

    ```python
    python - <<'PY'
    from app.storage import EVENTS
    import json
    print(json.dumps(EVENTS[-100:], ensure_ascii=False, indent=2))
    PY
    ```

3. Сохраняй выгрузки в объектное хранилище.

## Политика ретенции

- Оперативные данные хранятся в памяти, очищаются при рестарте.
- Для истории маркетинга сохраняй ежедневный дамп (см. DR-план) и очищай записи старше 90 дней.
