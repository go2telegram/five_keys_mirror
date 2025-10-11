#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="${PYTHONPATH:-.}"
python -m tools.dev_check --fast --json || {
  echo "[pre-commit] ❌ dev_check failed. См. build/reports/dev_check.md"
  exit 1
}
