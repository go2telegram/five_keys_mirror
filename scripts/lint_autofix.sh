#!/usr/bin/env bash
set -euo pipefail
python -m pip install --upgrade pip >/dev/null
# ставим то, что есть в проекте; если нет, ставим fallback
python - <<'PY'
import sys, subprocess

def safe_install(pkgs):
    for p in pkgs:
        try:
            __import__(p.split("==")[0].replace("-","_"))
        except Exception:
            subprocess.check_call([sys.executable,"-m","pip","install",p])

# базовый набор
safe_install(["black==24.8.0","isort==5.13.2"])
PY
# автофиксы (тихо), затем проверка
isort . || true
black . || true
# Если проект требует strict-проверку:
isort --check-only . && black --check .
