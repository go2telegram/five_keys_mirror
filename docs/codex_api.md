# Codex API (repository_dispatch)

## Эндпоинт

```
POST https://api.github.com/repos/go2telegram/five_keys_bot/dispatches
```

## Заголовки

```
Authorization: token <PAT_WITH_repo+workflow>
Accept: application/vnd.github+json
```

## Payload

```json
{
  "event_type": "codex_command",
  "client_payload": {
    "cmd": "<command>",
    "msg": "описание",
    "key": "<CODEX_SHARED_KEY>",
    "patch_b64": "<base64 unified diff, только для open_patch_pr>",
    "fix": true
  }
}
```

## Команды

- `render_menu` — рендер `*.mmd` → SVG (с автофиксом при фейле).
- `build_catalog` — сборка/валидация каталога.
- `open_patch_pr` — применить unified-diff, открыть PR.
- `lint_autofix` — `isort`→`black`, PR при изменениях.
- `auto_label` — навесить automerge на безопасный PR (по `pr:<num>` или SHA).
- `doctor` — health-пинг; при `fix:true` — лейблы и scaffold-workflow через PR.

## Пример вызова (GH CLI)

```bash
gh api repos/go2telegram/five_keys_bot/dispatches \
  --raw-field event_type=codex_command \
  --raw-field client_payload='{"cmd":"doctor","fix":true,"msg":"nightly doctor --fix","key":"<SHARED_KEY>"}'
```

## Проверка последних прогонов `nightly_doctor`

```bash
gh run list --workflow nightly_doctor --limit 5
```

## Guard-rails

PR не автомёрджится, если изменены:

- `.github/workflows/**`
- `Dockerfile`
- `requirements*.txt`
- `run.py`
- `app/main.py`
- `scripts/**`

Тогда automerge снимается, PR ждёт ручного ревью.

## Напоминание по секретам

```
# общий ключ для Codex
gh secret set CODEX_SHARED_KEY -b"YOUR_RANDOM_SHARED_KEY"

# опционально для уведомлений
gh secret set TELEGRAM_BOT_TOKEN -b"123456:ABCDEF..."
gh secret set TELEGRAM_CHAT_ID   -b"-1001234567890"
# или Slack:
gh secret set SLACK_WEBHOOK_URL  -b"https://hooks.slack.com/services/..."
```
