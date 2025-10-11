"""Generic FSM-powered quiz engine backed by YAML definitions."""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Sequence

import yaml
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.content.overrides import load_quiz_override
from app.content.overrides.quiz_merge import apply_quiz_override
from app.db.session import compat_session, session_scope
from app.feature_flags import feature_flags
from app.reco.ai_reasoner import ai_tip_for_quiz
from app.repo import events as events_repo
from app.storage import commit_safely, touch_throttle

if TYPE_CHECKING:  # pragma: no cover - import only for typing
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(__file__).resolve().parent / "data"
IMAGE_ROOT = PROJECT_ROOT / "app" / "static" / "images" / "quiz"

QUIZ_CALLBACK_PREFIX = "quiz"
QUIZ_NAV_ACTIONS: set[str] = {"next", "prev", "finish", "home"}
QUIZ_TIMEOUT_SECONDS = 15 * 60
QUIZ_GUARD_COOLDOWN = 8.0
OPTION_KEY_PATTERN = re.compile(r"^[a-z0-9_-]+$")
CALLBACK_RE = re.compile(
    r"^quiz:(?P<name>[a-z0-9_-]+):"
    r"(?:(?:q:(?P<qid>[a-zA-Z0-9_-]+):ans:(?P<akey>[a-z0-9_-]+))|"
    r"nav:(?P<action>next|prev|finish|home))$"
)

logger = logging.getLogger(__name__)

DEFAULT_REMOTE_BASE = (
    "https://raw.githubusercontent.com/go2telegram/media/1312d74492d26a8de5b8a65af38293fe6bf8ccc5/media/quizzes"
)

_quiz_mode = os.getenv("QUIZ_IMAGE_MODE", "remote").strip().lower()
QUIZ_IMAGE_MODE = _quiz_mode if _quiz_mode in {"remote", "local"} else "remote"
QUIZ_REMOTE_BASE = os.getenv("QUIZ_IMG_BASE", DEFAULT_REMOTE_BASE).rstrip("/")


class QuizSession(StatesGroup):
    """Aiogram FSM state for an active quiz."""

    # Dynamic states will be created per question (Q1..Qn) via :func:`_question_state`.
    pass


@dataclass
class QuizOption:
    key: str
    text: str
    score: int
    tags: list[str]


@dataclass
class QuizQuestion:
    id: str
    text: str
    options: list[QuizOption]
    image: str | None = None


@dataclass
class QuizThreshold:
    min: int
    max: int
    label: str
    advice: str
    tags: list[str]

    def includes(self, score: int) -> bool:
        return self.min <= score <= self.max


@dataclass
class QuizDefinition:
    name: str
    title: str
    questions: list[QuizQuestion]
    thresholds: list[QuizThreshold]
    cover: str | None = None

    def pick_threshold(self, score: int) -> QuizThreshold:
        for threshold in self.thresholds:
            if threshold.includes(score):
                return threshold
        # Fallback to the highest threshold if score goes beyond defined max.
        return self.thresholds[-1]


@dataclass
class QuizResultContext:
    total_score: int
    chosen_options: dict[str, QuizOption]
    collected_tags: list[str]
    threshold: QuizThreshold
    origin: CallbackQuery | None = None


@dataclass
class QuizHooks:
    """Optional lifecycle hooks to customize quiz behaviour."""

    on_finish: Callable[[int, QuizDefinition, QuizResultContext], Awaitable[bool]] | None = None


@dataclass(frozen=True)
class QuizCallbackPayload:
    name: str
    kind: Literal["answer", "nav"]
    question_id: str | None = None
    answer_key: str | None = None
    action: str | None = None


QUIZ_HOOKS: dict[str, QuizHooks] = {}


def register_quiz_hooks(name: str, hooks: QuizHooks) -> None:
    """Register custom hooks for a quiz definition."""

    QUIZ_HOOKS[name] = hooks


