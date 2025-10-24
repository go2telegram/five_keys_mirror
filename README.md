# five_keys_mirror

Статический сайт на GitHub Pages с автосборкой из `docs/` и публикацией в ветку `gh-pages`.

## Как работает

- **main** — исходники (`docs/`, `tools/`, workflows).
- **gh-pages** — собранный сайт (деплоится автоматически из workflows).

### Сборка и публикация

- `/.github/workflows/publish.yml` — публикует сайт при каждом `push` в `main`.
- `/.github/workflows/codex_dispatch.yml` — ручной/внешний триггер (workflow_dispatch / repository_dispatch).
- `/.github/workflows/nightly_render.yml` — ночная пересборка и репаблиш.
- `/.github/workflows/audit.yml` — CI для PR (actionlint + пробная сборка).

### Как добавить контент

1. Клади новые файлы `.mmd` в `docs/` (напр. `docs/feature-x/diagram.mmd`).
2. Пушь в `main` — Mermaid-диаграммы соберутся в `dist/menu/*.svg`.
3. Публикация 💡 выполняется автоматически — `gh-pages` обновится, сайт будет доступен по URL из настроек Pages.

### Ручной запуск публикации

Через UI:
- **Actions → codex_dispatch → Run workflow**, выбери `cmd=publish`.

Через API (`repository_dispatch`):
```json
{
  "event_type": "codex_command",
  "client_payload": { "cmd": "publish", "key": "cdx_..." }
}
```

Требуется секрет CODEX_ASYNC_KEY (или CODEX_SHARED_KEY) в Settings → Secrets → Actions
