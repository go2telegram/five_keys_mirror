# app/scheduler/jobs.py
import datetime as dt
from zoneinfo import ZoneInfo
from aiogram import Bot
from app.storage import USERS
from app.utils_openai import ai_generate
from app.ethics import ethics_validator, EthicsViolation

async def send_nudges(bot: Bot, tz_name: str, weekdays: set[str]):
    """
    Рассылка «мягких напоминаний» тем, кто согласился (USERS[uid]['subs'] == True).
    Дни недели фильтруем по TZ; тексты — короткие, через ChatGPT для свежести.
    """
    now_local = dt.datetime.now(ZoneInfo(tz_name))
    wd = now_local.strftime("%a")  # 'Mon', 'Tue', ...
    if weekdays and wd not in weekdays:
        return

    # Генерим короткий совет (3–4 строки)
    prompt = (
        "Сделай короткий мотивирующий чек-лист (3–4 строки) для энергии и здоровья: "
        "сон, утренний свет, 30 минут быстрой ходьбы. Пиши дружелюбно, без воды."
    )

    try:
        ethics_validator.ensure_allowed(
            "generate_nudge_content",
            details={"prompt": "энергия и здоровье"},
        )
    except EthicsViolation:
        # Если действие запрещено, не выполняем рассылку.
        return

    text = await ai_generate(prompt)
    if not text or text.startswith("⚠️"):
        text = "Микро-челлендж дня:\n☑️ Сон 7–9 часов\n☑️ 10 мин утреннего света\n☑️ 30 мин быстрой ходьбы"

    # Рассылаем тем, кто согласился на напоминания
    for uid, profile in USERS.items():
        if not profile.get("subs"):
            continue
        try:
            ethics_validator.ensure_allowed(
                "send_nudge_message",
                details={"user_id": uid, "has_opt_in": bool(profile.get("subs"))},
            )
        except EthicsViolation:
            continue

        try:
            await bot.send_message(uid, text)
        except Exception:
            # молча пропускаем закрытые чаты/блок
            pass
