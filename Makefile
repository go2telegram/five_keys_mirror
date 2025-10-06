.PHONY: migrate

migrate:
	@if [ -z "$$DATABASE_URL" ]; then \
		echo "DATABASE_URL is not set" >&2; \
		exit 1; \
	fi
	PYTHONPATH=. alembic upgrade head
