# MIGRATIONS

- Именование: `YYYYMMDDHHMM_<slug>.py` или `000X_<slug>.py` для ключевых релизов.
- Каждая миграция должна быть идемпотентной и учитывать оба драйвера (SQLite и Postgres).
- После генерации (`alembic revision --autogenerate`) вручную проверить типы и дефолты.
- В `upgrade()` и `downgrade()` избегать прямых SQL, используйте Alembic API.
- Перед PR: `alembic upgrade head` и `alembic downgrade -1` на SQLite.
