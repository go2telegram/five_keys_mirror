#!/usr/bin/env bash
set -euo pipefail

curl -sf "http://127.0.0.1:${HEALTH_PORT:-8080}/ping" >/dev/null
curl -sf "http://127.0.0.1:${HEALTH_PORT:-8080}/metrics" | head -n 3 >/dev/null
echo "SMOKE OK"
