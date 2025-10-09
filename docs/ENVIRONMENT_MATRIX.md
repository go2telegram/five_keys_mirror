# Environment matrix

The table below summarises the key runtime settings for each supported environment.

| Environment | `ENVIRONMENT` value | Telegram token requirement | Database URL | Notes |
|-------------|--------------------|----------------------------|--------------|-------|
| Local dry run | `dev` (default) + `DEV_DRY_RUN=1` | Optional (`BOT_TOKEN` may be empty or `dummy`) | `sqlite+aiosqlite:///./var/bot.db` | Starts HTTP services only; useful for health checks without Telegram. |
| Local integration | `dev` | Required (`BOT_TOKEN` must be valid) | Custom (SQLite or Postgres) | Full bot with polling, background workers, and dashboard. |
| Staging | `stage` | Required | Points to staging database | Enable monitoring integrations and staging webhook URLs. |
| Production | `prod` | Mandatory (`BOT_TOKEN` cannot be empty) | Managed Postgres cluster | Startup fails fast if the token is missing; monitoring and Sentry should be configured. |

Additional guidance:

- Any environment may override `HEALTH_PORT`. When set to `0`, the service binds to an ephemeral port and logs the resolved value.
- The `/doctor` endpoint is available everywhere and supports `?repair=1` to remove `_alembic_tmp_*` tables prior to migrations.
- Dashboard access requires `DASHBOARD_ENABLED=1` and a non-empty `DASHBOARD_TOKEN`.
