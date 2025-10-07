# v1.0.0 — Production Release

**CI**
- Сборка и валидация каталога (schema-backed), pytest, audit tooling.
- Warning-проверка доступности изображений.

**Bot**
- `/ping`, `/metrics`, `/version`, `/catalog`, `/product`, `/find`.
- Админ: `/catalog_reload`, `/catalog_stats`, `/catalog_broken` + cron-check.
- Throttling + ACL; optional Redis backend (`USE_REDIS=1`).

**DX/Ops**
- Docker HEALTHCHECK на `/ping`.
- README: как собрать/валидировать каталог и запустить.
