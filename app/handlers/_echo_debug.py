"""Debug echo router used in diagnostics mode."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

router = Router(name="echo_debug")
log_echo = logging.getLogger("echo")


@router.message(F.text)
async def echo(message: Message) -> None:
    """Echo incoming text messages for quick manual checks."""

    log_echo.info(
        "ECHO uid=%s msg_id=%s text=%r",
        getattr(message.from_user, "id", None),
        getattr(message, "message_id", None),
        message.text,
    )
    await message.reply(f"echo: {message.text}")
