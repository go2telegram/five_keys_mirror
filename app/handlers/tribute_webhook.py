import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from aiohttp import web

from app.config import settings
from app.storage import (
    ensure_user,
    increment_ref_conversion,
    set_subscription,
    update_subscription_expiry,
)

# --- уведомления ---
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

LOG = os.getenv("TRIBUTE_WEBHOOK_LOG", "0") == "1"
INSECURE = os.getenv("TRIBUTE_WEBHOOK_INSECURE", "0") == "1"
NOTIFY = True

logger = logging.getLogger(__name__)

BASIC_KEYS = [x.strip().lower() for x in settings.SUB_BASIC_MATCH.split(",") if x.strip()]
PRO_KEYS   = [x.strip().lower() for x in settings.SUB_PRO_MATCH.split(",") if x.strip()]

def _now(): return datetime.now(timezone.utc)

def _infer_plan(name: str) -> str | None:
    n = (name or "").lower()
    if any(k in n for k in PRO_KEYS):
        return "pro"
    if any(k in n for k in BASIC_KEYS):
        return "basic"
    return None

def _parse_expiry(expires_iso: str | None) -> datetime | None:
    if not expires_iso:
        return None
    try:
        return datetime.fromisoformat(expires_iso.replace("Z", "+00:00"))
    except Exception:
        return None

async def _notify_user(user_id: int, plan: str):
    try:
        bot = Bot(token=settings.BOT_TOKEN)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔓 Открыть Premium", callback_data="premium:menu")]]
        )
        text = (
            f"🎉 <b>Подписка активирована</b>\n\n"
            f"Тариф: <b>MITO {plan.title()}</b>\n"
            f"Доступ открыт. Нажмите кнопку ниже, чтобы перейти к премиум-разделам."
        )
        await bot.send_message(user_id, text, reply_markup=kb)
        await bot.session.close()
    except Exception as exc:  # noqa: BLE001 - notify failures shouldn't crash webhook
        if LOG:
            logger.warning("Tribute notify failed for user=%s: %s", user_id, exc)

async def tribute_webhook(request: web.Request) -> web.Response:
    raw = await request.read()

    signature = request.headers.get("trbt-signature") or ""
    mac = hmac.new(settings.TRIBUTE_API_KEY.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, signature):
        if INSECURE:
            if LOG:
                logger.warning("Tribute webhook accepted with invalid signature (insecure mode)")
        else:
            return web.json_response({"ok": False, "reason": "invalid_signature"}, status=401)

    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)

    ev = data.get("name")
    payload = data.get("payload", {}) or {}
    tg_id = payload.get("telegram_user_id")
    sub_name = payload.get("subscription_name") or payload.get("donation_name") or ""
    expires = payload.get("expires_at")

    if ev == "new_subscription":
        plan = _infer_plan(sub_name) or "basic"
        if tg_id:
            user_id = int(tg_id)
            expiry = _parse_expiry(expires)
            profile, _ = await ensure_user(user_id)
            await set_subscription(user_id, plan_code=plan, expires_at=expiry)

            if profile.referred_by:
                await increment_ref_conversion(profile.referred_by)
                if LOG:
                    logger.info("Tribute ref conversion user=%s by=%s", user_id, profile.referred_by)

            if NOTIFY:
                await _notify_user(user_id, plan)
            return web.json_response({"ok": True})
        return web.json_response({"ok": False, "reason": "no_telegram_id"}, status=400)

    if ev == "cancelled_subscription":
        if tg_id:
            user_id = int(tg_id)
            expiry = _parse_expiry(expires)
            await update_subscription_expiry(user_id, expiry)
        return web.json_response({"ok": True})

    return web.json_response({"ok": True, "ignored": ev or ""})
