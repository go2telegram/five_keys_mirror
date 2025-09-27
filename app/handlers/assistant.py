from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from app.utils_openai import ai_generate

router = Router()


@router.message(Command("assistant"))
async def assistant_cmd(m: Message):
    prompt = m.text.replace("/assistant", "").strip()
    if not prompt:
        await m.answer("Напиши после команды тему. Например:\n/assistant сделай короткое напоминание про пользу сна для митохондрий")
        return
    txt = await ai_generate(prompt)
    await m.answer(txt)
