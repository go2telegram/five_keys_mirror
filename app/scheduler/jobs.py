# app/scheduler/jobs.py
import datetime as dt
from zoneinfo import ZoneInfo
from aiogram import Bot
from app.storage import USERS`nfrom app.texts import DRIP_FREE_MESSAGES, UPSELL_BASIC_MESSAGE
from app.utils_openai import ai_generate

async def send_nudges(bot: Bot, tz_name: str, weekdays: set[str]):
    """
    Р Р°СЃСЃС‹Р»РєР° В«РјСЏРіРєРёС… РЅР°РїРѕРјРёРЅР°РЅРёР№В» С‚РµРј, РєС‚Рѕ СЃРѕРіР»Р°СЃРёР»СЃСЏ (USERS[uid]['subs'] == True).
    Р”РЅРё РЅРµРґРµР»Рё С„РёР»СЊС‚СЂСѓРµРј РїРѕ TZ; С‚РµРєСЃС‚С‹ вЂ” РєРѕСЂРѕС‚РєРёРµ, С‡РµСЂРµР· ChatGPT РґР»СЏ СЃРІРµР¶РµСЃС‚Рё.
    """
    now_local = dt.datetime.now(ZoneInfo(tz_name))
    wd = now_local.strftime("%a")  # 'Mon', 'Tue', ...
    if weekdays and wd not in weekdays:
        return

    # Р“РµРЅРµСЂРёРј РєРѕСЂРѕС‚РєРёР№ СЃРѕРІРµС‚ (3вЂ“4 СЃС‚СЂРѕРєРё)
    prompt = (
        "РЎРґРµР»Р°Р№ РєРѕСЂРѕС‚РєРёР№ РјРѕС‚РёРІРёСЂСѓСЋС‰РёР№ С‡РµРє-Р»РёСЃС‚ (3вЂ“4 СЃС‚СЂРѕРєРё) РґР»СЏ СЌРЅРµСЂРіРёРё Рё Р·РґРѕСЂРѕРІСЊСЏ: "
        "СЃРѕРЅ, СѓС‚СЂРµРЅРЅРёР№ СЃРІРµС‚, 30 РјРёРЅСѓС‚ Р±С‹СЃС‚СЂРѕР№ С…РѕРґСЊР±С‹. РџРёС€Рё РґСЂСѓР¶РµР»СЋР±РЅРѕ, Р±РµР· РІРѕРґС‹."
    )
    text = await ai_generate(prompt)
    if not text or text.startswith("вљ пёЏ"):
        text = "РњРёРєСЂРѕ-С‡РµР»Р»РµРЅРґР¶ РґРЅСЏ:\nв‘пёЏ РЎРѕРЅ 7вЂ“9 С‡Р°СЃРѕРІ\nв‘пёЏ 10 РјРёРЅ СѓС‚СЂРµРЅРЅРµРіРѕ СЃРІРµС‚Р°\nв‘пёЏ 30 РјРёРЅ Р±С‹СЃС‚СЂРѕР№ С…РѕРґСЊР±С‹"

    # Р Р°СЃСЃС‹Р»Р°РµРј С‚РµРј, РєС‚Рѕ СЃРѕРіР»Р°СЃРёР»СЃСЏ РЅР° РЅР°РїРѕРјРёРЅР°РЅРёСЏ
    for uid, profile in USERS.items():
        if not profile.get("subs"):
            continue
        try:
            await bot.send_message(uid, text)
        except Exception:
            # РјРѕР»С‡Р° РїСЂРѕРїСѓСЃРєР°РµРј Р·Р°РєСЂС‹С‚С‹Рµ С‡Р°С‚С‹/Р±Р»РѕРє
            pass


# --- Drip & Upsell ---
from datetime import timedelta
DRIP_COOLDOWN = timedelta(hours=72)
UPSELL_COOLDOWN = timedelta(days=7)

async def drip_campaign(bot):
    """1) есплатникам — раз в 72ч одно сообщение; 2) Basic — раз в 7д апселл на Pro."""
    now = datetime.now(timezone.utc)
    for uid, u in USERS.items():
        sub = u.get("subscription") or {}
        until = sub.get("until")
        plan  = (sub.get("plan") or "").lower()

        active = False
        if until:
            try:
                dtu = datetime.fromisoformat(until)
                if dtu.tzinfo is None: dtu = dtu.replace(tzinfo=timezone.utc)
                active = dtu > now
            except Exception:
                active = False

        if not active:
            last = u.get("last_drip_ts")
            if (not last) or (now - datetime.fromisoformat(last) >= DRIP_COOLDOWN):
                idx = int(u.get("drip_idx", 0)) % max(1, len(DRIP_FREE_MESSAGES))
                msg = DRIP_FREE_MESSAGES[idx]
                try:    await bot.send_message(uid, msg)
                except: pass
                u["last_drip_ts"] = now.isoformat()
                u["drip_idx"] = idx + 1
            continue

        if active and plan == "basic":
            last_up = u.get("last_upsell_ts")
            if (not last_up) or (now - datetime.fromisoformat(last_up) >= UPSELL_COOLDOWN):
                try:    await bot.send_message(uid, UPSELL_BASIC_MESSAGE)
                except: pass
                u["last_upsell_ts"] = now.isoformat()
