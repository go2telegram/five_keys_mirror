#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[chaos][redis] $1"
}

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Kill Redis process to simulate an outage.

Usage: ./kill_redis.sh [signal]

Arguments:
  signal   Optional POSIX signal to send (default: TERM). Use KILL as a last resort.

The script tries, in order, to stop Redis running as:
  1. A docker compose service named redis/redis-cache (docker compose stop <service>).
  2. A standalone Docker container whose name contains "redis" (docker stop <container>).
  3. A systemd service called redis or redis-server (systemctl stop <service>).
  4. A process called redis-server (pkill -f).

It returns successfully even if Redis was not running.
USAGE
  exit 0
fi

signal="${1:-TERM}"

log "Simulating Redis failure (signal=$signal)"

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

if compose_stop "redis" || compose_stop "redis-cache"; then
  exit 0
fi

if command -v docker >/dev/null 2>&1; then
  container_id=$(docker ps --format '{{.ID}} {{.Names}}' | awk '/redis/ {print $1; exit}')
  if [[ -n "${container_id}" ]]; then
    log "Stopping docker container ${container_id}"
    docker stop "${container_id}" >/dev/null 2>&1 || docker kill "${container_id}" >/dev/null 2>&1 || true
    exit 0
  fi
fi

if command -v systemctl >/dev/null 2>&1; then
  for svc in redis redis-server; do
    if systemctl list-units --full -all | grep -q "${svc}.service"; then
      log "Stopping systemd service ${svc}"
      systemctl stop "${svc}" || true
      exit 0
    fi
  done
fi

if pgrep -f redis-server >/dev/null 2>&1; then
  log "Killing redis-server processes with signal ${signal}"
  pkill -${signal} -f redis-server || true
  exit 0
fi

log "Redis process not found; nothing to kill"
exit 0
