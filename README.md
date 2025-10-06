five_keys_bot
=================

## Telemetry & Monitoring

The bot exposes runtime metrics in Prometheus format at `GET /metrics`. The
endpoint is served by the embedded aiohttp application (same host/port as the
Tribute webhook server) and includes the following key series:

- `bot_update_latency_seconds` — histogram with per-update processing latency.
- `bot_updates_total` — counter for the total number of updates (use `rate()` in
  Grafana to get updates per second).
- `bot_update_errors_total` — counter of failed update processing attempts.
- `bot_active_users` — gauge with the number of active users within the last
  five minutes.
- `bot_uptime_seconds` — gauge with the bot uptime, used by Grafana to visualise
  service availability.

### Telegraf

Add the following input to your Telegraf agent to scrape the metrics:

```
[[inputs.prometheus]]
  urls = ["http://localhost:8080/metrics"]
  metric_version = 2
```

Update the URL if your bot runs on a different host/port.

### Grafana

With the Telegraf Prometheus input enabled, the metrics become available in
InfluxDB/Prometheus data sources. Recommended Grafana queries:

- **Uptime**: `bot_uptime_seconds` (displayed as a single stat or time series).
- **Latency (p95)**: `histogram_quantile(0.95, sum by (le) (rate(bot_update_latency_seconds_bucket[5m])))`.
- **Updates per second**: `rate(bot_updates_total[1m])`.
- **Errors per second**: `rate(bot_update_errors_total[5m])`.
- **Active users**: `bot_active_users`.

This setup ensures production-grade observability with Prometheus scraping,
Telegraf forwarding, and Grafana dashboards.

## Data persistence (PostgreSQL)

User profiles, leads, subscriptions and the static product catalog are
persisted in PostgreSQL via SQLAlchemy's async ORM. The application expects a
`DATABASE_URL` environment variable (e.g.
`postgresql://bot:password@localhost:5432/five_keys`) and falls back to a local
SQLite file (`bot.db`) for development environments.

Schema changes are tracked with Alembic. To create/update the database run:

```
alembic upgrade head
```

During startup the bot will also call `sync_products()` to ensure the built-in
product catalog is synchronised with the database.
