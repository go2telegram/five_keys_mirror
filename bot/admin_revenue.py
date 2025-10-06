"""Admin handlers for the revenue dashboard."""
from __future__ import annotations

import tempfile
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from revenue import get_revenue_summary, import_csv

router = Router(name="admin-revenue")


def _format_money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def _ensure_admin(message: Message) -> bool:
    return message.from_user and message.from_user.id == settings.ADMIN_ID


@router.message(Command("revenue"))
async def revenue_report(message: Message):
    if not _ensure_admin(message):
        return

    summary = get_revenue_summary()
    totals = summary["totals"]

    roi_text = "—" if totals["roi"] is None else f"{totals['roi'] * 100:.1f}%"
    epc_text = f"{totals['epc']:.2f} ₽"

    lines = [
        "💰 <b>Revenue dashboard</b>",
        f"Доход (payouts): {_format_money(totals['revenue'])} ₽",
        f"Затраты (traffic): {_format_money(totals['spend'])} ₽",
        f"ROI: {roi_text}",
        f"EPC: {epc_text}",
        "",
        f"Офферов: {totals['offers']} | Кликов: {totals['clicks']} |",
        f"Конверсий: {totals['conversions']} | Выплат: {totals['payouts']}",
        "",
        "📈 ROI по кампаниям:",
    ]

    if summary["roi_per_campaign"]:
        for item in summary["roi_per_campaign"]:
            roi_value = "—" if item["roi"] is None else f"{item['roi'] * 100:.1f}%"
            lines.append(
                f"• {item['campaign']}: доход {_format_money(item['revenue'])} ₽,"
                f" расходы {_format_money(item['spend'])} ₽, ROI {roi_value}"
            )
    else:
        lines.append("нет данных")

    trends = summary.get("trends", [])[:7]
    if trends:
        lines.append("\n📊 Последние дни:")
        for day in trends:
            lines.append(
                f"{day['day']}: кликов {day['clicks']}, конверсий {day['conversions']},"
                f" выручка {_format_money(day['payout_revenue'])} ₽, расходы {_format_money(day['spend'])} ₽"
            )

    lines.append("\nДля импорта отправь CSV с подписью <code>#revenue</code> или команду /revenue_import.")

    await message.answer("\n".join(lines))


@router.message(Command("revenue_import"))
async def revenue_import_hint(message: Message):
    if not _ensure_admin(message):
        return

    await message.answer(
        "📥 Отправь CSV файл с подписью <code>#revenue</code>.\n"
        "Формат строк: type,id,offer_id,click_id,conversion_id,campaign,name,cost,revenue,amount,timestamp."
    )


@router.message(F.document)
async def revenue_csv_upload(message: Message, bot: Bot):
    if not _ensure_admin(message):
        return

    caption = (message.caption or "").lower()
    if "#revenue" not in caption:
        return

    suffix = Path(message.document.file_name or "").suffix.lower()
    if suffix != ".csv":
        await message.answer("⚠️ Нужен CSV файл.")
        return

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp_path = Path(tmp.name)
    try:
        await bot.download(message.document.file_id, destination=tmp_path)
        stats = import_csv(tmp_path)
    except Exception as exc:  # pragma: no cover - defensive
        await message.answer(f"❌ Ошибка импорта: {exc}")
        return
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    errors = stats.get("errors") or []
    text = (
        "✅ Импорт завершён.\n"
        f"Офферы: {stats['offers']}, клики: {stats['clicks']}, конверсии: {stats['conversions']},"
        f" выплаты: {stats['payouts']}."
    )
    if errors:
        text += f"\n⚠️ Пропущено строк: {len(errors)}"
    await message.answer(text)


__all__ = ["router"]
