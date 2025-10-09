"""Admin commands for growth analytics and UTM tooling."""
from __future__ import annotations

import shlex
from typing import Mapping

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.config import settings
from app.db.session import compat_session, session_scope
from app.growth import attribution

router = Router(name="admin_growth")


def _is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    allowed = set(settings.ADMIN_USER_IDS or [])
    admin_id = int(settings.ADMIN_ID or 0)
    if admin_id:
        allowed.add(admin_id)
    return user_id in allowed


def _extract_pairs(raw: str) -> Mapping[str, str]:
    items: dict[str, str] = {}
    if not raw:
        return items
    for token in shlex.split(raw):
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key in attribution.UTM_KEYS and value:
            items[key] = value
    if items:
        return items
    return attribution.parse_utm_payload(raw)


@router.message(Command("link_builder"))
async def link_builder(message: Message, command: CommandObject) -> None:
    user_id = getattr(message.from_user, "id", None)
    if not _is_admin(user_id):
        return

    args = (command.args or "").strip() if command else ""
    params = attribution.normalize_utm(_extract_pairs(args))
    if not params:
        await message.answer(
            "Использование: /link_builder utm_source=tiktok utm_medium=shorts "
            "[utm_campaign=energy] [utm_content=vid01]"
        )
        return

    raw_payload, encoded_payload = attribution.build_start_payload(params)

    try:
        me = await message.bot.get_me()
        username = getattr(me, "username", None) or ""
    except Exception:
        username = ""

    if username:
        deeplink = f"https://t.me/{username}?start={encoded_payload}" if encoded_payload else f"https://t.me/{username}"
    else:
        deeplink = (
            f"https://t.me/<bot>?start={encoded_payload}" if encoded_payload else "https://t.me/<bot>"
        )

    bullets = "\n".join(f"• {key}: {params.get(key, '—')}" for key in attribution.UTM_KEYS)

    await message.answer(
        "🔗 Deeplink сконструирован:\n"
        f"{deeplink}\n\n"
        f"Payload: <code>{raw_payload}</code>\n"
        f"UTM:\n{bullets}"
    )


@router.message(Command("growth_report"))
async def growth_report(message: Message) -> None:
    user_id = getattr(message.from_user, "id", None)
    if not _is_admin(user_id):
        return

    async with compat_session(session_scope) as session:
        metrics = await attribution.collect_funnel_metrics(session)

    if not metrics:
        await message.answer("Данных по UTM ещё нет.")
        return

    limit = 10
    ordered = attribution.sort_metrics(metrics, limit=limit)
    total = attribution.summarize(metrics)
    remaining = max(0, len(metrics) - len(ordered))

    lines = ["📈 Growth-отчёт по UTM"]
    for key, stats in ordered:
        label = attribution.format_utm_label(key)
        lines.append(
            "\n".join(
                [
                    f"<b>{label}</b>",
                    f"Регистрации: {stats.registrations}",
                    f"Квизы: {stats.quiz_starts} (CTR: {stats.quiz_ctr:.1f}%)",
                    f"Рекомендации: {stats.recommendations} (CR к рекомендациям: {stats.recommendation_rate:.1f}%)",
                    f"Подписки: {stats.premium_buys} (CR: {stats.premium_cr:.1f}%)",
                ]
            )
        )

    if remaining:
        lines.append(f"\n…ещё {remaining} UTM c меньшим трафиком")

    lines.append(
        "\n".join(
            [
                "",
                "<b>Итого</b>",
                f"Регистрации: {total.registrations} · Квизы: {total.quiz_starts}",
                f"Рекомендации: {total.recommendations} · Подписки: {total.premium_buys}",
                f"CTR: {total.quiz_ctr:.1f}% · CR: {total.premium_cr:.1f}%",
            ]
        )
    )

    await message.answer("\n\n".join(lines))
