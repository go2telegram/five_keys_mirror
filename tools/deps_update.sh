#!/usr/bin/env bash
set -euo pipefail
pip install --upgrade pip pip-tools
pip-compile -q --upgrade --generate-hashes -o requirements.txt requirements.in
pip-compile -q --upgrade --generate-hashes -o requirements-dev.txt requirements-dev.in
mkdir -p build/reports
python -m tools.security_audit --summary > build/reports/deps_update_summary.md || true
