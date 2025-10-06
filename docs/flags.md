# Фича-флаги и конфигурация

Конфигурация хранится в `app/config.py` на базе `pydantic_settings`. Переменные подтягиваются из `.env`. Флаги — булевые или строковые значения, включающие функциональность.

## Основные переменные

| Переменная | Тип | Назначение | Модули |
|------------|-----|------------|--------|
| `BOT_TOKEN` | str | Telegram-токен бота | `app/main.py` |
| `ADMIN_ID` | int | Telegram ID администратора (доступ к /admin, уведомления) | `app/handlers/admin.py`, `app/handlers/lead.py` |
| `HTTP_PROXY_URL` | Optional[str] | Использовать HTTP(S) прокси при обращении к внешним API | `app/utils_media.py` |
| `OPENAI_*` | str | Включают ассистента и генерацию текстов | `app/utils_openai.py`, `app/scheduler/jobs.py` |
| `TRIBUTE_LINK_BASIC`, `TRIBUTE_LINK_PRO` | str | Публикуют кнопки подписки | `app/handlers/subscription.py` |
| `TRIBUTE_API_KEY` | str | Подпись вебхука Tribute | `app/handlers/tribute_webhook.py` |
| `TRIBUTE_WEBHOOK_PATH`, `WEB_HOST`, `WEB_PORT` | str/int | Настройки aiohttp сервера | `app/main.py` |
| `SUB_*` | str | Имена/цены планов и ключевые слова для маппинга | `app/handlers/tribute_webhook.py`, `app/handlers/subscription.py` |
| `VILAVI_REF_LINK_DISCOUNT`, `VILAVI_ORDER_NO_REG` | str | Управляют ссылками в квизах и меню | `app/keyboards.py`, `app/handlers/quiz_*`, `app/pdf_report.py` |
| `NOTIFY_HOUR_LOCAL`, `NOTIFY_WEEKDAYS` | int/str | Управляют расписанием рассылок | `app/scheduler/service.py` |

## Практика использования

- Для отключения кнопок подписки оставь `TRIBUTE_LINK_*` пустыми — кнопки не появятся (см. условие в `app/handlers/subscription.py`).
- Чтобы приостановить напоминания, очисти `NOTIFY_WEEKDAYS` или установи `NOTIFY_HOUR_LOCAL` в нерабочее время.
- При тестировании OpenAI оставь `OPENAI_API_KEY` пустым — `ai_generate` вернёт fallback текст (`app/utils_openai.py`).
- Если требуется прокси, укажи `HTTP_PROXY_URL` — это повлияет на загрузку медиа (`app/utils_media.py`).

## Процесс изменения

1. Обнови `.env` и задокументируй изменение (коммит + PR).
2. При критичных изменениях (бот, Tribute) согласуй с владельцем продукта.
3. Проверь значения через `/admin config` (добавь команду при необходимости) или через отладочный вывод.
