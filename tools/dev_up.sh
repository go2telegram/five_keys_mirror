#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

usage() {
  cat <<'USAGE'
Usage: tools/dev_up.sh [options]

Options:
  --dry                 Start the bot in dry-run mode (default)
  --prod                Start the bot in production mode (requires --bot-token)
  --bot-token TOKEN     Override the BOT_TOKEN for the run
  --health-port PORT    Override the HEALTH_PORT for the run (default: 8080)
  --no-install          Skip dependency installation
  --no-build            Skip catalog build/validation
  --links               Generate partner links CSV report
  --base-register URL   Override BASE_REGISTER_URL for the run
  --no-head-check       Skip media HEAD check step
  --skip-pull           Skip git stash/pull step
  --help                Show this help message
USAGE
}

DRY_MODE=0
PROD_MODE=0
BOT_TOKEN_OVERRIDE=""
HEALTH_PORT_OVERRIDE=""
NO_INSTALL=0
NO_BUILD=0
GENERATE_LINKS=0
BASE_REGISTER_OVERRIDE=""
SKIP_PULL=0
RUN_HEAD_CHECK=1

while (($# > 0)); do
  case "$1" in
    --dry)
      DRY_MODE=1
      shift
      ;;
    --prod)
      PROD_MODE=1
      shift
      ;;
    --bot-token)
      BOT_TOKEN_OVERRIDE="$2"
      shift 2
      ;;
    --bot-token=*)
      BOT_TOKEN_OVERRIDE="${1#*=}"
      shift
      ;;
    --health-port)
      HEALTH_PORT_OVERRIDE="$2"
      shift 2
      ;;
    --health-port=*)
      HEALTH_PORT_OVERRIDE="${1#*=}"
      shift
      ;;
    --no-install)
      NO_INSTALL=1
      shift
      ;;
    --no-build)
      NO_BUILD=1
      shift
      ;;
    --links)
      GENERATE_LINKS=1
      shift
      ;;
    --no-head-check)
      RUN_HEAD_CHECK=0
      shift
      ;;
    --base-register)
      BASE_REGISTER_OVERRIDE="$2"
      shift 2
      ;;
    --base-register=*)
      BASE_REGISTER_OVERRIDE="${1#*=}"
      shift
      ;;
    --skip-pull)
      SKIP_PULL=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

log() {
  printf '[dev-up] %s\n' "$*"
}

ensure_pull() {
  if [[ $SKIP_PULL -eq 1 ]]; then
    log "Skipping git pull (--skip-pull)"
    return
  fi

  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log "Not a git repository; skipping pull"
    return
  fi

  local worktree_status
  worktree_status="$(git status --porcelain)"
  local stashed=0
  if [[ -n "$worktree_status" ]]; then
    log "Saving local changes with git stash"
    git stash push --include-untracked --message "dev_up auto-stash $(date +%Y-%m-%dT%H:%M:%S)" >/dev/null
    stashed=1
  else
    log "Working tree clean"
  fi

  log "Pulling latest changes"
  git pull --ff-only --stat

  if [[ $stashed -eq 1 ]]; then
    log "Restoring stashed changes"
    git stash pop || log "WARN Failed to apply stashed changes automatically"
  fi
}

install_deps() {
  if [[ $NO_INSTALL -eq 1 ]]; then
    log "Skipping dependency installation (--no-install)"
    return
  fi

  log "Installing dependencies"
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt

  local tmpfile
  tmpfile="$(mktemp)"
  trap 'rm -f "$tmpfile"' EXIT
  grep -v '^gitleaks\b' requirements-dev.txt >"$tmpfile"
  python -m pip install -r "$tmpfile"
  rm -f "$tmpfile"
  trap - EXIT
}

build_catalog() {
  if [[ $NO_BUILD -eq 1 ]]; then
    log "Skipping catalog build (--no-build)"
    return
  fi

  log "Building product catalog"
  python -m tools.build_products build
  log "Validating product catalog"
  python -m tools.build_products validate
}

generate_links_csv() {
  if [[ $GENERATE_LINKS -eq 0 ]]; then
    return
  fi

  log "Generating partner links CSV"
  python - <<'PY'
from __future__ import annotations

import csv
from pathlib import Path

from tools.check_partner_links import collect_active_links, collect_register_links

build_dir = Path("build") / "reports"
build_dir.mkdir(parents=True, exist_ok=True)
output = build_dir / "dev_links.csv"

rows: list[tuple[str, str, str]] = []
seen: set[str] = set()

for link in collect_register_links():
    if link.url in seen:
        continue
    rows.append(("register", link.title or "", link.url))
    seen.add(link.url)

for link in collect_active_links():
    if link.url in seen:
        continue
    rows.append(("buy", link.title or "", link.url))
    seen.add(link.url)

with output.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["source", "title", "url"])
    writer.writerows(rows)

print(f"Links CSV written to {output}")
PY
}

run_head_check() {
  if [[ $RUN_HEAD_CHECK -eq 0 ]]; then
    log "Skipping media head check (--no-head-check)"
    return
  fi
  if [[ ${NO_NET:-0} == 1 ]]; then
    log "Skipping media head check (NO_NET=1)"
    return
  fi
  log "Running media head check"
  if ! python -m tools.head_check --quiet; then
    log "WARN head_check reported issues; inspect build/reports/media_head_report.txt"
  fi
}

main() {
  ensure_pull
  install_deps
  build_catalog
  generate_links_csv
  run_head_check

  local bot_token
  bot_token="${BOT_TOKEN_OVERRIDE:-${BOT_TOKEN:-}}"
  local mode="dry"
  local dev_dry_run=1

  if [[ $PROD_MODE -eq 1 ]]; then
    mode="prod"
    dev_dry_run=0
    if [[ -z "$bot_token" ]]; then
      echo "--prod requires --bot-token or BOT_TOKEN environment variable" >&2
      exit 1
    fi
  elif [[ $DRY_MODE -eq 1 ]]; then
    mode="dry"
    dev_dry_run=1
  else
    mode="dry"
    dev_dry_run=1
  fi

  if [[ $dev_dry_run -eq 1 ]]; then
    bot_token=""
  fi

  export DEV_DRY_RUN="$dev_dry_run"
  export BOT_TOKEN="$bot_token"

  if [[ -n "$HEALTH_PORT_OVERRIDE" ]]; then
    export HEALTH_PORT="$HEALTH_PORT_OVERRIDE"
  elif [[ -z "${HEALTH_PORT:-}" ]]; then
    export HEALTH_PORT=8080
  fi

  if [[ -n "$BASE_REGISTER_OVERRIDE" ]]; then
    export BASE_REGISTER_URL="$BASE_REGISTER_OVERRIDE"
  fi

  log "Starting bot (mode: $mode, health port: ${HEALTH_PORT})"
  exec python -m app.main
}

main "$@"