def parse_callback_data(data: str | None) -> QuizCallbackPayload | None:
    if not data:
        return None

    match = CALLBACK_RE.fullmatch(data)
    if not match:
        return None

    name = match.group("name")
    action = match.group("action")
    if action:
        return QuizCallbackPayload(name=name, kind="nav", action=action)

    question_id = match.group("qid")
    answer_key = match.group("akey")
    if not question_id or not answer_key:
        return None
    return QuizCallbackPayload(
        name=name,
        kind="answer",
        question_id=question_id,
        answer_key=answer_key,
    )


def build_answer_callback_data(name: str, question_id: str, option_key: str) -> str:
    if not OPTION_KEY_PATTERN.fullmatch(option_key):
        raise ValueError(f"Invalid option key {option_key!r}")
    return f"{QUIZ_CALLBACK_PREFIX}:{name}:q:{question_id}:ans:{option_key}"


def build_nav_callback_data(name: str, action: str) -> str:
    if action not in QUIZ_NAV_ACTIONS:
        raise ValueError(f"Unsupported navigation action: {action}")
    return f"{QUIZ_CALLBACK_PREFIX}:{name}:nav:{action}"


@lru_cache(maxsize=32)
def load_quiz(name: str) -> QuizDefinition:
    """Load a quiz definition from YAML."""

    path = DATA_ROOT / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Quiz definition not found: {name}")

    with path.open(encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)

    try:
        override = load_quiz_override(name)
    except Exception:
        logger.exception("Failed to load override for quiz %s", name)
        override = {}

    if override:
        try:
            raw = apply_quiz_override(raw, override)
        except Exception:
            logger.exception("Failed to apply override for quiz %s", name)

    title = str(raw.get("title", name)).strip()
    cover = raw.get("cover")
    questions = [_parse_question(q) for q in raw.get("questions", [])]
    thresholds = [_parse_threshold(t) for t in raw.get("result", {}).get("thresholds", [])]

    if len(questions) < 5:
        raise ValueError(f"Quiz {name} must contain at least five questions")
    if not thresholds:
        raise ValueError(f"Quiz {name} must define result thresholds")
    _validate_thresholds(name, thresholds)

    return QuizDefinition(
        name=name,
        title=title,
        questions=questions,
        thresholds=thresholds,
        cover=cover,
    )


def list_quizzes() -> list[QuizDefinition]:
    """Return available quizzes sorted by title."""

    definitions: list[QuizDefinition] = []
    for yaml_path in sorted(DATA_ROOT.glob("*.yaml")):
        definitions.append(load_quiz(yaml_path.stem))
    definitions.sort(key=lambda q: q.title.lower())
    return definitions


def _now() -> float:
    return time.time()


async def start_quiz(entry: CallbackQuery | Message, state: FSMContext, name: str) -> None:
    """Initialize quiz state and send the first question."""

    definition = load_quiz(name)

    message = _entry_message(entry)
    if message is None:
        return

    user_id = getattr(getattr(entry, "from_user", None), "id", None)
    if feature_flags.is_enabled("FF_QUIZ_GUARD", user_id=user_id) and user_id:
        remaining = touch_throttle(int(user_id), f"quiz:start:{name}", QUIZ_GUARD_COOLDOWN)
        if remaining > 0:
            warning = "Тест уже запущен. Давай завершим текущий и попробуем ещё раз чуть позже."
            if isinstance(entry, CallbackQuery):
                with suppress(Exception):
                    await entry.answer("Тест уже выполняется", show_alert=False)
            await message.answer(warning)
            return

    if hasattr(entry, "message") and hasattr(entry, "answer"):
        with suppress(Exception):
            await entry.answer()

    await state.clear()
    await state.update_data(quiz=name)

    await state.set_state(_question_state(0))

    await _send_cover(message, definition)
    question_message = await _send_question(message, definition, 0)

    await _record_question_state(
        state,
        definition=definition,
        index=0,
        message=question_message,
        score=0,
        tags=[],
        answers={},
    )

    if hasattr(entry, "message"):
        message_to_delete = getattr(entry, "message", None)
        if message_to_delete is not None:
            with suppress(Exception):
                await message_to_delete.delete()

    if user_id:
        try:
            async with compat_session(session_scope) as session:
                await events_repo.log(session, int(user_id), "quiz_start", {"quiz": name})
                await commit_safely(session)
        except Exception:  # pragma: no cover - logging best-effort
            logger.warning("quiz_start event logging failed", exc_info=True)


