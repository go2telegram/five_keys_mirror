"""Admin command exposing finance metrics."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from analytics.business import collect_business_metrics, format_finance_report
from app.config import settings

router = Router(name="admin_finance")


@router.message(Command("finance"))
async def finance(message: Message) -> None:
    if not settings.ENABLE_BUSINESS_ANALYTICS:
        return
    if message.from_user.id != settings.ADMIN_ID:
        return

    metrics = collect_business_metrics()
    await message.answer(format_finance_report(metrics))
