import datetime as dt
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.storage import USERS
from app.utils_openai import ai_generate


async def send_nudges(bot: Bot, tz_name: str, weekdays: set[str]):
    """Send daily nudges to subscribed users."""

    now_local = dt.datetime.now(ZoneInfo(tz_name))
    wd = now_local.strftime("%a")  # 'Mon', 'Tue', ...
    if weekdays and wd not in weekdays:
        return

    prompt = (
        "Сделай короткий мотивирующий чек-лист (3–4 строки) для энергии и здоровья: "
        "сон, утренний свет, 30 минут быстрой ходьбы. Пиши дружелюбно, без воды."
    )
    text = await ai_generate(prompt)
    if not text or text.startswith("⚠️"):
        text = (
            "Микро-челлендж дня:\n☑️ Сон 7–9 часов\n☑️ 10 мин утреннего света\n☑️ 30 мин быстрой ходьбы"
        )

    for uid, profile in USERS.items():
        if not profile.get("subs"):
            continue
        try:
            await bot.send_message(uid, text)
        except Exception:
            pass
