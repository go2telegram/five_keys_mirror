New-Item -ItemType Directory -Force -Path var | Out-Null
alembic upgrade head
python -m app.main