async def answer_callback(
    call: CallbackQuery,
    state: FSMContext,
    payload: QuizCallbackPayload | None = None,
) -> None:
    """Handle answer button presses for quiz questions."""

    payload = payload or parse_callback_data(call.data)
    if not payload or payload.kind != "answer":
        return

    message = call.message
    if message is None:
        await call.answer()
        return

    data = await state.get_data()
    quiz_name = payload.name
    if data.get("quiz") != quiz_name:
        await call.answer()
        return

    try:
        definition = load_quiz(quiz_name)
    except FileNotFoundError:
        await call.answer("Тест недоступен", show_alert=True)
        return

    questions = definition.questions
    current_index = int(data.get("index", 0))
    if not (0 <= current_index < len(questions)):
        await call.answer()
        return

    expected_state = f"{QuizSession.__name__}:Q{current_index + 1}"
    current_state = await state.get_state()
    if not current_state or not current_state.endswith(expected_state):
        await call.answer()
        return

    current_question = questions[current_index]
    if payload.question_id and current_question.id != payload.question_id:
        await call.answer()
        return

    stored_message_id = data.get("message_id")
    if stored_message_id and stored_message_id != getattr(message, "message_id", None):
        await call.answer()
        return

    asked_at_raw = data.get("asked_at")
    if asked_at_raw and _now() - float(asked_at_raw) > QUIZ_TIMEOUT_SECONDS:
        await _handle_step_timeout(call, state, definition)
        return

    option = next(
        (candidate for candidate in current_question.options if candidate.key == payload.answer_key),
        None,
    )
    if option is None:
        await call.answer()
        return

    total_score = int(data.get("score", 0)) + option.score
    tags: list[str] = list(data.get("tags", []))
    tags.extend(option.tags)
    tags = _unique(tags)
    answers: dict[str, str] = dict(data.get("answers", {}))
    answers[current_question.id] = option.key

    next_index = current_index + 1

    await call.answer()

    if next_index >= len(questions):
        threshold = definition.pick_threshold(total_score)
        chosen_options = _materialize_answers(definition, answers)
        result_context = QuizResultContext(
            total_score=total_score,
            chosen_options=chosen_options,
            collected_tags=tags,
            threshold=threshold,
            origin=call,
        )

        handled = False
        hooks = QUIZ_HOOKS.get(quiz_name)
        if hooks and hooks.on_finish:
            user_id = call.from_user.id if call.from_user else 0
            handled = await hooks.on_finish(user_id, definition, result_context)

        tip: str | None = None
        if message:
            tip_tags = result_context.collected_tags or result_context.threshold.tags
            tip = await ai_tip_for_quiz(quiz_name, tip_tags)

        if not handled:
            await _send_default_result(call, definition, result_context, tip=tip)
        elif message and tip:
            tags_line = ", ".join(result_context.threshold.tags) if result_context.threshold.tags else "—"
            tip_lines = [
                f"💡 AI совет: {tip}",
                "",
                f"score: {result_context.total_score}",
                f"label: {result_context.threshold.label}",
                f"advice: {result_context.threshold.advice}",
                f"tags: {tags_line}",
            ]
            await message.answer("\n".join(tip_lines))

        await state.clear()
        with suppress(Exception):
            await message.delete()
        return

    next_message: Message | None = None
    if message:
        next_message = await _send_question(message, definition, next_index)
        with suppress(Exception):
            await message.delete()

    await _record_question_state(
        state,
        definition=definition,
        index=next_index,
        message=next_message,
        score=total_score,
        tags=tags,
        answers=answers,
    )


