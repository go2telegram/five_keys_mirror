from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.utils_openai import ai_generate

router = Router()


@router.message(Command("assistant"))
async def assistant_cmd(m: Message):
    prompt = m.text.replace("/assistant", "").strip()
    if not prompt:
        help_text = (
            "Напиши после команды тему. Например:\n"
            "/assistant сделай короткое напоминание про пользу сна для митохондрий"
        )
        await m.answer(help_text)
        return
    txt = await ai_generate(prompt)
    await m.answer(txt)
