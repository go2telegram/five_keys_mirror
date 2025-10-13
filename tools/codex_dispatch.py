"""Utility for triggering codex_dispatch.yml via repository_dispatch."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_REPO = "go2telegram/five_keys_bot"


def build_payload(cmd: str, msg: str, key: str, patch_path: str | None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_type": "codex_command",
        "client_payload": {
            "cmd": cmd,
            "msg": msg,
            "key": key,
        },
    }

    if patch_path:
        if cmd != "open_patch_pr":
            raise ValueError("--patch можно использовать только с командой open_patch_pr")
        payload["client_payload"]["patch_b64"] = encode_patch(patch_path)

    return payload


def encode_patch(path: str) -> str:
    with open(path, "rb") as patch_file:
        raw = patch_file.read()
    return base64.b64encode(raw).decode("ascii")


def dispatch(repo: str, token: str, payload: Dict[str, Any]) -> int:
    url = f"https://api.github.com/repos/{repo}/dispatches"
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method="POST")
    request.add_header("Authorization", f"token {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Content-Type", "application/json")

    with urlopen(request) as response:  # nosec B310
        status = response.getcode()
        body = response.read().decode("utf-8", errors="ignore")

    if body:
        print(body)

    return status


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "cmd",
        choices=("render_menu", "build_catalog", "open_patch_pr", "lint_autofix"),
        help="Команда для выполнения в codex_dispatch.yml",
    )
    parser.add_argument("--msg", required=True, help="Короткое описание действия")
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"Целевой репозиторий (по умолчанию {DEFAULT_REPO})",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("GITHUB_TOKEN"),
        help="PAT с правами repo и workflow (можно задать через GITHUB_TOKEN)",
    )
    parser.add_argument(
        "--key",
        default=os.getenv("CODEX_SHARED_KEY"),
        help="Значение CODEX_SHARED_KEY (можно задать через переменную окружения)",
    )
    parser.add_argument(
        "--patch",
        help="Путь к unified diff для open_patch_pr",
    )

    args = parser.parse_args(argv)

    if not args.token:
        parser.error("Необходимо указать --token или переменную окружения GITHUB_TOKEN")
    if not args.key:
        parser.error("Необходимо указать --key или переменную окружения CODEX_SHARED_KEY")
    if args.cmd == "open_patch_pr" and not args.patch:
        parser.error("Для open_patch_pr нужно передать --patch с путём к diff")
    if args.patch and not os.path.isfile(args.patch):
        parser.error(f"Файл патча не найден: {args.patch}")

    return args


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    args = parse_args(argv)

    try:
        payload = build_payload(args.cmd, args.msg, args.key, args.patch)
        status = dispatch(args.repo, args.token, payload)
        print(f"Dispatch sent successfully (HTTP {status})")
        return 0
    except (HTTPError, URLError) as error:
        print(f"Failed to send dispatch: {error}", file=sys.stderr)
        if isinstance(error, HTTPError):
            try:
                body = error.read().decode("utf-8", errors="ignore")
            except Exception:  # pragma: no cover - best effort logging
                body = ""
            if body:
                print(body, file=sys.stderr)
        return 1
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

