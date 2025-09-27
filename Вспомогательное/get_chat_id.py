import asyncio
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties

API_TOKEN = "8488871667:AAH8OAzKk6cce8VYsPCIa2LOax6JxqagsYA"  # <-- сюда вставь токен


async def main():
    bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    @dp.message()
    async def echo(m: Message):
        print(f"\n=== CHAT INFO ===\n"
              f"chat.id = {m.chat.id}\n"
              f"type    = {m.chat.type}\n"
              f"title   = {m.chat.title}\n"
              f"username= {m.chat.username}\n"
              f"=============\n")
        await m.answer(f"Ваш chat.id: <code>{m.chat.id}</code>")

    print("Бот запущен. Напиши что-нибудь в группу/канал/личку с этим ботом.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
