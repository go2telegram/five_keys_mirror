# Five Keys Bot

Production-ready Telegram assistant for wellness coaching with PostgreSQL persistence, Prometheus telemetry, and Docker-first deployment tooling.

> **Current release:** [v1.0.0](CHANGELOG.md)

- **Framework**: [Aiogram 3](https://docs.aiogram.dev/).
- **Storage**: PostgreSQL for long-lived data, Redis for ephemeral cache/event fan-out.
- **Observability**: `/metrics` Prometheus endpoint, `/ping` watchdog, masked `/panel/logs`.
- **Automation**: APScheduler jobs, admin notifications, and a stress-test harness for performance baselines.

---

## Repository layout

| Path | Purpose |
| ---- | ------- |
| `app/` | Bot application code, organised by feature packages (admin, profile, referral, subscription) plus infrastructure modules. |
| `alembic/` | Database migrations maintained with Alembic. |
| `tools/stress_test.py` | Load generator that replays `/start` and `/panel` updates while capturing latency/CPU/RSS metrics. |
| `doctor.py` | Operational diagnostics hitting `/ping` and `/metrics`. |
| `docker-compose.yml` | One-command stack (bot + Postgres + Redis + Prometheus + Grafana). |
| `docs/` | MkDocs documentation sources (API reference, onboarding guides). |

---

## Quickstart (15 min)

### 1. Clone & prepare environment

```bash
git clone https://github.com/<your-org>/five_keys_bot.git
cd five_keys_bot
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install --upgrade pip
pip install -r requirements-dev.txt
```

### 2. Configure secrets

Create a `.env` file at the project root (or export variables in your shell):

```env
BOT_TOKEN=123456:REPLACE_ME
ADMIN_ID=123456789
CALLBACK_SECRET=super-secret
DATABASE_URL=postgresql://bot:password@localhost:5432/five_keys
REDIS_URL=redis://localhost:6379/0
TZ=Europe/Moscow
```

> ℹ️  A local PostgreSQL/Redis stack is available via Docker Compose (see below) if you do not have services installed locally.

### 3. Apply database migrations

```bash
alembic upgrade head
```

### 4. Launch the bot

```bash
python run.py
```

The aiohttp webhook server listens on `http://0.0.0.0:8080`. Visit:

- `GET /ping` — readiness/health check.
- `GET /metrics` — Prometheus metrics.
- `GET /panel/logs?secret=<CALLBACK_SECRET>` — masked logs for operators.

Stop the bot with <kbd>Ctrl</kbd> + <kbd>C</kbd>.

---

## Docker-based stack

Run the complete production-like stack (bot, PostgreSQL, Redis, Grafana):

```bash
cp .env.example .env  # or craft your own secrets as above
# Ensure the BOT_TOKEN and ADMIN_ID are set in .env before continuing
docker compose up --build
```

Key services:

- **Bot**: http://localhost:8080
- **Prometheus**: http://localhost:9090 (scrapes `bot:8080/metrics`)
- **Grafana**: http://localhost:3000 (default credentials configurable via `.env`)
- **PostgreSQL**: exposed as `postgres:5432` inside the Compose network
- **Redis**: `redis:6379`

Apply database migrations inside the running container if needed:

```bash
docker compose exec bot alembic upgrade head
```

Data for PostgreSQL and Redis is stored in named volumes, so restarts keep state.

> 🛎️  Configure Telegram alerts by setting `GRAFANA_TELEGRAM_BOT_TOKEN` and `GRAFANA_TELEGRAM_CHAT_ID` in `.env` before launching the stack. Grafana provisioning ships with a "Five Keys Bot Overview" dashboard and alerting rules for latency, error spikes, and missing metrics.

---

## Environment variables

| Variable | Description | Default |
| -------- | ----------- | ------- |
| `BOT_TOKEN` | Telegram bot token issued by BotFather. | — |
| `ADMIN_ID` | Telegram user ID receiving admin alerts. | — |
| `CALLBACK_SECRET` | Shared secret for `/panel/logs` access. | `None` (panel disabled) |
| `DATABASE_URL` | SQLAlchemy URL for PostgreSQL/SQLite. | `sqlite+aiosqlite:///./bot.db` |
| `REDIS_URL` | Redis connection string for caching. | `None` |
| `TZ` | IANA timezone for scheduled jobs. | `Europe/Moscow` |
| `TRIBUTE_API_KEY` | API key for Tribute subscription webhooks. | `""` |
| `TRIBUTE_WEBHOOK_PATH` | aiohttp route for Tribute callbacks. | `/tribute/webhook` |
| `SUB_BASIC_MATCH` / `SUB_PRO_MATCH` | Plan identifiers used to map Tribute subscriptions. | `basic` / `pro` |
| `ADMIN_REPORT_HOUR`/`ADMIN_REPORT_MINUTE` | Daily digest scheduling. | `9` / `30` |
| `OPENAI_API_KEY` | Optional key for assistant features. | `None` |

Refer to [`app/config.py`](app/config.py) for the exhaustive list and defaults.

---

## Operational tooling

- **Metrics**: Prometheus endpoint at `/metrics` exports latency histograms, update counters, error counters, active user gauges, and uptime gauges. Integrate with Telegraf using:

  ```toml
  [[inputs.prometheus]]
    urls = ["http://localhost:8080/metrics"]
    metric_version = 2
  ```

- **Watchdog**: `doctor.py` polls `/ping` and `/metrics`, reporting recovery status during incidents.
- **Nightly reports**: `python doctor.py --report` stores a JSON health snapshot under `reports/doctor/`. The scheduled GitHub Action `doctor-report.yml` runs nightly (configure `PING_URL` and `METRICS_URL` secrets) and uploads the artifact.
- **Stress testing**: `python tools/stress_test.py --updates 200 --concurrency 20` to replay synthetic traffic and ensure average latency stays under 200 ms.

---

## Running quality checks

| Check | Command |
| ----- | ------- |
| Lint | `ruff check` |
| Type hints | `mypy --config-file pyproject.toml` |
| Security scan | `bandit -r app --confidence-level MEDIUM` |
| Bytecode compilation | `python -m compileall app doctor.py` |
| Load test | `python tools/stress_test.py --updates 100 --concurrency 10 --max-duration 10` |

Run these before opening a pull request. The CI workflow enforces the same gates.

---

## Documentation

MkDocs is configured for onboarding and API reference material:

```bash
mkdocs serve  # starts docs at http://127.0.0.1:8000
```

The documentation lives under `docs/` and includes auto-generated API references via `mkdocstrings`.

---

## Releases & deployments

- Release notes live in [CHANGELOG.md](CHANGELOG.md). Tag the repository with `v1.0.0` (or the next semantic version) after updating the changelog.
- Continuous Deployment is automated through `.github/workflows/deploy.yml`, which triggers only after a successful `CI` workflow on `main`. Configure production credentials via repository secrets (`DEPLOY_ENABLED=true`, `PROD_DEPLOY_HOST`, `PROD_DEPLOY_USER`, etc.) to activate the deployment step.
- A nightly doctor report is produced by `.github/workflows/doctor-report.yml`; configure `PROD_PING_URL` / `PROD_METRICS_URL` secrets so the job targets your environment and retains JSON artifacts.

---

## Need help?

- `doctor.py` — diagnose health issues.
- `app/notifications.py` — understand admin alert flows.
- `tools/stress_test.py` — profile performance regressions.

For questions about contributing or release workflow see [CONTRIBUTING.md](CONTRIBUTING.md).
