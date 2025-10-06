# Бизнес-аналитика

Модуль расширенной аналитики включает расчёт ключевых метрик (LTV, CAC, ROI и Retention) и экспорт их в бот и HTTP-интерфейсы.

## Источники данных

До подключения к продакшн-хранилищу используется промежуточное in-memory хранилище в `app.storage`. Для синхронизации с Data Lake необходимо записывать события через функции:

- `record_revenue(amount, user_id, source, ts)` — финансовые поступления.
- `record_cost(amount, category, ts, source)` — операционные расходы.
- `record_acquisition(user_id, cost, source, ts)` — маркетинговые затраты на привлечение.
- `record_retention(user_id, day, active, ts)` — статус удержания по пользователю.

Эти данные лежат в структурах `FINANCE_OPERATIONS`, `CUSTOMER_ACQUISITIONS` и `RETENTION_EVENTS`. Метрики агрегируются функцией `collect_business_metrics()` из `analytics.business`.

## Метрики

Расчёт показателей основан на классических формулах:

- **Выручка** — сумма событий `record_revenue`.
- **LTV** — выручка / количество платящих пользователей.
- **CAC** — сумма маркетинговых затрат / количество новых клиентов.
- **ROI** — `(выручка − (маркетинг + операционные)) / (маркетинг + операционные)`.
- **Retention** — доля пользователей с последним `record_retention(..., active=True)`.

## Интерфейсы

- `/finance` (только для администратора) — краткий отчёт в Telegram.
- HTTP `GET /admin` — HTML-дашборд с текущими значениями.
- HTTP `GET /metrics` — экспорт в формате Prometheus/Grafana.

Функция `format_finance_report` формирует текст для бота, `render_admin_dashboard` — HTML-страницу, `render_prometheus` — payload для метрик.

## Управление фичей

Фича управляется флагом `ENABLE_BUSINESS_ANALYTICS` (см. `app.config`). Для быстрого отката выставьте `ENABLE_BUSINESS_ANALYTICS=false` в окружении — это отключит маршруты `/finance`, `/admin`, `/metrics` и не будет подключать соответствующий роутер.
