FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100

RUN useradd --create-home --shell /bin/bash bot
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# --- healthcheck tools (если образ без curl) ---
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY . .
RUN chmod +x scripts/entrypoint.sh

USER bot

ENV DB_URL=sqlite+aiosqlite:///./var/bot.db

# --- Container health ---
HEALTHCHECK --interval=30s --timeout=3s --retries=5 \
  CMD curl -fs http://localhost:8080/ping || exit 1

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