async def back_callback(
    call: CallbackQuery,
    state: FSMContext,
    payload: QuizCallbackPayload | None = None,
) -> None:
    """Handle "back" navigation within an active quiz."""

    payload = payload or parse_callback_data(call.data)
    if not payload or payload.kind != "nav" or payload.action != "prev":
        return

    message = call.message
    if message is None:
        await call.answer()
        return

    data = await state.get_data()
    quiz_name = payload.name
    if data.get("quiz") != quiz_name:
        await call.answer()
        return

    current_index = int(data.get("index", 0))
    if current_index <= 0:
        await call.answer()
        return

    try:
        definition = load_quiz(quiz_name)
    except FileNotFoundError:
        await call.answer("Тест недоступен", show_alert=True)
        return

    stored_message_id = data.get("message_id")
    if stored_message_id and stored_message_id != getattr(message, "message_id", None):
        await call.answer()
        return

    asked_at_raw = data.get("asked_at")
    if asked_at_raw and _now() - float(asked_at_raw) > QUIZ_TIMEOUT_SECONDS:
        await _handle_step_timeout(call, state, definition)
        return

    answers: dict[str, str] = dict(data.get("answers", {}))
    prev_index = current_index - 1
    if not (0 <= prev_index < len(definition.questions)):
        await call.answer()
        return

    previous_question = definition.questions[prev_index]
    answers.pop(previous_question.id, None)
    score, tags = _recalculate_progress(definition, answers)

    prev_message = await _send_question(message, definition, prev_index)
    with suppress(Exception):
        await message.delete()

    await _record_question_state(
        state,
        definition=definition,
        index=prev_index,
        message=prev_message,
        score=score,
        tags=tags,
        answers=answers,
    )

    await call.answer()


async def navigation_callback(
    call: CallbackQuery,
    state: FSMContext,
    payload: QuizCallbackPayload | None = None,
) -> None:
    payload = payload or parse_callback_data(call.data)
    if not payload or payload.kind != "nav" or not payload.action:
        return

    action = payload.action
    if action == "prev":
        await back_callback(call, state, payload)
    elif action == "next":
        await _handle_nav_next(call, state, payload.name)
    elif action == "home":
        await _handle_nav_home(call, state, payload.name)
    elif action == "finish":
        await _handle_nav_finish(call, state, payload.name)


def _parse_question(raw: dict[str, Any]) -> QuizQuestion:
    qid = str(raw.get("id") or raw.get("name"))
    if not qid:
        raise ValueError("Question must define an 'id'")

    text = str(raw.get("text", ""))
    image = raw.get("image")
    options = [_parse_option(opt) for opt in raw.get("options", [])]
    if not options:
        raise ValueError(f"Question {qid} must define answer options")

    seen_keys: set[str] = set()
    for option in options:
        if not OPTION_KEY_PATTERN.fullmatch(option.key):
            raise ValueError(f"Question {qid} option key must match [a-z0-9_-]: {option.key!r}")
        if option.key in seen_keys:
            raise ValueError(f"Question {qid} has duplicate option key: {option.key}")
        seen_keys.add(option.key)

    return QuizQuestion(id=qid, text=text, options=options, image=image)


def _parse_option(raw: dict[str, Any]) -> QuizOption:
    key = str(raw.get("key"))
    if not key:
        raise ValueError("Option must define a 'key'")

    text = str(raw.get("text", ""))
    score = int(raw.get("score", 0))
    tags = [str(tag) for tag in raw.get("tags", [])]
    return QuizOption(key=key, text=text, score=score, tags=tags)


