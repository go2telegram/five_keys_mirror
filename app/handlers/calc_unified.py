"""Unified calculator handlers built on top of the core engine."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.calculators.engine import (
    CALCULATORS,
    CalculationContext,
    CalculatorDefinition,
    CalculationResult,
    ChoiceStep,
    InputStep,
    Step,
)
from app.db.session import compat_session, session_scope
from app.handlers.quiz_common import send_product_cards
from app.keyboards import kb_calc_result_actions
from app.repo import (
    calculator_results as calculator_results_repo,
    events as events_repo,
    users as users_repo,
)
from app.storage import SESSIONS, SessionData, commit_safely, set_last_plan

router = Router(name="calc_unified")

_FLOW_PREFIX = "calc:flow"
_COMMANDS = {
    "water": "calc_water",
    "kcal": "calc_kcal",
    "macros": "calc_macros",
    "bmi": "calc_bmi",
}


def _get_session(user_id: int) -> SessionData | None:
    try:
        session = SESSIONS[user_id]
    except KeyError:
        return None
    if session.get("calc_engine") != "core":
        return None
    return session


def _get_definition(slug: str) -> CalculatorDefinition | None:
    return CALCULATORS.get(slug)


def _ensure_session(user_id: int, slug: str) -> SessionData:
    payload = {"calc": slug, "calc_engine": "core", "step_index": 0, "data": {}}
    SESSIONS[user_id] = payload
    return SESSIONS[user_id]


def _step_keyboard(slug: str, step: Step, allow_back: bool) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    layout: list[int] = []

    if isinstance(step, ChoiceStep):
        for option in step.options:
            kb.button(
                text=option.label,
                callback_data=f"{_FLOW_PREFIX}:{slug}:opt:{step.key}:{option.key}",
            )
            layout.append(1)

    if allow_back:
        kb.button(text="⬅️ Назад", callback_data=f"{_FLOW_PREFIX}:{slug}:ctrl:back")
        layout.append(1)

    kb.button(text="🔁 Повторить", callback_data=f"{_FLOW_PREFIX}:{slug}:ctrl:repeat")
    layout.append(1)

    kb.button(text="🏠 Главное меню", callback_data="home:main")
    layout.append(1)

    if not layout:
        layout = [1]
    kb.adjust(*layout)
    return kb


async def _send_step(
    target: CallbackQuery | Message,
    definition: CalculatorDefinition,
    session: SessionData,
    *,
    replace: bool,
) -> None:
    index = int(session.get("step_index", 0))
    step = definition.steps[index]
    markup = _step_keyboard(definition.slug, step, allow_back=index > 0).as_markup()

    if isinstance(target, CallbackQuery):
        message = target.message
        if replace and message is not None:
            try:
                await message.edit_text(step.prompt, reply_markup=markup)
            except Exception:
                await message.answer(step.prompt, reply_markup=markup)
        else:
            if message is not None:
                await message.answer(step.prompt, reply_markup=markup)
    else:
        await target.answer(step.prompt, reply_markup=markup)


async def _finish(
    target: CallbackQuery | Message,
    definition: CalculatorDefinition,
    session: SessionData,
) -> None:
    data_raw = session.get("data", {})
    if isinstance(data_raw, SessionData):
        data = data_raw.to_dict()
    elif isinstance(data_raw, dict):
        data = dict(data_raw)
    else:
        data = {}

    user = target.from_user
    context = CalculationContext(data=data, user_id=user.id, username=getattr(user, "username", None))
    result: CalculationResult = definition.build_result(context)
    input_payload = dict(data)
    result_payload = dict(result.event_payload)

    async with compat_session(session_scope) as db:
        await users_repo.get_or_create_user(db, user.id, getattr(user, "username", None))
        await set_last_plan(db, user.id, dict(result.plan_payload))
        payload = dict(result_payload)
        payload.setdefault("calc", definition.slug)
        await events_repo.log(db, user.id, "calc_finish", payload)
        await calculator_results_repo.log_success(
            db,
            user.id,
            definition.slug,
            input_data=input_payload,
            result_data=result_payload,
            tags=result.tags,
        )
        await commit_safely(db)

    await send_product_cards(
        target,
        result.cards_title,
        result.cards,
        headline=result.headline,
        bullets=result.bullets,
        back_cb=result.back_cb,
        with_actions=result.with_actions,
        ctx=result.cards_ctx,
        reply_markup=kb_calc_result_actions(result.back_cb),
    )
    SESSIONS.pop(user.id, None)


async def _handle_input(message: Message, definition: CalculatorDefinition, session: SessionData) -> None:
    index = int(session.get("step_index", 0))
    step = definition.steps[index]
    if not isinstance(step, InputStep):
        return

    text = message.text or ""
    user = message.from_user
    user_id = getattr(user, "id", None)
    username = getattr(user, "username", None)

    try:
        value = step.parser(text)
    except ValueError:
        markup = _step_keyboard(definition.slug, step, allow_back=index > 0).as_markup()
        await message.answer(f"{step.error}\n\n{step.prompt}", reply_markup=markup)
        async with compat_session(session_scope) as db:
            if user_id is not None:
                await users_repo.get_or_create_user(db, user_id, username)
            await calculator_results_repo.log_error(
                db,
                user_id,
                definition.slug,
                step=step.key,
                raw_value=text,
                error="parse_error",
            )
            await commit_safely(db)
        return

    for validator in step.validators:
        error = validator(value)
        if error:
            markup = _step_keyboard(definition.slug, step, allow_back=index > 0).as_markup()
            await message.answer(f"{error}\n\n{step.prompt}", reply_markup=markup)
            async with compat_session(session_scope) as db:
                if user_id is not None:
                    await users_repo.get_or_create_user(db, user_id, username)
                await calculator_results_repo.log_error(
                    db,
                    user_id,
                    definition.slug,
                    step=step.key,
                    raw_value=text,
                    error=error,
                )
                await commit_safely(db)
            return

    data = session.setdefault("data", {})
    if isinstance(data, SessionData):
        data = session["data"]
    data[step.key] = value
    session["step_index"] = index + 1

    if session["step_index"] >= len(definition.steps):
        await _finish(message, definition, session)
    else:
        await _send_step(message, definition, session, replace=False)


async def _handle_choice(
    callback: CallbackQuery,
    definition: CalculatorDefinition,
    session: SessionData,
    *,
    step_key: str,
    option_key: str,
) -> None:
    index = int(session.get("step_index", 0))
    step = definition.steps[index]
    if not isinstance(step, ChoiceStep) or step.key != step_key:
        await callback.answer()
        return

    option = step.option_by_key(option_key)
    if option is None:
        await callback.answer()
        return

    data = session.setdefault("data", {})
    if isinstance(data, SessionData):
        data = session["data"]
    data[step.key] = option.value
    session["step_index"] = index + 1

    if session["step_index"] >= len(definition.steps):
        await callback.answer()
        await _finish(callback, definition, session)
    else:
        await callback.answer()
        await _send_step(callback, definition, session, replace=True)


async def _handle_back(callback: CallbackQuery, definition: CalculatorDefinition, session: SessionData) -> None:
    index = int(session.get("step_index", 0))
    if index <= 0:
        await callback.answer()
        return

    session["step_index"] = index - 1
    new_index = int(session.get("step_index", 0))
    step = definition.steps[new_index]
    data = session.get("data")
    if isinstance(data, SessionData):
        data = session["data"]
    if isinstance(data, dict):
        data.pop(step.key, None)

    await callback.answer()
    await _send_step(callback, definition, session, replace=True)


async def _handle_repeat(callback: CallbackQuery, definition: CalculatorDefinition, session: SessionData) -> None:
    await callback.answer()
    await _send_step(callback, definition, session, replace=True)


async def _start_flow(target: CallbackQuery | Message, slug: str) -> None:
    definition = _get_definition(slug)
    if definition is None:
        if isinstance(target, CallbackQuery):
            await target.answer()
        return

    user_id = target.from_user.id
    session = _ensure_session(user_id, slug)

    if isinstance(target, CallbackQuery):
        await target.answer()
        await _send_step(target, definition, session, replace=True)
    else:
        await _send_step(target, definition, session, replace=False)


# Command entry points -------------------------------------------------------


for slug, command in _COMMANDS.items():
    router.message.register(lambda message, s=slug: _start_flow(message, s), Command(command))


# Callback entry points ------------------------------------------------------


@router.callback_query(F.data.in_({f"calc:{slug}" for slug in _COMMANDS}))
async def _entry_callback(callback: CallbackQuery) -> None:
    slug = callback.data.split(":")[-1]
    await _start_flow(callback, slug)


@router.message(F.text)
async def _dispatch_message(message: Message) -> None:
    session = _get_session(message.from_user.id)
    if session is None:
        return

    slug = session.get("calc")
    definition = _get_definition(slug)
    if not definition:
        return

    await _handle_input(message, definition, session)


@router.callback_query(F.data.startswith(_FLOW_PREFIX))
async def _dispatch_callback(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer()
        return

    _, _, slug, action, *rest = parts
    session = _get_session(callback.from_user.id)
    if session is None or session.get("calc") != slug:
        await callback.answer()
        return

    definition = _get_definition(slug)
    if definition is None:
        await callback.answer()
        return

    if action == "ctrl" and rest:
        command = rest[0]
        if command == "back":
            await _handle_back(callback, definition, session)
        elif command == "repeat":
            await _handle_repeat(callback, definition, session)
        else:
            await callback.answer()
        return

    if action == "opt" and len(rest) == 2:
        step_key, option_key = rest
        await _handle_choice(callback, definition, session, step_key=step_key, option_key=option_key)
        return

    await callback.answer()
