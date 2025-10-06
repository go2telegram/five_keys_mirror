# Getting started

This guide walks a new developer from cloning the repository to running the bot and accompanying services.

## 1. Prerequisites

- Python 3.11+
- Docker & Docker Compose (optional but recommended)
- PostgreSQL 14+ and Redis 6+ (or run them via Docker Compose)

## 2. Clone the repository

```bash
git clone https://github.com/<your-org>/five_keys_bot.git
cd five_keys_bot
```

## 3. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install --upgrade pip
pip install -r requirements-dev.txt
```

## 4. Configure environment variables

Create a `.env` file using the provided template:

```bash
cp .env.example .env
```

Update the values for `BOT_TOKEN`, `ADMIN_ID`, and other secrets as needed. The application reads variables via [Pydantic Settings](https://docs.pydantic.dev/latest/usage/pydantic_settings/).

## 5. Apply database migrations

Ensure PostgreSQL is running and execute:

```bash
alembic upgrade head
```

This creates the schema for users, leads, subscriptions, products, and admin event logs.

## 6. Run the bot

```bash
python run.py
```

The webhook server starts on `http://0.0.0.0:8080` with:

- `/ping` — health probe (used by the watchdog and Docker healthcheck).
- `/metrics` — Prometheus metrics (scrapeable by Telegraf).
- `/panel/logs?secret=<CALLBACK_SECRET>` — masked operator logs.

Stop the server with `Ctrl+C`.

## 7. (Optional) Bring up the full stack with Docker

```bash
docker compose up --build
```

Services exposed:

- `bot` (Five Keys Bot) — port 8080
- `postgres` — port 5432
- `redis` — port 6379
- `prometheus` — port 9090 (scrapes the bot's `/metrics` endpoint)
- `grafana` — port 3000 (credentials configured through `.env`)

To receive Telegram alerts from Grafana provisioning, set `GRAFANA_TELEGRAM_BOT_TOKEN` and `GRAFANA_TELEGRAM_CHAT_ID` in `.env` before launching `docker compose`.

Run database migrations inside the container as required:

```bash
docker compose exec bot alembic upgrade head
```

## 8. Verify the installation

Run the quality gates to ensure your environment is ready:

```bash
ruff check
mypy --config-file pyproject.toml
bandit -r app --confidence-level MEDIUM
python -m compileall app doctor.py
python tools/stress_test.py --updates 100 --concurrency 10 --max-duration 10
```

If the stress test hits network or dependency issues, confirm PostgreSQL/Redis are available and that optional dependencies from `requirements-dev.txt` are installed.

You are ready to start building features. See [Development workflow](development.md) for day-to-day tips.
