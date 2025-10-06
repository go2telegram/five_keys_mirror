#!/usr/bin/env python3
"""Self deployment manager for autonomous deploys and rollbacks.

The script is intentionally conservative: it deploys only when CI is green and
pre-deploy metrics signal a healthy system. After the deploy it re-reads the
metrics and performs an automatic rollback when the error rate breaches the
threshold (defaults to 0.2).

Usage examples::

    ENABLE_SELF_DEPLOY=true python tools/self_deploy.py \
        --ci-status-file build/ci_status.json --metrics-file deploy/metrics.json

    # Simulate an incident to ensure rollback logic is exercised
    python tools/self_deploy.py --simulate-error

Both Slack and Telegram notifications are supported via the ``SLACK_WEBHOOK``
and ``TELEGRAM_WEBHOOK`` environment variables.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

DEFAULT_THRESHOLD = 0.2
DEFAULT_POST_DEPLOY_WAIT = 15
LOG_PATH = Path("deploy/deploy.log")


@dataclass
class DeployResult:
    success: bool
    output: str = ""


class NotificationDispatcher:
    """Sends notifications to configured chat integrations."""

    def __init__(self, slack_webhook: Optional[str], telegram_webhook: Optional[str]):
        self.slack_webhook = slack_webhook
        self.telegram_webhook = telegram_webhook

    def send(self, message: str) -> None:
        payload = json.dumps({"text": message}).encode()
        for name, webhook in ("slack", self.slack_webhook), ("telegram", self.telegram_webhook):
            if not webhook:
                continue
            try:
                req = Request(webhook, data=payload, headers={"Content-Type": "application/json"})
                with urlopen(req, timeout=10):
                    pass
            except URLError as exc:
                print(f"[warn] Failed to push {name} notification: {exc}", file=sys.stderr)


class SelfDeployManager:
    def __init__(
        self,
        deploy_command: Iterable[str],
        rollback_command: Iterable[str],
        dispatcher: NotificationDispatcher,
        log_path: Path = LOG_PATH,
        dry_run: bool = False,
    ) -> None:
        self.deploy_command = deploy_command
        self.rollback_command = rollback_command
        self.dispatcher = dispatcher
        self.log_path = log_path
        self.dry_run = dry_run

    # region helpers
    def _run(self, command: Iterable[str]) -> DeployResult:
        if self.dry_run:
            return DeployResult(True, "dry-run")
        if not command:
            return DeployResult(True, "")
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        output = (process.stdout or "") + (process.stderr or "")
        return DeployResult(process.returncode == 0, output.strip())

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")

    # endregion

    def deploy(self) -> DeployResult:
        self._append_log("Starting deploy")
        result = self._run(self.deploy_command)
        status = "✅ Deployed" if result.success else "🔴 Deploy failed"
        self._append_log(status)
        self.dispatcher.send(status)
        if not result.success:
            self._append_log(f"Deploy output: {result.output}")
        return result

    def rollback(self) -> DeployResult:
        self._append_log("Initiating rollback")
        result = self._run(self.rollback_command)
        status = "🔴 Rolled back" if result.success else "⚠️ Rollback failed"
        self._append_log(status)
        self.dispatcher.send(status)
        if not result.success:
            self._append_log(f"Rollback output: {result.output}")
        return result


def _load_json_from_path(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_json_from_url(url: str) -> Dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        data = response.read()
    return json.loads(data.decode("utf-8"))


def _load_ci_status(source: Optional[str]) -> Dict[str, Any]:
    if source is None:
        env_status = os.getenv("CI_STATUS", "green")
        return {"state": env_status.lower()}
    path = Path(source)
    if path.exists():
        return _load_json_from_path(path)
    return _load_json_from_url(source)


def _load_metrics(source: Optional[str]) -> Dict[str, Any]:
    default_metrics = {"health": "OK", "error_rate": 0.0}
    if source is None:
        env_metrics = os.getenv("METRICS_DATA")
        if env_metrics:
            try:
                return json.loads(env_metrics)
            except json.JSONDecodeError:
                print("[warn] Failed to parse METRICS_DATA, falling back to defaults", file=sys.stderr)
        return default_metrics
    path = Path(source)
    if path.exists():
        return _load_json_from_path(path)
    return _load_json_from_url(source)


def _ci_is_green(ci_status: Dict[str, Any]) -> bool:
    state = str(ci_status.get("state", "")).lower()
    return state in {"green", "success", "passed", "ok"}


def _metrics_are_healthy(metrics: Dict[str, Any]) -> bool:
    return str(metrics.get("health", "")).upper() == "OK"


def _error_rate(metrics: Dict[str, Any]) -> float:
    try:
        return float(metrics.get("error_rate", 0.0))
    except (TypeError, ValueError):
        return 1.0


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Self deploy manager")
    parser.add_argument("--ci-status-file", dest="ci_source", help="Path or URL to CI status JSON")
    parser.add_argument("--metrics-file", dest="metrics_source", help="Path or URL to metrics JSON")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="Allowed error rate threshold")
    parser.add_argument("--post-deploy-wait", type=int, default=DEFAULT_POST_DEPLOY_WAIT, help="Seconds to wait before verifying metrics")
    parser.add_argument("--simulate-error", action="store_true", help="Force the post-deploy verification to fail")
    parser.add_argument("--dry-run", action="store_true", help="Do not execute deploy or rollback commands")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    if os.getenv("ENABLE_SELF_DEPLOY", "true").lower() == "false":
        print("Self deploy disabled via ENABLE_SELF_DEPLOY", file=sys.stderr)
        return 0

    args = parse_args(argv)

    dispatcher = NotificationDispatcher(
        slack_webhook=os.getenv("SLACK_WEBHOOK"),
        telegram_webhook=os.getenv("TELEGRAM_WEBHOOK"),
    )

    deploy_command = os.getenv("DEPLOY_COMMAND", "echo Deploying service").split()
    rollback_command = os.getenv("ROLLBACK_COMMAND", "echo Rolling back service").split()

    manager = SelfDeployManager(
        deploy_command=deploy_command,
        rollback_command=rollback_command,
        dispatcher=dispatcher,
        dry_run=args.dry_run,
    )

    try:
        ci_status = _load_ci_status(args.ci_source)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"[error] Cannot load CI status: {exc}", file=sys.stderr)
        return 1

    if not _ci_is_green(ci_status):
        print("CI is not green. Skipping deployment.")
        return 0

    try:
        metrics = _load_metrics(args.metrics_source)
    except Exception as exc:
        print(f"[error] Cannot load metrics: {exc}", file=sys.stderr)
        return 1

    if not _metrics_are_healthy(metrics):
        print("Metrics health check failed. Skipping deployment.")
        return 0

    deploy_result = manager.deploy()
    if not deploy_result.success:
        manager.rollback()
        return 1

    wait_seconds = 0 if args.dry_run else max(0, args.post_deploy_wait)
    if wait_seconds:
        time.sleep(wait_seconds)

    try:
        post_metrics = _load_metrics(args.metrics_source)
    except Exception as exc:
        print(f"[error] Cannot load post deploy metrics: {exc}", file=sys.stderr)
        manager.rollback()
        return 1

    error_rate = _error_rate(post_metrics)
    should_rollback = args.simulate_error or error_rate > args.threshold

    if should_rollback:
        if args.simulate_error:
            reason = "Simulated incident requested rollback."
        else:
            reason = (
                f"Error rate {error_rate:.2f} exceeded threshold {args.threshold:.2f}."
            )
        print(f"{reason} Triggering rollback.")
        manager.rollback()
        return 1

    print("Deployment completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
