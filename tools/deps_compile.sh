#!/usr/bin/env bash
set -euo pipefail
pip install --upgrade pip pip-tools
pip-compile -q --generate-hashes -o requirements.txt requirements.in
pip-compile -q --generate-hashes -o requirements-dev.txt requirements-dev.in
