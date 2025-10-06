# Data Lake и историческая аналитика

## Структура данных

* Сырые события пишутся в `logs/events.log` (JSON по строкам).
* Ежедневные слои хранилища — `data/events_YYYYMMDD.parquet`.
* При использовании ClickHouse целевая таблица — `analytics.events`.

Стабильная схема события:

| Поле    | Тип           | Описание                                  |
|---------|---------------|-------------------------------------------|
| `ts`    | `DateTime64`  | Момент события в UTC.                     |
| `user_id` | `String`    | Уникальный идентификатор пользователя.   |
| `event` | `String`      | Имя события.                              |
| `props` | `JSON`        | Дополнительные атрибуты события.         |
| `segment` | `String`    | Маркетинговый сегмент (может быть пустым).|
| `source` | `String`     | Источник трафика (может быть пустым).    |

## Ежедневный ETL

Запустить ETL можно в двух режимах: экспорт в Parquet или загрузка в ClickHouse.

```bash
python analytics/etl_daily.py --date=$(date -I) --sink=parquet
python analytics/etl_daily.py --date=$(date -I) --sink=clickhouse --table=analytics.events
```

* `--date` — дата выгрузки (UTC) в формате `YYYY-MM-DD`.
* `--sink` — тип хранилища (`parquet` или `clickhouse`).
* `--table` — имя таблицы ClickHouse `<db>.<table>` (по умолчанию `analytics.events`).

Логи читаются из `logs/events.log`. Скрипт автоматически создаёт `data/` и целевую таблицу в ClickHouse.

## Настройки окружения

| Переменная         | Значение по умолчанию    | Назначение                               |
|--------------------|--------------------------|------------------------------------------|
| `CLICKHOUSE_URL`   | `http://localhost:8123`  | HTTP эндпоинт ClickHouse.                |
| `DATA_DIR`         | `data`                   | Каталог для Parquet-файлов.              |
| `LOGS_DIR`         | `logs`                   | Каталог, где лежат сырые логи событий.   |

## Дашборды Retention и MoM

В Grafana создайте datasource ClickHouse или Parquet (через SQLite/Parquet plugin). Рекомендуемые запросы:

### Когортный Retention

```sql
WITH cohort AS (
    SELECT
        user_id,
        toStartOfMonth(ts) AS cohort_month,
        min(ts) AS first_seen
    FROM analytics.events
    GROUP BY user_id
),
activity AS (
    SELECT
        e.user_id,
        cohort.cohort_month,
        dateDiff('month', cohort.first_seen, e.ts) AS month_offset
    FROM analytics.events e
    INNER JOIN cohort ON cohort.user_id = e.user_id
)
SELECT
    cohort_month,
    month_offset,
    uniqExact(user_id) AS users
FROM activity
GROUP BY cohort_month, month_offset
ORDER BY cohort_month, month_offset;
```

Постройте heatmap со значениями `users` и нормализацией по первой колонке.

### Month-over-Month (MoM)

```sql
SELECT
    toStartOfMonth(ts) AS month,
    event,
    count() AS events,
    round(100 * (events / lagInFrame(events) OVER (PARTITION BY event ORDER BY month) - 1), 2) AS mom_percent
FROM analytics.events
GROUP BY month, event
ORDER BY month, event;
```

Для графика MoM используйте комбинированный график: столбцы `events` и линия `mom_percent`.

## Docker Compose (опционально)

Для локального ClickHouse и Grafana добавьте в `docker-compose.yml`:

```yaml
services:
  clickhouse:
    image: clickhouse/clickhouse-server:24.8
    ports:
      - "8123:8123"
    volumes:
      - ./data/clickhouse:/var/lib/clickhouse
      - ./logs/clickhouse:/var/log/clickhouse-server
  grafana:
    image: grafana/grafana:11.1.0
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - ./grafana:/var/lib/grafana
```

После запуска `docker compose up -d` подключите ClickHouse datasource и импортируйте панель Retention/MoM.
