"""Health check command handlers."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="health")


@router.message(Command("ping"))
async def ping(message: Message) -> None:
    """Reply with a simple pong marker."""

    await message.answer("pong \u2705")
