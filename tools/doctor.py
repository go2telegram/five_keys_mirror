#!/usr/bin/env python3
"""Simple health diagnostics for the bot runtime."""
from __future__ import annotations

import asyncio
import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import SplitResult, urlsplit, urlunsplit

from dotenv import load_dotenv

STATUS_ORDER = {"OK": 0, "WARN": 1, "FAIL": 2}


@dataclass
class Action:
    message: str
    severity: str


@dataclass
class CheckReport:
    name: str
    status: str
    details: Dict[str, Any]
    actions: List[Action]


def upgrade_status(current: str, new: str) -> str:
    if STATUS_ORDER[new] > STATUS_ORDER[current]:
        return new
    return current


def redact_url(raw_url: str) -> str:
    try:
        parts: SplitResult = urlsplit(raw_url)
    except ValueError:
        return raw_url

    netloc = parts.netloc
    if "@" in netloc:
        auth, host = netloc.rsplit("@", 1)
        if ":" in auth:
            user, _ = auth.split(":", 1)
            auth = f"{user}:***"
        else:
            auth = f"{auth}:***"
        netloc = f"{auth}@{host}"

    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def check_environment(env: Dict[str, str]) -> CheckReport:
    status = "OK"
    details: Dict[str, Any] = {}
    actions: List[Action] = []

    required = ["BOT_TOKEN", "ADMIN_ID"]
    missing_required = [var for var in required if not env.get(var)]
    if missing_required:
        status = upgrade_status(status, "FAIL")
        actions.append(
            Action(
                "Set required environment variables: {}.".format(
                    ", ".join(missing_required)
                ),
                "FAIL",
            )
        )
    else:
        details["BOT_TOKEN"] = bool(env.get("BOT_TOKEN"))
        details["ADMIN_ID"] = env.get("ADMIN_ID")

    log_path = env.get("LOG_PATH")
    if not log_path:
        status = upgrade_status(status, "WARN")
        actions.append(
            Action(
                "Define LOG_PATH to point to a writable directory for log output.",
                "WARN",
            )
        )
    else:
        path_obj = Path(log_path)
        details["LOG_PATH"] = str(path_obj)
        if not path_obj.exists():
            status = upgrade_status(status, "WARN")
            actions.append(
                Action(
                    f"Create the log directory at {log_path} before starting the bot.",
                    "WARN",
                )
            )
        elif not os.access(path_obj, os.W_OK):
            status = upgrade_status(status, "WARN")
            actions.append(
                Action(
                    f"Grant write permissions for {log_path} to the bot user.",
                    "WARN",
                )
            )

    web_port = env.get("WEB_PORT")
    if not web_port:
        status = upgrade_status(status, "WARN")
        actions.append(
            Action(
                "Set WEB_PORT to the desired HTTP port (default 8080).",
                "WARN",
            )
        )
    else:
        try:
            port = int(web_port)
            if not (0 < port < 65536):
                raise ValueError
            details["WEB_PORT"] = port
        except ValueError:
            status = upgrade_status(status, "FAIL")
            actions.append(
                Action(
                    f"WEB_PORT value '{web_port}' is invalid; specify an integer between 1 and 65535.",
                    "FAIL",
                )
            )

    return CheckReport("environment", status, details, actions)


def check_health_port(env: Dict[str, str]) -> CheckReport:
    host = env.get("WEB_HOST", "127.0.0.1") or "127.0.0.1"
    port_raw = env.get("WEB_PORT", "8080")
    details: Dict[str, Any] = {"host": host}
    actions: List[Action] = []

    try:
        port = int(port_raw)
    except ValueError:
        return CheckReport(
            "health_port",
            "FAIL",
            {"error": f"WEB_PORT '{port_raw}' is not a valid integer."},
            [
                Action(
                    "Adjust WEB_PORT to a numeric value before launching the bot.",
                    "FAIL",
                )
            ],
        )

    details["port"] = port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as exc:
        return CheckReport(
            "health_port",
            "FAIL",
            {"error": str(exc), "host": host, "port": port},
            [
                Action(
                    f"Stop the process using {host}:{port} or change WEB_PORT.",
                    "FAIL",
                )
            ],
        )
    finally:
        sock.close()

    return CheckReport(
        "health_port",
        "OK",
        details,
        actions,
    )


