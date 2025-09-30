#!/bin/bash
set -euo pipefail

mkdir -p var
alembic upgrade head
exec python -m app.main
