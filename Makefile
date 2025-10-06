.PHONY: run doctor migrate ci

run:      ## Запуск бота (dev)
	BOT_TOKEN=$${BOT_TOKEN} LOG_PATH=./logs/telemetry.log python run.py

doctor:   ## Сухая диагностика
	python tools/doctor.py

migrate:  ## Применить миграции
	alembic upgrade head

ci:       ## Локальный прогон проверок
	ruff . && mypy . && pytest -q || true
