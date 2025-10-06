import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple

from aiohttp import web

from app.config import settings
from app.storage import ensure_user, user_set

# --- уведомления ---
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)

LOG = os.getenv("TRIBUTE_WEBHOOK_LOG", "0") == "1"
NOTIFY = os.getenv("TRIBUTE_WEBHOOK_NOTIFY", "1") == "1"

_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 30
_RATE_BUCKETS: Dict[str, Tuple[float, int]] = {}

BASIC_KEYS = [x.strip().lower() for x in settings.SUB_BASIC_MATCH.split(",") if x.strip()]
PRO_KEYS = [x.strip().lower() for x in settings.SUB_PRO_MATCH.split(",") if x.strip()]


def _now():
    return datetime.now(timezone.utc)


def _infer_plan(name: str) -> str | None:
    n = (name or "").lower()
    if any(k in n for k in PRO_KEYS):
        return "pro"
    if any(k in n for k in BASIC_KEYS):
        return "basic"
    return None


async def _activate(user_id: int, plan: str, expires_iso: str | None):
    if expires_iso:
        try:
            until = datetime.fromisoformat(expires_iso.replace("Z", "+00:00"))
        except Exception:
            until = _now() + timedelta(days=30)
    else:
        until = _now() + timedelta(days=30)
    profile = await ensure_user(user_id, {})
    profile["subscription"] = {
        "plan": plan,
        "since": _now().isoformat(),
        "until": until.isoformat(),
    }
    await user_set(user_id, profile)
    if LOG:
        logger.info(
            "Tribute subscription activated",
            extra={
                "event": "activated",
                "plan": plan,
                "user": _mask_user_id(user_id),
                "until": until.isoformat(),
            },
        )
    return profile


async def _notify_user(user_id: int, plan: str):
    try:
        bot = Bot(token=settings.BOT_TOKEN)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔓 Открыть Premium", callback_data="premium:menu")]
        ])
        text = (
            f"🎉 <b>Подписка активирована</b>\n\n"
            f"Тариф: <b>MITO {plan.title()}</b>\n"
            f"Доступ открыт. Нажмите кнопку ниже, чтобы перейти к премиум-разделам."
        )
        await bot.send_message(user_id, text, reply_markup=kb)
        await bot.session.close()
    except Exception as e:
        if LOG:
            logger.warning(
                "Tribute notify failed",
                extra={"user": _mask_user_id(user_id), "error": str(e)},
            )


def _mask_user_id(user_id: int | None) -> str | None:
    if user_id is None:
        return None
    text = str(user_id)
    if len(text) <= 4:
        return text
    return f"***{text[-4:]}"


def _extract_remote(request: web.Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote or "unknown"


def _mask_remote(remote: str) -> str:
    if not remote:
        return "unknown"
    digest = hashlib.sha256(remote.encode("utf-8")).hexdigest()[:10]
    return f"hash:{digest}"


def _allow_request(key: str, *, limit: int | None = None, window: int | None = None) -> bool:
    if limit is None:
        limit = _RATE_LIMIT_MAX
    if window is None:
        window = _RATE_LIMIT_WINDOW
    if limit <= 0:
        return True

    now = time.monotonic()
    start, count = _RATE_BUCKETS.get(key, (now, 0))
    if now - start > window:
        _RATE_BUCKETS[key] = (now, 1)
        return True
    if count >= limit:
        return False
    _RATE_BUCKETS[key] = (start, count + 1)
    return True


def _log_event(message: str, **fields) -> None:
    if not LOG:
        return
    safe_fields = {k: v for k, v in fields.items() if v is not None}
    logger.info("Tribute webhook %s", message, extra={"payload": safe_fields})


async def tribute_webhook(request: web.Request) -> web.Response:
    raw = await request.read()

    signature = request.headers.get("trbt-signature") or ""
    remote = _extract_remote(request)
    rate_key = f"{remote}:{signature[:16] if signature else 'missing'}"
    if not _allow_request(rate_key):
        _log_event("rate_limited", remote=_mask_remote(remote))
        return web.json_response({"ok": False, "reason": "rate_limited"}, status=429)

    if not signature:
        _log_event("missing_signature", remote=_mask_remote(remote))
        return web.json_response({"ok": False, "reason": "missing_signature"}, status=401)

    mac = hmac.new(settings.TRIBUTE_API_KEY.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, signature):
        _log_event("invalid_signature", remote=_mask_remote(remote))
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
            profile = await _activate(user_id, plan, expires)

            # учёт конверсии для реферала
            ref_by = profile.get("referred_by")
            if ref_by:
                ref_profile = await ensure_user(ref_by, {
                    "ref_conversions": 0,
                    "ref_users": [],
                })
                ref_profile["ref_conversions"] = ref_profile.get("ref_conversions", 0) + 1
                await user_set(ref_by, ref_profile)
            _log_event(
                "ref_conversion",
                referrer=_mask_user_id(ref_by),
                user=_mask_user_id(user_id),
            )

            if NOTIFY:
                await _notify_user(user_id, plan)
            _log_event(
                "subscription_processed",
                event=ev,
                plan=plan,
                remote=_mask_remote(remote),
                user=_mask_user_id(tg_id if tg_id is not None else None),
            )
            return web.json_response({"ok": True})
        return web.json_response({"ok": False, "reason": "no_telegram_id"}, status=400)

    if ev == "cancelled_subscription":
        if tg_id:
            user_id = int(tg_id)
            profile = await ensure_user(user_id, {})
            if profile.get("subscription") and expires:
                try:
                    profile["subscription"]["until"] = datetime.fromisoformat(
                        expires.replace("Z", "+00:00")
                    ).isoformat()
                except Exception:
                    pass
                await user_set(user_id, profile)
        _log_event(
            "subscription_processed",
            event=ev,
            remote=_mask_remote(remote),
            user=_mask_user_id(tg_id if tg_id is not None else None),
        )
        return web.json_response({"ok": True})

    _log_event("ignored", event=ev or "", remote=_mask_remote(remote))
    return web.json_response({"ok": True, "ignored": ev or ""})
