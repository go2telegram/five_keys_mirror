# v1.0.0 — Production Release

**CI**
- Сборка/валидация каталога (schema-backed), pytest, audit tooling.
- Warning-проверка доступности изображений (HEAD-check).

**Bot**
- `/ping`, `/metrics`, `/version`, `/catalog`, `/product`, `/find`.
- Admin: `/catalog_reload`, `/catalog_stats`, `/catalog_broken` + nightly cron.
- Throttling + ACL; optional Redis backend (`USE_REDIS=1`).

**DX/Ops**
- Docker HEALTHCHECK на `/ping`.
- README: build/validate catalog & quickstart.