def _parse_threshold(raw: dict[str, Any]) -> QuizThreshold:
    min_score = int(raw.get("min", 0))
    max_score = int(raw.get("max", min_score))
    label = str(raw.get("label", ""))
    advice = str(raw.get("advice", ""))
    tags = [str(tag) for tag in raw.get("tags", [])]
    return QuizThreshold(min=min_score, max=max_score, label=label, advice=advice, tags=tags)


def _validate_thresholds(name: str, thresholds: list[QuizThreshold]) -> None:
    prev_max: int | None = None
    for threshold in thresholds:
        if threshold.min > threshold.max:
            raise ValueError(f"Quiz {name} has invalid threshold range: {threshold.min}>{threshold.max}")
        if prev_max is not None and threshold.min > prev_max + 1:
            logger.warning(
                "Quiz %s thresholds have gaps between %s and %s",
                name,
                prev_max,
                threshold.min,
            )
        prev_max = max(prev_max or threshold.max, threshold.max)


def _entry_message(entry: CallbackQuery | Message) -> Message | None:
    if isinstance(entry, CallbackQuery):
        return entry.message
    if hasattr(entry, "message"):
        candidate = entry.message
        if candidate is not None:
            return candidate
    return entry


async def _send_cover(message: Message, definition: QuizDefinition) -> None:
    if not definition.cover:
        return

    caption = f"{definition.title}\n\nОтветь на вопросы, чтобы получить результат.".strip()
    photo_message = await _send_photo(message, definition.cover, caption)
    if photo_message:
        return
    await message.answer(caption)


async def _send_question(message: Message, definition: QuizDefinition, index: int) -> Message | None:
    total = len(definition.questions)
    question = definition.questions[index]

    header = definition.title if index == 0 else ""
    prefix = f"Вопрос {index + 1}/{total}:\n"
    text = f"{header}\n\n{prefix}{question.text}" if header else f"{prefix}{question.text}"

    kb = InlineKeyboardBuilder()
    for option in question.options:
        kb.button(
            text=option.text,
            callback_data=build_answer_callback_data(definition.name, question.id, option.key),
        )
    if index > 0:
        kb.button(
            text="⬅️ Назад",
            callback_data=build_nav_callback_data(definition.name, "prev"),
        )
    kb.button(
        text="🏠 Домой",
        callback_data=build_nav_callback_data(definition.name, "home"),
    )
    kb.adjust(1)

    markup = kb.as_markup()

    photo_message = await _send_photo(
        message,
        question.image,
        text,
        reply_markup=markup,
    )
    if photo_message:
        return photo_message
    return await message.answer(text, reply_markup=markup)


async def _record_question_state(
    state: FSMContext,
    *,
    definition: QuizDefinition,
    index: int,
    message: Message | None,
    score: int,
    tags: Sequence[str],
    answers: dict[str, str],
) -> None:
    question = definition.questions[index]
    await state.update_data(
        index=index,
        score=score,
        tags=list(tags),
        answers=answers,
        question_id=question.id,
        message_id=getattr(message, "message_id", None),
        asked_at=_now(),
    )
    await state.set_state(_question_state(index))


async def _handle_step_timeout(call: CallbackQuery, state: FSMContext, definition: QuizDefinition) -> None:
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔁 Начать заново",
        callback_data=build_nav_callback_data(definition.name, "next"),
    )
    builder.button(
        text="🏠 Домой",
        callback_data=build_nav_callback_data(definition.name, "home"),
    )
    builder.adjust(1)

    message = call.message
    if message:
        try:
            await message.answer(
                "⏳ Пауза была слишком долгой. Начнём тест заново?",
                reply_markup=builder.as_markup(),
            )
        except Exception:
            logger.warning("Failed to send quiz timeout prompt", exc_info=True)
        with suppress(Exception):
            await message.delete()

    with suppress(Exception):
        await call.answer("Сессия теста устарела", show_alert=True)


async def _handle_nav_next(call: CallbackQuery, state: FSMContext, quiz_name: str) -> None:
    try:
        await start_quiz(call, state, quiz_name)
    except FileNotFoundError:
        with suppress(Exception):
            await call.answer("Тест недоступен", show_alert=True)


