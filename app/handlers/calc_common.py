"""Shared helpers for calculator flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from aiogram.types import CallbackQuery, Message

from app.db.session import compat_session, session_scope
from app.keyboards import kb_calc_result
from app.repo import events as events_repo
from app.storage import commit_safely


@dataclass(slots=True)
class CalcResult:
    calc: str
    title: str
    products: list[str | Mapping]
    headline: str | None
    bullets: Sequence[str] | None
    back_cb: str | None


class _ResultStore:
    def __init__(self) -> None:
        self._store: dict[int, dict[str, CalcResult]] = {}

    def put(self, user_id: int, result: CalcResult) -> None:
        user_map = self._store.setdefault(user_id, {})
        user_map[result.calc] = result

    def get(self, user_id: int, calc: str) -> CalcResult | None:
        user_map = self._store.get(user_id)
        if not user_map:
            return None
        return user_map.get(calc)

    def clear(self, user_id: int, calc: str | None = None) -> None:
        if calc is None:
            self._store.pop(user_id, None)
            return
        user_map = self._store.get(user_id)
        if not user_map:
            return
        user_map.pop(calc, None)
        if not user_map:
            self._store.pop(user_id, None)


_RESULTS = _ResultStore()


async def send_calc_summary(
    target: CallbackQuery | Message,
    *,
    calc: str,
    title: str,
    summary: Sequence[str],
    products: Iterable[str | Mapping],
    headline: str | None = None,
    bullets: Sequence[str] | None = None,
    back_cb: str | None = "calc:menu",
) -> None:
    """Send a concise calculator result with a CTA for recommendations."""

    user_id = target.from_user.id if target.from_user else None  # type: ignore[attr-defined]
    if isinstance(target, CallbackQuery):
        await target.answer()
        message = target.message
    else:
        message = target

    summary_lines = [f"<b>{title}</b>"]
    summary_lines.extend(summary)
    summary_lines.append("")
    summary_lines.append("Нажми «Персональные рекомендации», чтобы получить детальный план.")
    text = "\n".join(line for line in summary_lines if line)

    markup = kb_calc_result(calc, back_cb=back_cb)
    await message.answer(text, reply_markup=markup)

    if user_id is None:
        return

    stored = CalcResult(
        calc=calc,
        title=title,
        products=list(products),
        headline=headline,
        bullets=list(bullets) if bullets is not None else None,
        back_cb=back_cb,
    )
    _RESULTS.put(user_id, stored)


def get_calc_result(user_id: int, calc: str) -> CalcResult | None:
    return _RESULTS.get(user_id, calc)


async def log_calc_error(
    user_id: int | None,
    *,
    calc: str,
    step: str,
    reason: str,
    raw_input: str | None = None,
) -> None:
    if user_id is None:
        return

    payload: dict[str, str] = {"calc": calc, "step": step, "reason": reason}
    if raw_input:
        payload["input"] = raw_input[:120]

    async with compat_session(session_scope) as session:
        await events_repo.log(session, user_id, "calc_error", payload)
        await commit_safely(session)


__all__ = [
    "CalcResult",
    "get_calc_result",
    "log_calc_error",
    "send_calc_summary",
]
