# GitHub Actions Codex Dispatch Guide

Этот документ описывает, как запускать GitHub Actions-шлюз `codex_dispatch.yml`
в репозитории `go2telegram/five_keys_bot` через событие
[`repository_dispatch`](https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28#create-a-repository-dispatch-event).

## 1. Токен доступа и секретный ключ

- Нужен персональный токен (PAT) **с правами `repo` и `workflow`**. Для
  тонко настроенного токена достаточно доступа только к репозиторию
  `go2telegram/five_keys_bot`.
- В репозитории определён секрет `CODEX_SHARED_KEY`. Его необходимо передавать в
  payload (поле `key`). Без корректного ключа workflow будет проигнорирован.

## 2. Формат запроса

```
POST https://api.github.com/repos/go2telegram/five_keys_bot/dispatches

Headers:
  Authorization: token <PAT_WITH_repo+workflow>
  Accept: application/vnd.github+json
  Content-Type: application/json

Body:
{
  "event_type": "codex_command",
  "client_payload": {
    "cmd": "render_menu" | "build_catalog" | "open_patch_pr" | "lint_autofix",
    "msg": "Короткий осмысленный заголовок/описание",
    "key": "<значение CODEX_SHARED_KEY>",
    "patch_b64": "<base64 unified diff (только для open_patch_pr)>"
  }
}
```

### Допустимые команды

- `render_menu` — рендер всех `*.mmd` в `artifacts/menu/*.svg`. При ошибке
  запускается автофиксер и рендер повторяется. Создаётся PR с лейблами `codex`
  и `automerge`, если есть изменения.
- `build_catalog` — сборка и валидация каталога (`app/catalog/products.json`).
  PR появляется только при наличии изменений.
- `open_patch_pr` — применяет переданный unified diff (`git apply --index`) и
  открывает PR.
- `lint_autofix` — запускает автоформат Python (isort+black) и открывает PR с
  изменениями форматирования.

## 3. Скрипт-обёртка `tools/codex_dispatch.py`

Чтобы не собирать запрос вручную, можно воспользоваться скриптом из этого
репозитория:

```
python -m tools.codex_dispatch \
  render_menu \
  --msg "refresh diagrams" \
  --token "$GITHUB_TOKEN" \
  --key "$CODEX_SHARED_KEY"
```

Параметры:

- позиционный аргумент `cmd` — одна из команд (`render_menu`, `build_catalog`,
  `open_patch_pr`, `lint_autofix`);
- `--msg` — обязательное описание команды;
- `--repo` — целевой репозиторий (`go2telegram/five_keys_bot` по умолчанию);
- `--token` — PAT (можно опустить, если задан env `GITHUB_TOKEN`);
- `--key` — значение `CODEX_SHARED_KEY` (можно опустить, если задан env
  `CODEX_SHARED_KEY`);
- `--patch` — путь к файлу с unified diff (только для `open_patch_pr`).

При успешном выполнении скрипт выводит HTTP-статус ответа GitHub. В случае
ошибок печатается диагностическое сообщение с телом ответа.

## 4. Отслеживание результатов

- Ждите завершения workflow `codex_dispatch` в Actions. В случае ошибки
  сообщите шаг и текст ошибки, при необходимости повторите запуск.
- Если workflow создал PR, дождитесь статуса merge:
  - безопасные изменения (не затрагивающие «рискованные» пути) автомёрджатся;
  - PR, помеченные как `risky`, требуют ручного ревью (лейбл `automerge`
    снимается автоматически).

## 5. Примеры вызовов через CLI

### GitHub CLI

```
gh api repos/go2telegram/five_keys_bot/dispatches \
  --raw-field event_type=codex_command \
  --raw-field client_payload='{"cmd":"render_menu","msg":"refresh diagrams","key":"<SHARED_KEY>"}'

PATCH_B64=$(base64 -w0 /path/to/patch.diff)
gh api repos/go2telegram/five_keys_bot/dispatches \
  --raw-field event_type=codex_command \
  --raw-field client_payload='{"cmd":"open_patch_pr","msg":"apply doc patch","patch_b64":"'"$PATCH_B64"'","key":"<SHARED_KEY>"}'

gh api repos/go2telegram/five_keys_bot/dispatches \
  --raw-field event_type=codex_command \
  --raw-field client_payload='{"cmd":"lint_autofix","msg":"autofix formatting","key":"<SHARED_KEY>"}'
```

### curl

```
curl -X POST \
  -H "Authorization: token <PAT_WITH_repo+workflow>" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/go2telegram/five_keys_bot/dispatches \
  -d '{"event_type":"codex_command","client_payload":{"cmd":"build_catalog","msg":"rebuild products.json","key":"<SHARED_KEY>"}}'
```

> ⚠️ Передавать `patch_b64` необходимо **только** для команды `open_patch_pr`.

