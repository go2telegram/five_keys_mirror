import os, hmac, hashlib, json
from aiohttp import web
from datetime import datetime, timezone

LOG = os.getenv("TRIBUTE_WEBHOOK_LOG", "1") == "1"
API_KEY = os.getenv("TRIBUTE_API_KEY") or ""

def _log(msg: str):
    if not LOG: return
    try:
        with open("./logs/tribute_webhook.log", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.utcnow():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass

def _verify_signature(body: bytes, signature_hex: str) -> bool:
    if not API_KEY or not signature_hex:  # если ключа нет  пропускаем проверку (режим разработки)
        return True
    try:
        mac = hmac.new(API_KEY.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(mac, signature_hex.lower())
    except Exception:
        return False

async def tribute_webhook(request: web.Request):
    try:
        body = await request.read()
        sig  = request.headers.get("trbt-signature", "")
        if not _verify_signature(body, sig):
            _log("invalid_signature")
            return web.json_response({"ok": False, "reason": "invalid_signature"}, status=401)

        # попробуем как JSON, иначе сырой текст
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            data = {"raw": body.decode("utf-8", "replace")}

        name = (data.get("name") or "").strip()
        _log(f"event {name}")

        # обработка базовых событий (минимально безопасно)
        if name == "new_subscription":
            payload = data.get("payload") or {}
            tg_id   = payload.get("telegram_user_id")
            price   = payload.get("amount")
            # отметим конверсию/событие в  (не упадём, если чего-то нет)
            try:
                from app.storage import save_event
                save_event(int(tg_id or 0), None, "sub_new", {"amount": price})
            except Exception:
                pass

        elif name == "cancelled_subscription":
            payload = data.get("payload") or {}
            tg_id   = payload.get("telegram_user_id")
            try:
                from app.storage import save_event
                save_event(int(tg_id or 0), None, "sub_cancel", {})
            except Exception:
                pass

        # сегда отвечаем ok (чтобы Tribute не ретрайл)
        return web.json_response({"ok": True})
    except Exception as e:
        _log(f"exception: {e}")
        return web.json_response({"ok": False, "reason": "server_error"}, status=500)