def check_database(env: Dict[str, str]) -> CheckReport:
    url = env.get("DATABASE_URL")
    if not url:
        return CheckReport(
            "database",
            "WARN",
            {"configured": False},
            [
                Action(
                    "Set DATABASE_URL to enable persistent storage connectivity checks.",
                    "WARN",
                )
            ],
        )

    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import SQLAlchemyError
        from sqlalchemy.ext.asyncio import create_async_engine
    except Exception as exc:  # pragma: no cover - safety guard when deps missing
        return CheckReport(
            "database",
            "WARN",
            {"url": redact_url(url), "error": f"SQLAlchemy unavailable: {exc}"},
            [
                Action(
                    "Install SQLAlchemy dependencies to run database diagnostics.",
                    "WARN",
                )
            ],
        )

    async_mode = "+async" in url or url.startswith("postgresql+asyncpg") or url.startswith("sqlite+aiosqlite")

    if async_mode:
        async def _ping_async() -> None:
            engine = create_async_engine(url)
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            finally:
                await engine.dispose()

        try:
            asyncio.run(_ping_async())
        except Exception as exc:
            return CheckReport(
                "database",
                "FAIL",
                {"url": redact_url(url), "error": str(exc)},
                [
                    Action(
                        "Verify database credentials, host reachability, and migrations.",
                        "FAIL",
                    )
                ],
            )
    else:
        engine = create_engine(url, future=True)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            return CheckReport(
                "database",
                "FAIL",
                {"url": redact_url(url), "error": str(exc)},
                [
                    Action(
                        "Check the database DSN and ensure the server is reachable.",
                        "FAIL",
                    )
                ],
            )
        finally:
            engine.dispose()

    return CheckReport(
        "database",
        "OK",
        {"url": redact_url(url)},
        [],
    )


def check_redis(env: Dict[str, str]) -> CheckReport:
    url = env.get("REDIS_URL")
    if not url:
        return CheckReport(
            "redis",
            "WARN",
            {"configured": False},
            [
                Action(
                    "Set REDIS_URL if caching or rate limits rely on Redis.",
                    "WARN",
                )
            ],
        )

    try:
        import redis.asyncio as aioredis
        from redis.exceptions import RedisError
    except Exception as exc:  # pragma: no cover - optional dependency
        return CheckReport(
            "redis",
            "WARN",
            {"url": redact_url(url), "error": f"redis-py unavailable: {exc}"},
            [
                Action(
                    "Install redis>=5 to enable Redis diagnostics.",
                    "WARN",
                )
            ],
        )

    async def _ping() -> None:
        client = aioredis.from_url(url)
        try:
            await client.ping()
        finally:
            await client.close()

    try:
        asyncio.run(_ping())
    except RedisError as exc:
        return CheckReport(
            "redis",
            "FAIL",
            {"url": redact_url(url), "error": str(exc)},
            [
                Action(
                    "Ensure Redis is reachable and the credentials are valid.",
                    "FAIL",
                )
            ],
        )
    except Exception as exc:
        return CheckReport(
            "redis",
            "FAIL",
            {"url": redact_url(url), "error": str(exc)},
            [
                Action(
                    "Verify REDIS_URL and network connectivity to the Redis host.",
                    "FAIL",
                )
            ],
        )

    return CheckReport("redis", "OK", {"url": redact_url(url)}, [])


def check_library_versions() -> CheckReport:
    libraries = ["aiogram", "aiohttp", "redis", "SQLAlchemy", "python-dotenv"]
    details: Dict[str, Any] = {}
    missing: List[str] = []

    for lib in libraries:
        try:
            details[lib] = metadata.version(lib)
        except metadata.PackageNotFoundError:
            details[lib] = None
            missing.append(lib)

    status = "OK" if not missing else "WARN"
    actions: List[Action] = []
    if missing:
        actions.append(
            Action(
                "Install missing libraries: {}.".format(", ".join(sorted(missing))),
                "WARN",
            )
        )

    return CheckReport("libraries", status, details, actions)


def collect_reports(env: Dict[str, str]) -> Dict[str, CheckReport]:
    checks = [
        check_environment,
        check_health_port,
        check_database,
        check_redis,
        lambda _env: check_library_versions(),
    ]

    reports: Dict[str, CheckReport] = {}
    for func in checks:
        report = func(env)
        reports[report.name] = report
    return reports


def aggregate_status(reports: Dict[str, CheckReport]) -> str:
    overall = "OK"
    for report in reports.values():
        overall = upgrade_status(overall, report.status)
    return overall


def build_payload(reports: Dict[str, CheckReport]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {},
        "actions": [],
    }

    for name, report in reports.items():
        payload["checks"][name] = {
            "status": report.status,
            "details": report.details,
        }
        for action in report.actions:
            payload["actions"].append(
                {
                    "component": name,
                    "status": action.severity,
                    "action": action.message,
                }
            )

    payload["status"] = aggregate_status(reports)
    return payload


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    load_dotenv(repo_root / ".env")
    env = dict(os.environ)

    reports = collect_reports(env)
    payload = build_payload(reports)

    print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 0 if payload["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
