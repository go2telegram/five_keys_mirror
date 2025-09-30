.PHONY: dev migrate upgrade downgrade test

DEV_PYTHON ?= python

var:
mkdir -p var

migrate:
alembic revision --autogenerate -m "$(msg)"

upgrade: var
alembic upgrade head

downgrade:
alembic downgrade -1

dev: upgrade
$(DEV_PYTHON) -m app.main

test:
pytest
