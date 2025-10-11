SHELL := /bin/bash

PY ?= python
PORT ?= 8080
TOKEN ?=

export PYTHONPATH := $(PYTHONPATH):.

.PHONY: help pull install build validate links dry prod selfcheck precommit

help:
	@echo "make pull        - git pull --ff-only"
	@echo "make install     - install deps (runtime + dev without gitleaks)"
	@echo "make build       - python -m tools.build_products build"
	@echo "make validate    - python -m tools.build_products validate"
	@echo "make links       - generate links CSV (BASE=<url>)"
	@echo "make dry         - run service only (DEV_DRY_RUN=1, port=$(PORT))"
	@echo "make prod        - run bot with TOKEN=... (port=$(PORT))"
	@echo "make selfcheck   - local smoke (build/validate/pytest-smoke/ruff/bandit)"
	@echo "make precommit   - install pre-commit and enable dev-check hook"

pull:
	git stash push -u -m "WIP dev" >/dev/null 2>&1 || true
	git pull --ff-only
	git stash pop >/dev/null 2>&1 || true

install:
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt
	$(PY) -m pip install pytest pytest-asyncio pytest-cov bandit mypy ruff pip-audit safety

build:
	$(PY) -m tools.build_products build

validate:
	$(PY) -m tools.build_products validate

links:
	BASE=$${BASE:-"https://vilavi.com/reg/XXXXXX"}; \
	$(PY) - <<PY
import json, csv, os
from pathlib import Path
data=json.load(open("app/catalog/products.json",encoding="utf-8"))
prods=data["products"] if isinstance(data,dict) else data
out=Path("app/links/sets/links_set_default.csv"); out.parent.mkdir(parents=True,exist_ok=True)
with out.open("w",newline="",encoding="utf-8") as f:
    w=csv.writer(f); w.writerow(["type","id","url"]); w.writerow(["register","",os.getenv("BASE")])
    [w.writerow(["product",p["id"],p.get("order","")]) for p in prods]
print("CSV:",out)
PY

dry:
	DEV_DRY_RUN=1 HEALTH_PORT=$(PORT) $(PY) run.py

prod:
	@if [ -z "$(TOKEN)" ]; then echo "TOKEN is empty. Use: make prod TOKEN=123:AA..." && exit 1; fi
	DEV_DRY_RUN=0 BOT_TOKEN=$(TOKEN) HEALTH_PORT=$(PORT) QUIZ_IMAGE_MODE=remote $(PY) run.py

selfcheck:
	$(PY) -m tools.dev_check --fast --json || true
	@echo "Report: build/reports/dev_check.md"

precommit:
	$(PY) tools/hooks/install_hooks.py
