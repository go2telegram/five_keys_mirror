# Changelog

All notable changes to this project will be documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2024-10-05
### Added
- Production-grade monitoring stack with Prometheus metrics, Grafana dashboards, and Telegram alerting.
- PostgreSQL persistence layer with Alembic migrations covering users, leads, subscriptions, products, and admin events.
- Admin notification services including `/stats`, `/errors`, and scheduled daily digests.
- Stress-test harness and CI gate enforcing latency, CPU, and memory budgets.
- Docker Compose stack for bot, PostgreSQL, Redis, Prometheus, and Grafana with automated provisioning.
- Security hardening for secret handling, masked logs, and repository quality checks (ruff, mypy, bandit).
- MkDocs documentation site, onboarding guides, and contributing workflow.

### Changed
- Modularised handlers and scheduler jobs into plugin-style packages auto-registered at startup.
- Bootstrap flow to initialise telemetry, middleware, watchdogs, and persistence with self-healing retry logic.

### Fixed
- Automatic recovery loop covering transient database/network faults via `/ping` watchdog endpoints.

[1.0.0]: https://github.com/your-org/five_keys_bot/releases/tag/v1.0.0
