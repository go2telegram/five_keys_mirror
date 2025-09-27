from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from aiogram import Bot

from app.storage import USERS
from app.texts import DRIP_FREE_MESSAGES, UPSELL_BASIC_MESSAGE
from app.utils_openai import ai_generate

# ---------------------------------------------------------
# Ежедневные "мягкие" напоминания (по подписке на рассылку)
# ---------------------------------------------------------
async def send_nudges(bot: Bot, tz_name: str, weekdays: set[str]):
    """
    Рассылка коротких напоминаний тем, кто согласился (USERS[uid]['subs'] == True).
    Дни недели фильтруем по tz; тексты — короткие, через ChatGPT для свежести.
    """
    now_local = datetime.now(ZoneInfo(tz_name))
    wd = now_local.strftime("%a")  # 'Mon','Tue',...
    if weekdays and wd not in weekdays:
        return

    # Генерим короткий совет (3–4 строки)
    prompt = (
        "Сделай короткий мотивирующий чек-лист (3–4 строки) для энергии и здоровья: "
        "сон, утренний свет, 30 минут быстрой ходьбы. Пиши дружелюбно, без воды."
    )
    text = await ai_generate(prompt)

    # Фоллбек
    if not text or not text.strip():
        text = (
            "Микро-челлендж дня:\n"
            "• Сон 7–9 часов\n"
            "• 10 мин утреннего света\n"
            "• 30 мин быстрой ходьбы"
        )

    for uid, profile in USERS.items():
        if not profile.get("subs"):
            continue
        try:
            await bot.send_message(uid, text)
        except Exception:
            pass

# ---------------------------------------------------------
# Drip & Upsell — по сегментам (бесплатники / Basic→Pro)
# ---------------------------------------------------------
DRIP_COOLDOWN = timedelta(hours=72)
UPSELL_COOLDOWN = timedelta(days=7)

async def drip_campaign(bot: Bot):
    now = datetime.now(timezone.utc)
    for uid, u in USERS.items():
        sub = u.get("subscription") or {}
        until = sub.get("until")
        plan  = (sub.get("plan") or "").lower()

        active = False
        if until:
            try:
                dtu = datetime.fromisoformat(until)
                if dtu.tzinfo is None:
                    dtu = dtu.replace(tzinfo=timezone.utc)
                active = dtu > now
            except Exception:
                active = False

        # Бесплатники → drip
        if not active:
            last = u.get("last_drip_ts")
            if (not last) or (now - datetime.fromisoformat(last) >= DRIP_COOLDOWN):
                idx = int(u.get("drip_idx", 0)) % max(1, len(DRIP_FREE_MESSAGES))
                msg = DRIP_FREE_MESSAGES[idx]
                try:
                    await bot.send_message(uid, msg)
                except Exception:
                    pass
                u["last_drip_ts"] = now.isoformat()
                u["drip_idx"] = idx + 1
            continue

        # Basic → апселл
        if active and plan == "basic":
            last_up = u.get("last_upsell_ts")
            if (not last_up) or (now - datetime.fromisoformat(last_up) >= UPSELL_COOLDOWN):
                try:
                    await bot.send_message(uid, UPSELL_BASIC_MESSAGE)
                except Exception:
                    pass
                u["last_upsell_ts"] = now.isoformat()
# --- expiry reminders ---
async def notify_expiring(bot):
    """
    ведомляет пользователей у кого подписка заканчивается через 3 дня, через 1 день и сегодня.
    """
    from app.storage_sqlite import get_session
    from app.db.models import Subscription
    now = datetime.now(timezone.utc).date()
    targets = set()
    with get_session() as s:
        subs = s.query(Subscription).all()
        for sub in subs:
            d = sub.until.date()
            delta = (d - now).days
            if delta in (3, 1, 0):
                targets.add((sub.user_id, delta, sub.plan, sub.until))

    for uid, delta, plan, until in targets:
        if delta == 3:
            text = f" одписка {plan.upper()} истечёт через 3 дня (до {until:%d.%m.%Y}). родлить?"
        elif delta == 1:
            text = f" автра истекает подписка {plan.upper()} (до {until:%d.%m.%Y}). ажмите одписка для продления."
        else:
            text = f" Сегодня заканчивается подписка {plan.upper()} (до {until:%d.%m.%Y}). родлить сейчас?"
        try:
            await bot.send_message(uid, text)
        except Exception:
            pass
