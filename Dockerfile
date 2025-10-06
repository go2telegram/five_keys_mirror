# syntax=docker/dockerfile:1
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_NO_CACHE_DIR=off

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential libpq-dev \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y build-essential libpq-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY run.py ./run.py
COPY doctor.py ./doctor.py
COPY README.md ./README.md

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fs http://localhost:8080/ping || exit 1

CMD ["python", "-m", "run"]
