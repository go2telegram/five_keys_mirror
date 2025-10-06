from __future__ import annotations

import json
from datetime import datetime, timezone

from aiohttp import ContentTypeError, web

from app.config import settings
from app.handlers import tribute_webhook as h_tw


async def handle_ping(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "ts": datetime.now(timezone.utc).isoformat()})


async def handle_doctor_echo(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, ContentTypeError):
        payload = {"raw": await request.text()}

    return web.json_response({"status": "ok", "echo": payload})


def create_web_app() -> web.Application:
    app_web = web.Application()
    app_web.router.add_get("/ping", handle_ping)
    app_web.router.add_post("/doctor/echo", handle_doctor_echo)
    app_web.router.add_post(settings.TRIBUTE_WEBHOOK_PATH, h_tw.tribute_webhook)
    return app_web
