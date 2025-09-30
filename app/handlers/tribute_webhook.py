import hashlib
import hmac
import json
import os
from aiohttp import web
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.db.session import session_scope
from app.repo import events as events_repo
from app.repo import referrals as referrals_repo
from app.repo import subscriptions as subscriptions_repo
from app.repo import users as users_repo

LOG = os.getenv("TRIBUTE_WEBHOOK_LOG", "0") == "1"
INSECURE = os.getenv("TRIBUTE_WEBHOOK_INSECURE", "0") == "1"
NOTIFY = True

BASIC_KEYS = [x.strip().lower() for x in settings.SUB_BASIC_MATCH.split(",") if x.strip()]
PRO_KEYS = [x.strip().lower() for x in settings.SUB_PRO_MATCH.split(",") if x.strip()]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _infer_plan(name: str) -> str | None:
    n = (name or "").lower()
    if any(k in n for k in PRO_KEYS):
        return "pro"
    if any(k in n for k in BASIC_KEYS):
        return "basic"
    return None


def _parse_until(expires_iso: str | None) -> datetime:
    if expires_iso:
        try:
            return datetime.fromisoformat(expires_iso.replace("Z", "+00:00"))
        except Exception:
            pass
    return _now() + timedelta(days=30)


async def _notify_user(user_id: int, plan: str):
    try:
        bot = Bot(token=settings.BOT_TOKEN)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔓 Открыть Premium", callback_data="premium:menu")]
            ]
        )
        text = (
            f"🎉 <b>Подписка активирована</b>\n\n"
            f"Тариф: <b>MITO {plan.title()}</b>\n"
            f"Доступ открыт. Нажмите кнопку ниже, чтобы перейти к премиум-разделам."
        )
        await bot.send_message(user_id, text, reply_markup=kb)
        await bot.session.close()
    except Exception as exc:
        if LOG:
            print(f"[TRIBUTE] notify failed for user={user_id}: {exc}")


async def tribute_webhook(request: web.Request) -> web.Response:
    raw = await request.read()

    signature = request.headers.get("trbt-signature") or ""
    mac = hmac.new(settings.TRIBUTE_API_KEY.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, signature):
        if INSECURE:
            if LOG:
                print("[TRIBUTE] insecure accept (bad/missing signature)")
        else:
            return web.json_response({"ok": False, "reason": "invalid_signature"}, status=401)

    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)

    ev = data.get("name")
    payload = data.get("payload", {}) or {}
    tg_id = payload.get("telegram_user_id")
    try:
        tg_id_int = int(tg_id) if tg_id is not None else None
    except (TypeError, ValueError):
        tg_id_int = None
    sub_name = payload.get("subscription_name") or payload.get("donation_name") or ""
    expires = payload.get("expires_at")

    if ev == "new_subscription":
        plan = _infer_plan(sub_name) or "basic"
        if not tg_id_int:
            return web.json_response({"ok": False, "reason": "no_telegram_id"}, status=400)

        until = _parse_until(expires)
        async with session_scope() as session:
            await users_repo.get_or_create_user(session, tg_id_int, None)
            await subscriptions_repo.set_plan(session, tg_id_int, plan, until=until)
            referral = await referrals_repo.get_by_invited(session, tg_id_int)
            if referral and referral.converted_at is None:
                await referrals_repo.convert(session, tg_id_int, bonus_days=0)
                await events_repo.log(
                    session,
                    referral.referrer_id,
                    "ref_conversion",
                    {"invited_id": tg_id_int, "plan": plan},
                )
            await events_repo.log(
                session,
                tg_id_int,
                "subscription_activated",
                {"plan": plan, "until": until.isoformat()},
            )
            await session.commit()

        if LOG:
            print(f"[TRIBUTE] activated: user={tg_id_int} plan={plan} until={until.isoformat()}")

        if NOTIFY:
            await _notify_user(tg_id_int, plan)
        return web.json_response({"ok": True})

    if ev == "cancelled_subscription":
        if not tg_id_int:
            return web.json_response({"ok": True, "ignored": "no_telegram_id"})
        if not expires:
            return web.json_response({"ok": True})

        try:
            until = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        except Exception:
            until = _now()

        async with session_scope() as session:
            sub = await subscriptions_repo.get(session, tg_id_int)
            if sub:
                sub.until = until
                await events_repo.log(
                    session,
                    tg_id_int,
                    "subscription_cancelled",
                    {"until": until.isoformat()},
                )
                await session.commit()

        return web.json_response({"ok": True})

    return web.json_response({"ok": True, "ignored": ev or ""})
