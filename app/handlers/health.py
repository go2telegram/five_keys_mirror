"""Health check command handlers."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings

router = Router(name="health")


if settings.DEBUG_COMMANDS:

    @router.message(Command("ping"))
    async def ping(message: Message) -> None:
        """Reply with a simple pong marker."""

        await message.answer("pong \u2705")
