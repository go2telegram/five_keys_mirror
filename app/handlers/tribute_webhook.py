import hmac, hashlib, json, os
from aiohttp import web
from datetime import datetime, timezone, timedelta

from app.config import settings
from app.storage import USERS
from growth.bonuses import award_referral_bonus
from growth.referrals import log_referral_event

# --- уведомления ---
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

LOG = os.getenv("TRIBUTE_WEBHOOK_LOG", "0") == "1"
INSECURE = os.getenv("TRIBUTE_WEBHOOK_INSECURE", "0") == "1"
NOTIFY = True

BASIC_KEYS = [x.strip().lower() for x in settings.SUB_BASIC_MATCH.split(",") if x.strip()]
PRO_KEYS   = [x.strip().lower() for x in settings.SUB_PRO_MATCH.split(",") if x.strip()]

def _now(): return datetime.now(timezone.utc)

def _infer_plan(name: str) -> str | None:
    n = (name or "").lower()
    if any(k in n for k in PRO_KEYS):   return "pro"
    if any(k in n for k in BASIC_KEYS): return "basic"
    return None

def _activate(user_id: int, plan: str, expires_iso: str | None):
    if expires_iso:
        try:
            until = datetime.fromisoformat(expires_iso.replace("Z","+00:00"))
        except Exception:
            until = _now() + timedelta(days=30)
    else:
        until = _now() + timedelta(days=30)
    USERS.setdefault(user_id, {})["subscription"] = {
        "plan": plan,
        "since": _now().isoformat(),
        "until": until.isoformat()
    }
    if LOG:
        print(f"[TRIBUTE] activated: user={user_id} plan={plan} until={until.isoformat()}")

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
        if LOG: print(f"[TRIBUTE] notify failed for user={user_id}: {e}")

async def tribute_webhook(request: web.Request) -> web.Response:
    raw = await request.read()

    signature = request.headers.get("trbt-signature") or ""
    mac = hmac.new(settings.TRIBUTE_API_KEY.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, signature):
        if INSECURE:
            if LOG: print("[TRIBUTE] insecure accept (bad/missing signature)")
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
            _activate(user_id, plan, expires)

            # учёт конверсии для реферала
            ref_by = USERS.get(user_id, {}).get("referred_by")
            if ref_by:
                USERS.setdefault(ref_by, {}).setdefault("ref_conversions", 0)
                USERS[ref_by]["ref_conversions"] += 1
                if LOG: print(f"[TRIBUTE] ref conversion: user={user_id} by={ref_by}")

                channel = (
                    USERS.get(ref_by, {})
                    .get("ref_channels", {})
                    .get(user_id)
                    or USERS.get(user_id, {}).get("referred_channel")
                )
                log_referral_event(
                    "conversion",
                    referrer_id=ref_by,
                    referred_id=user_id,
                    channel=channel,
                    metadata={
                        "source": "tribute",
                        "subscription": sub_name,
                        "plan": plan,
                    },
                )
                award_referral_bonus(
                    referrer_id=ref_by,
                    referred_id=user_id,
                    channel=channel,
                    metadata={
                        "source": "tribute",
                        "subscription": sub_name,
                        "plan": plan,
                    },
                )

            if NOTIFY:
                await _notify_user(user_id, plan)
            return web.json_response({"ok": True})
        return web.json_response({"ok": False, "reason": "no_telegram_id"}, status=400)

    if ev == "cancelled_subscription":
        if tg_id and tg_id in USERS and USERS[tg_id].get("subscription") and expires:
            try:
                USERS[tg_id]["subscription"]["until"] = datetime.fromisoformat(
                    expires.replace("Z", "+00:00")
                ).isoformat()
            except Exception:
                pass
        return web.json_response({"ok": True})

    return web.json_response({"ok": True, "ignored": ev or ""})
