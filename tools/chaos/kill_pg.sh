#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[chaos][postgres] $1"
}

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Stop Postgres to simulate an outage.

Usage: ./kill_pg.sh [signal]

Arguments:
  signal   Optional POSIX signal to send to postgres processes (default: TERM).

The script tries, in order, to stop Postgres when it is run as:
  1. A docker compose service named postgres or db.
  2. A standalone Docker container whose name contains "postgres".
  3. A systemd service named postgresql or postgres.
  4. Local postgres/postmaster processes (pkill -f).

It is idempotent and exits with 0 even if Postgres is not running.
USAGE
  exit 0
fi

signal="${1:-TERM}"

log "Simulating Postgres failure (signal=$signal)"

compose_stop() {
  local service="$1"
  if command -v docker-compose >/dev/null 2>&1; then
    if docker-compose ps --services 2>/dev/null | grep -q "^${service}$"; then
      log "Stopping docker-compose service ${service}"
      docker-compose stop "${service}" || true
      return 0
    fi
  fi
  if command -v docker >/dev/null 2>&1; then
    if docker compose ls --format '{{.Name}}' 2>/dev/null | grep -q '.'; then
      if docker compose ps --services 2>/dev/null | grep -q "^${service}$"; then
        log "Stopping docker compose service ${service}"
        docker compose stop "${service}" || true
        return 0
      fi
    fi
  fi
  return 1
}

if compose_stop "postgres" || compose_stop "db"; then
  exit 0
fi

if command -v docker >/dev/null 2>&1; then
  container_id=$(docker ps --format '{{.ID}} {{.Names}}' | awk '/postgres/ {print $1; exit}')
  if [[ -n "${container_id}" ]]; then
    log "Stopping docker container ${container_id}"
    docker stop "${container_id}" >/dev/null 2>&1 || docker kill "${container_id}" >/dev/null 2>&1 || true
    exit 0
  fi
fi

if command -v systemctl >/dev/null 2>&1; then
  for svc in postgresql postgres; do
    if systemctl list-units --full -all | grep -q "${svc}.service"; then
      log "Stopping systemd service ${svc}"
      systemctl stop "${svc}" || true
      exit 0
    fi
  done
fi

if pgrep -f 'postgres' >/dev/null 2>&1; then
  log "Killing postgres processes with signal ${signal}"
  pkill -${signal} -f postgres || true
  exit 0
fi

log "Postgres process not found; nothing to kill"
exit 0
