"""Admin commands for monitoring autonomous research experiments."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from research.engine import engine

router = Router()


@router.message(Command("research_status"))
async def research_status(message: Message) -> None:
    """Send the current research dashboard to the admin."""
    if message.from_user.id != settings.ADMIN_ID:
        return

    await message.answer(engine.get_status())
