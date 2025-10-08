# Production deployment guide

This document describes how to deploy the Five Keys bot to a production server in under ten minutes.

## 1. Prepare the server

1. Provision an Ubuntu 22.04 LTS host with at least 2 vCPUs, 4 GB RAM, and 20 GB SSD.
2. Install the base toolchain:
   ```bash
   sudo apt update && sudo apt install -y python3.11 python3.11-venv git nginx docker.io docker-compose
   sudo usermod -aG docker "$USER"
   ```
3. Create a dedicated system user for the bot (optional but recommended):
   ```bash
   sudo adduser --disabled-password --gecos "Five Keys" fivekeys
   sudo usermod -aG sudo fivekeys
   ```
4. Copy your `.env` file with production secrets to `/opt/five-keys/.env` (never commit secrets to git).

## 2. Clone the repository and configure

```bash
sudo mkdir -p /opt/five-keys
sudo chown -R fivekeys:fivekeys /opt/five-keys
sudo -u fivekeys git clone https://github.com/<org>/five_keys_bot.git /opt/five-keys/repo
cd /opt/five-keys/repo
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn uvicorn[standard]
```

Symlink the environment file and configure runtime directories:

```bash
ln -s /opt/five-keys/.env .env
mkdir -p var logs
```

## 3. Database migrations

Run Alembic migrations once after every deployment:

```bash
source .venv/bin/activate
alembic upgrade head
```

Enable automatic migrations on startup by keeping `MIGRATE_ON_START=true` in `.env` for safety.

## 4. Application server (Gunicorn + Uvicorn workers)

Use Gunicorn with async Uvicorn workers to serve the FastAPI dashboard and background webhook server:

```bash
source .venv/bin/activate
export $(cat .env | xargs)
exec gunicorn "app.main:main" \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind 0.0.0.0:8080 \
  --timeout 60 \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log
```

Create a systemd unit `/etc/systemd/system/five-keys.service`:

```ini
[Unit]
Description=Five Keys Telegram bot
After=network.target

[Service]
Type=simple
User=fivekeys
WorkingDirectory=/opt/five-keys/repo
EnvironmentFile=/opt/five-keys/.env
ExecStart=/opt/five-keys/repo/.venv/bin/gunicorn app.main:main \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind 127.0.0.1:8080 \
  --timeout 60 \
  --log-file -
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Reload and enable the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now five-keys.service
```

## 5. Reverse proxy with Nginx

Expose the bot endpoints via HTTPS and handle TLS offloading. Example `/etc/nginx/sites-available/five-keys`:

```nginx
server {
    listen 80;
    server_name bot.example.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 90;
    }
}
```

Enable the site and reload:

```bash
sudo ln -s /etc/nginx/sites-available/five-keys /etc/nginx/sites-enabled/five-keys
sudo nginx -t
sudo systemctl reload nginx
```

Issue TLS certificates with Let’s Encrypt:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d bot.example.com
```

## 6. Logs and monitoring

* Application logs are written to `logs/` (see systemd unit). Rotate with logrotate:
  ```bash
  sudo tee /etc/logrotate.d/five-keys <<'EOF'
  /opt/five-keys/repo/logs/*.log {
      daily
      rotate 14
      compress
      missingok
      copytruncate
  }
  EOF
  ```
* Prometheus scrapes `http://bot.example.com/metrics` for uptime and recommendation counters.
* Configure Sentry DSN in `.env` to capture exceptions in production.

## 7. Backups and disaster recovery

* Database: schedule a cron job to dump the Postgres database daily:
  ```bash
  0 2 * * * pg_dump "$DB_URL" > /opt/backups/five-keys-$(date +\%F).sql
  ```
* Media and configuration: back up `/opt/five-keys/.env`, `/opt/five-keys/repo/logs`, and `/opt/five-keys/repo/var`.
* Store backups in an encrypted S3 bucket with a 30-day retention policy.

## 8. CI/CD pipeline

1. GitHub Actions (`.github/workflows/ci.yml`) runs tests, catalog validators, and secret scans on every push.
2. Protect the `main` branch with required status checks.
3. Tag releases (`vX.Y.Z`) to trigger your deployment job (e.g., GitHub Actions workflow or ArgoCD sync).
4. On deployment, run migrations, restart the systemd service, and verify `/ping` and `/metrics` respond with HTTP 200.

## 9. Troubleshooting checklist

| Issue | Fix |
|-------|-----|
| Bot not responding in Telegram | Check systemd service status, verify BOT_TOKEN, inspect logs. |
| Dashboard 401 | Ensure `DASHBOARD_TOKEN` is set and passed as `Authorization: Bearer <token>`. |
| Google export failing | Confirm `GOOGLE_SERVICE_ACCOUNT_INFO` / credentials and sheet permissions. |
| High latency | Increase Gunicorn workers or migrate to a larger instance. |

You now have a reproducible production setup for the Five Keys bot with monitoring, security, and deployment automation.
