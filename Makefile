.PHONY: migrate upgrade db-check dev fmt lint hooks build-products validate-products

migrate:
	@alembic revision -m "$(msg)" --autogenerate

upgrade:
	@mkdir -p var
	@alembic upgrade head

db-check:
	@python scripts/db_check.py

dev:
	@python -m app.main

fmt:
	@python -m black .
	@ruff check . --fix

lint:
	@ruff check .


hooks:
	@python -m pip install --upgrade pip
	@python -m pip install pre-commit
	@pre-commit install
	@pre-commit run --all-files

build-products:
        @python -m tools.build_products build

validate-products:
        @python -m tools.build_products validate