async def _handle_nav_home(call: CallbackQuery, state: FSMContext, quiz_name: str) -> None:
    await state.clear()

    message = call.message
    if message:
        try:
            from app.keyboards import kb_main

            text = "🏠 Возвращаемся в главное меню."
            markup = kb_main(user_id=getattr(call.from_user, "id", None))
        except Exception:
            logger.warning("Failed to build main keyboard on quiz exit", exc_info=True)
            text = "🏠 Возвращаемся домой. Нажми /start, чтобы продолжить."
            markup = None

        try:
            await message.answer(text, reply_markup=markup)
        except Exception:
            logger.warning("Failed to send quiz home message", exc_info=True)
        with suppress(Exception):
            await message.delete()

    with suppress(Exception):
        await call.answer()


async def _handle_nav_finish(call: CallbackQuery, state: FSMContext, quiz_name: str) -> None:
    await state.clear()
    with suppress(Exception):
        await call.answer("Тест завершён", show_alert=False)


async def _send_default_result(
    call: CallbackQuery,
    definition: QuizDefinition,
    result: QuizResultContext,
    tip: str | None = None,
) -> None:
    message = call.message
    if not message:
        return

    threshold_tags = result.threshold.tags
    tag_line = ", ".join(threshold_tags) if threshold_tags else "—"
    text = (
        f"Тест «{definition.title}» завершён!\n\n"
        f"score: {result.total_score}\n"
        f"label: {result.threshold.label}\n"
        f"advice: {result.threshold.advice}\n"
        f"tags: {tag_line}"
    )
    if result.collected_tags:
        answers_line = ", ".join(result.collected_tags)
        text += f"\nanswers: {answers_line}"

    if tip:
        text = f"{text}\n\n💡 AI совет: {tip}"

    await message.answer(text)


async def _send_photo(
    message: Message,
    path_str: str | None,
    caption: str,
    *,
    reply_markup=None,
) -> Message | None:
    if not path_str:
        return None

    for source, candidate in _iter_photo_candidates(path_str):
        try:
            if source == "local":
                return await message.answer_photo(
                    photo=FSInputFile(str(candidate)),
                    caption=caption,
                    reply_markup=reply_markup,
                )

            if source == "remote":
                if feature_flags.is_enabled("FF_MEDIA_PROXY"):
                    from app.utils_media import fetch_image_as_file  # local import to avoid cycles

                    proxy = await fetch_image_as_file(str(candidate))
                    if proxy:
                        return await message.answer_photo(
                            photo=proxy,
                            caption=caption,
                            reply_markup=reply_markup,
                        )
                    logger.warning("Quiz remote proxy unavailable, using direct URL: %s", candidate)

                return await message.answer_photo(
                    photo=str(candidate),
                    caption=caption,
                    reply_markup=reply_markup,
                )
        except TelegramBadRequest as exc:
            logger.warning(
                "Failed to send quiz image %s via %s: %s",
                path_str,
                source,
                exc,
            )
        except Exception as exc:  # pragma: no cover - network/runtime failures
            logger.warning(
                "Unexpected error sending quiz image %s via %s: %s",
                path_str,
                source,
                exc,
            )

    logger.warning("Quiz image unavailable, using text fallback: %s", path_str)
    return None


def build_quiz_image_url(path: str) -> str:
    """Build a remote image URL for the provided quiz asset path."""

    normalized = str(path).strip()
    if not normalized:
        raise ValueError("Empty image path")
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return normalized

    relative = _normalize_relative_image_path(normalized)
    if not relative:
        raise ValueError(f"Cannot normalize quiz image path: {path}")

    base = QUIZ_REMOTE_BASE or DEFAULT_REMOTE_BASE
    if not base:
        raise ValueError("Remote quiz image base is not configured")

    return f"{base.rstrip('/')}/{relative.lstrip('/')}"


