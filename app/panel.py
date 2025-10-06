from __future__ import annotations

import hmac

from aiohttp import web

from app.config import settings
from app.security import get_panel_logs, redact_text

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def _authorised(secret: str | None) -> bool:
    configured = bool(getattr(settings, "CALLBACK_SECRET", ""))
    if not configured:
        return False
    if secret is None:
        return False
    expected = settings.CALLBACK_SECRET or ""
    try:
        return hmac.compare_digest(secret, expected)
    except ValueError:
        return False


async def logs_handler(request: web.Request) -> web.Response:
    token = request.headers.get("X-Panel-Token") or request.query.get("secret")
    if not getattr(settings, "CALLBACK_SECRET", ""):
        return web.json_response({"error": "callback_secret_not_configured"}, status=503)
    if not _authorised(token):
        return web.json_response({"error": "forbidden"}, status=403)

    limit_raw = request.query.get("limit")
    try:
        limit = int(limit_raw) if limit_raw else DEFAULT_LIMIT
    except ValueError:
        return web.json_response({"error": "invalid_limit"}, status=400)

    limit = max(1, min(limit, MAX_LIMIT))
    logs = [redact_text(line) for line in get_panel_logs(limit)]
    return web.json_response({"logs": logs})


def setup_panel(app_web: web.Application) -> None:
    app_web.router.add_get("/panel/logs", logs_handler)
