#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip pip-tools
pip-compile --upgrade --generate-hashes -o requirements.txt requirements.in
pip-compile --upgrade --generate-hashes -o requirements-dev.txt requirements-dev.in
