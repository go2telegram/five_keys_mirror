#!/usr/bin/env bash
set -euo pipefail

# инструменты
python -m pip install --upgrade pip >/dev/null
pip install --disable-pip-version-check -q black==24.8.0 isort==5.13.2

# автофикс
isort --profile black .
black .

# строгое подтверждение (если что-то осталось — пусть шаг валится)
isort --profile black --check-only .
black --check .
