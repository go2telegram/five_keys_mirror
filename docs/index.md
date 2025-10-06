# Five Keys Bot

Five Keys Bot is a production-grade Telegram assistant that helps wellness coaches onboard clients, deliver subscription content, and monitor engagement. The project emphasises reliability, observability, and security from the outset.

## Key capabilities

- **Rich workflow orchestration** via modular Aiogram handlers (referral, profile, subscription, admin areas).
- **Durable storage** powered by PostgreSQL with Alembic migrations and async SQLAlchemy sessions.
- **Operational visibility** through Prometheus metrics, Grafana dashboards, and watchdog health probes.
- **Self-healing runtime** that retries database connections, monitors `/ping`, and restarts polling loops automatically.
- **Security hardening** with secret redaction, environment-based configuration, and CI scanners.

## Architecture highlights

```text
Telegram ↔ Aiogram dispatcher ↔ Handlers (plugins)
                                   │
                                   ├─ PostgreSQL (async SQLAlchemy)
                                   ├─ Redis cache/events
                                   ├─ Tribute webhook (subscriptions)
                                   ├─ Prometheus metrics (/metrics)
                                   └─ Admin notifications + APScheduler jobs
```

Explore the navigation to learn how to run the bot locally, contribute new features, and understand the core modules.
