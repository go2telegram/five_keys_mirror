from __future__ import annotations

import hashlib
import hmac
import json

from aiohttp import web

from app.config import settings
from app.services.payments import finalize_successful_payment, verify_signature


async def payments_webhook(request: web.Request) -> web.Response:
    secret = settings.PAYMENTS_WEBHOOK_SECRET or settings.PREMIUM_HMAC_SECRET
    raw_body = await request.text()
    if secret:
        signature = request.headers.get("X-Premium-Signature", "")
        digest = hmac.new(secret.encode("utf-8"), raw_body.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, digest):
            return web.json_response({"status": "error", "reason": "invalid_signature"}, status=403)

    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError:
        return web.json_response({"status": "error", "reason": "invalid_json"}, status=400)

    payload = data.get("payload") or {}
    if not isinstance(payload, dict):
        return web.json_response({"status": "error", "reason": "missing_payload"}, status=400)

    status = data.get("status", "").lower()
    txn_id = str(data.get("txn_id") or "")
    try:
        verify_signature(payload)
        if status == "paid":
            await finalize_successful_payment(payload, provider_charge_id=txn_id or "external")
    except Exception as exc:  # pragma: no cover - defensive
        return web.json_response({"status": "error", "reason": str(exc)}, status=400)

    return web.json_response({"status": "ok"})


__all__ = ["payments_webhook"]
