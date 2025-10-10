#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

SHOW_HELP=false
DRY_RUN=false
LINKS=false
BASE_REGISTER=""
PROD=false
BOT_TOKEN=""
HEALTH_PORT=""

usage() {
  cat <<'USAGE'
Usage: tools/dev_up.sh [options]

Options:
  --dry                 Print actions without executing them
  --prod                Enable production mode (reserved)
  --links               Generate default links CSV
  --base-register URL   Override BASE_REGISTER_URL for links generation
  --bot-token TOKEN     Bot token (reserved)
  --health-port PORT    Healthcheck port (reserved)
  -h, --help            Show this help message
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry)
      DRY_RUN=true
      shift
      ;;
    --prod)
      PROD=true
      shift
      ;;
    --links)
      LINKS=true
      shift
      ;;
    --base-register)
      [[ $# -ge 2 ]] || { echo "--base-register requires a value" >&2; exit 1; }
      BASE_REGISTER="$2"
      shift 2
      ;;
    --base-register=*)
      BASE_REGISTER="${1#*=}"
      shift
      ;;
    --bot-token)
      [[ $# -ge 2 ]] || { echo "--bot-token requires a value" >&2; exit 1; }
      BOT_TOKEN="$2"
      shift 2
      ;;
    --bot-token=*)
      BOT_TOKEN="${1#*=}"
      shift
      ;;
    --health-port)
      [[ $# -ge 2 ]] || { echo "--health-port requires a value" >&2; exit 1; }
      HEALTH_PORT="$2"
      shift 2
      ;;
    --health-port=*)
      HEALTH_PORT="${1#*=}"
      shift
      ;;
    -h|--help)
      SHOW_HELP=true
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "$SHOW_HELP" == true ]]; then
  usage
  exit 0
fi

run_cmd() {
  if [[ "$DRY_RUN" == true ]]; then
    echo "+ $*"
  else
    "$@"
  fi
}

if [[ "$LINKS" == true ]]; then
  cmd=(python -m tools.build_links_csv)
  if [[ -n "$BASE_REGISTER" ]]; then
    cmd+=(--base-register "$BASE_REGISTER")
  fi
  run_cmd "${cmd[@]}"
fi

if [[ "$LINKS" != true ]]; then
  if [[ "$DRY_RUN" == true ]]; then
    echo "No actions scheduled (dry run)."
  fi
fi