def _iter_photo_candidates(path_str: str) -> list[tuple[str, str | Path]]:
    candidates: list[tuple[str, str | Path]] = []
    remote = _build_remote_image_url(path_str)
    local = _resolve_local_image(path_str)

    if QUIZ_IMAGE_MODE == "remote":
        if remote:
            candidates.append(("remote", remote))
        if local:
            candidates.append(("local", local))
    else:
        if local:
            candidates.append(("local", local))
        if remote:
            candidates.append(("remote", remote))
    return candidates


def _build_remote_image_url(path_str: str | None) -> str | None:
    if not path_str:
        return None
    normalized = str(path_str).strip()
    if not normalized:
        return None
    try:
        return build_quiz_image_url(normalized)
    except ValueError:
        return None


def _resolve_local_image(path_str: str | None) -> Path | None:
    if not path_str:
        return None

    raw = Path(path_str)
    direct_candidates: list[Path] = []
    if raw.is_absolute():
        direct_candidates.append(raw)
    else:
        direct_candidates.append(PROJECT_ROOT / raw)
        if raw.parts[:4] == ("app", "static", "images", "quiz"):
            direct_candidates.append(PROJECT_ROOT / Path(*raw.parts))

    for candidate in direct_candidates:
        if candidate.exists():
            return candidate

    relative = _normalize_relative_image_path(path_str)
    if relative:
        local = IMAGE_ROOT / relative
        if local.exists():
            return local
        fallback = _flexible_image_lookup(relative)
        if fallback:
            return fallback
    return None


def _normalize_relative_image_path(path_str: str) -> str:
    candidate = Path(path_str)
    if candidate.is_absolute():
        with suppress(ValueError):
            return candidate.relative_to(IMAGE_ROOT).as_posix()
        with suppress(ValueError):
            return candidate.relative_to(PROJECT_ROOT).as_posix()
        return candidate.name

    parts = candidate.parts
    if len(parts) >= 4 and parts[:4] == ("app", "static", "images", "quiz"):
        candidate = Path(*parts[4:])

    return candidate.as_posix()


def _flexible_image_lookup(relative: str) -> Path | None:
    if not relative:
        return None

    path = Path(relative)
    parent = IMAGE_ROOT / path.parent if path.parent != Path(".") else IMAGE_ROOT
    search_name = path.stem if path.suffix else path.name

    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        candidate = parent / f"{search_name}{ext}"
        if candidate.exists():
            return candidate
    return None


def _materialize_answers(definition: QuizDefinition, answer_keys: dict[str, str]) -> dict[str, QuizOption]:
    mapping: dict[str, QuizOption] = {}
    for question in definition.questions:
        key = answer_keys.get(question.id)
        if not key:
            continue
        for option in question.options:
            if option.key == key:
                mapping[question.id] = option
                break
    return mapping


def _unique(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _question_state(index: int) -> State:
    return State(f"{QuizSession.__name__}:Q{index + 1}")


def _recalculate_progress(definition: QuizDefinition, answers: dict[str, str]) -> tuple[int, list[str]]:
    score = 0
    tags: list[str] = []
    for question in definition.questions:
        key = answers.get(question.id)
        if not key:
            continue
        for option in question.options:
            if option.key == key:
                score += option.score
                tags.extend(option.tags)
                break
    return score, _unique(tags)


__all__ = [
    "QuizCallbackPayload",
    "QuizDefinition",
    "QuizHooks",
    "QuizOption",
    "QuizQuestion",
    "QuizResultContext",
    "QuizSession",
    "QuizThreshold",
    "answer_callback",
    "back_callback",
    "build_answer_callback_data",
    "build_nav_callback_data",
    "build_quiz_image_url",
    "list_quizzes",
    "load_quiz",
    "navigation_callback",
    "parse_callback_data",
    "register_quiz_hooks",
    "start_quiz",
]
