from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from app.storage import get_regulation_state

router = Router()


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


@router.message(Command("regulation_status"))
async def regulation_status(message: Message) -> None:
    state = get_regulation_state()

    if not settings.ENABLE_REGULATION_LAYER:
        await message.answer(
            "\n".join(
                [
                    "⚠️ Слой регулирования отключён.",
                    "Установите ENABLE_REGULATION_LAYER=true и перезапустите сервис.",  # noqa: E501
                ]
            )
        )
        return

    tax = state.get("tax_rate", 0.0)
    subsidy = state.get("subsidy_rate", 0.0)
    balance = state.get("economic_balance", 1.0)
    notes = state.get("notes", "")
    last_updated = state.get("last_updated") or "—"

    text = (
        "📈 Текущее состояние экономики\n"
        f"Налог: {_format_percent(tax)}\n"
        f"Субсидия: {_format_percent(subsidy)}\n"
        f"Баланс: {balance:.3f}\n"
        f"Комментарий: {notes}\n"
        f"Обновлено: {last_updated}"
    )
    await message.answer(text)
