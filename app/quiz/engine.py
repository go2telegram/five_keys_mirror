"""Generic FSM-powered quiz engine backed by YAML definitions."""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

import yaml
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(__file__).resolve().parent / "data"
IMAGE_ROOT = PROJECT_ROOT / "app" / "static" / "images" / "quiz"

ANSWER_PREFIX = "tests:answer"
BACK_PREFIX = "tests:back"

logger = logging.getLogger(__name__)

DEFAULT_REMOTE_BASE = (
    "https://raw.githubusercontent.com/go2telegram/media/1312d74492d26a8de5b8a65af38293fe6bf8ccc5/media/quizzes"
)

_quiz_mode = os.getenv("QUIZ_IMAGE_MODE", "remote").strip().lower()
QUIZ_IMAGE_MODE = _quiz_mode if _quiz_mode in {"remote", "local"} else "remote"
QUIZ_REMOTE_BASE = os.getenv("QUIZ_IMG_BASE", DEFAULT_REMOTE_BASE).rstrip("/")


class QuizSession(StatesGroup):
    """Aiogram FSM states for quiz questions."""


for _idx in range(1, 51):  # Support up to 50 questions per quiz.
    setattr(QuizSession, f"Q{_idx}", State())
del _idx


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
    source: CallbackQuery | Message | None = None


@dataclass
class QuizHooks:
    """Optional lifecycle hooks to customize quiz behaviour."""

    on_finish: (
        Callable[[int, QuizDefinition, QuizResultContext], Awaitable[None]] | None
    ) = None


QUIZ_HOOKS: dict[str, QuizHooks] = {}


def register_quiz_hooks(name: str, hooks: QuizHooks) -> None:
    """Register custom hooks for a quiz definition."""

    QUIZ_HOOKS[name] = hooks


@lru_cache(maxsize=32)
def load_quiz(name: str) -> QuizDefinition:
    """Load a quiz definition from YAML."""

    path = DATA_ROOT / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Quiz definition not found: {name}")

    with path.open(encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)

    title = str(raw.get("title", name)).strip()
    cover = raw.get("cover")
    questions = [_parse_question(q) for q in raw.get("questions", [])]
    thresholds = [_parse_threshold(t) for t in raw.get("result", {}).get("thresholds", [])]

    if len(questions) < 5:
        raise ValueError(f"Quiz {name} must contain at least five questions")
    if not thresholds:
        raise ValueError(f"Quiz {name} must define result thresholds")

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


async def start_quiz(entry: CallbackQuery | Message, state: FSMContext, name: str) -> None:
    """Initialize quiz state and send the first question."""

    definition = load_quiz(name)

    message = _entry_message(entry)
    if message is None:
        return

    if isinstance(entry, CallbackQuery):
        await entry.answer()

    await state.clear()
    await state.set_state(_question_state(0))
    await state.update_data(
        quiz=name,
        index=0,
        score=0,
        tags=[],
        answers={},
    )

    await _send_cover(message, definition)
    await _send_question(message, definition, 0)

    if isinstance(entry, CallbackQuery):
        with suppress(Exception):
            await entry.message.delete()


async def answer_callback(call: CallbackQuery, state: FSMContext) -> None:
    """Handle answer button presses for quiz questions."""

    if not call.data:
        return

    parts = call.data.split(":")
    if len(parts) < 3 or parts[0] != "tests":
        return
    action = parts[1]

    if action == "answer" and len(parts) == 5:
        await _handle_answer(call, state, parts[2:])
    elif action == "back" and len(parts) == 4:
        await _handle_back(call, state, parts[2:])


def _parse_question(raw: dict[str, Any]) -> QuizQuestion:
    qid = str(raw.get("id") or raw.get("name"))
    if not qid:
        raise ValueError("Question must define an 'id'")

    text = str(raw.get("text", ""))
    image = raw.get("image")
    options = [_parse_option(opt) for opt in raw.get("options", [])]
    if not options:
        raise ValueError(f"Question {qid} must define answer options")

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
    if "min" not in raw or "max" not in raw:
        raise ValueError("Each threshold must define 'min' and 'max'")

    min_score = int(raw.get("min", 0))
    max_score = int(raw.get("max", min_score))
    if max_score < min_score:
        raise ValueError("Threshold 'max' cannot be less than 'min'")
    label = str(raw.get("label", ""))
    advice = str(raw.get("advice", ""))
    tags = [str(tag) for tag in raw.get("tags", [])]
    return QuizThreshold(min=min_score, max=max_score, label=label, advice=advice, tags=tags)


def _entry_message(entry: CallbackQuery | Message) -> Message | None:
    if isinstance(entry, CallbackQuery):
        return entry.message
    return entry


async def _send_cover(message: Message, definition: QuizDefinition) -> None:
    if not definition.cover:
        return

    caption = f"{definition.title}\n\nОтветь на вопросы, чтобы получить результат.".strip()
    if await _send_photo(message, definition.cover, caption):
        return
    await message.answer(caption)


async def _send_question(message: Message, definition: QuizDefinition, index: int) -> None:
    total = len(definition.questions)
    question = definition.questions[index]

    header = definition.title if index == 0 else ""
    prefix = f"Вопрос {index + 1}/{total}:\n"
    text = f"{header}\n\n{prefix}{question.text}" if header else f"{prefix}{question.text}"

    kb = InlineKeyboardBuilder()
    for opt_idx, option in enumerate(question.options):
        kb.button(
            text=option.text,
            callback_data=f"{ANSWER_PREFIX}:{definition.name}:{index}:{opt_idx}",
        )
    if index > 0:
        kb.button(
            text="◀️ Назад",
            callback_data=f"{BACK_PREFIX}:{definition.name}:{index}",
        )
    kb.button(text="🏠 Домой", callback_data="home:main")
    kb.adjust(1)

    if await _send_photo(
        message,
        question.image,
        text,
        reply_markup=kb.as_markup(),
    ):
        return
    await message.answer(text, reply_markup=kb.as_markup())


async def _send_default_result(
    call: CallbackQuery, definition: QuizDefinition, result: QuizResultContext
) -> None:
    message = call.message
    if not message:
        return

    tags = result.threshold.tags
    tag_line = "\n\n" + " ".join(f"#{tag}" for tag in tags) if tags else ""
    text = (
        f"Тест «{definition.title}» завершён!\n\n"
        f"<b>{result.threshold.label}</b>\n{result.threshold.advice}{tag_line}"
    )
    await message.answer(text)


async def _send_photo(
    message: Message,
    path_str: str | None,
    caption: str,
    *,
    reply_markup=None,
) -> bool:
    if not path_str:
        logger.warning("Quiz image missing, falling back to text message")
        return False

    for source, candidate in _iter_photo_candidates(path_str):
        try:
            if source == "local":
                await message.answer_photo(
                    photo=FSInputFile(str(candidate)),
                    caption=caption,
                    reply_markup=reply_markup,
                )
            else:
                await message.answer_photo(
                    photo=candidate,
                    caption=caption,
                    reply_markup=reply_markup,
                )
            return True
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
    return False


async def _handle_answer(
    call: CallbackQuery, state: FSMContext, payload: Sequence[str]
) -> None:
    quiz_name, question_idx_raw, option_idx_raw = payload

    try:
        question_idx = int(question_idx_raw)
        option_idx = int(option_idx_raw)
    except ValueError:
        await call.answer()
        return

    data = await state.get_data()
    if data.get("quiz") != quiz_name:
        await call.answer()
        return

    try:
        definition = load_quiz(quiz_name)
    except FileNotFoundError:
        await call.answer("Тест недоступен")
        return

    questions = definition.questions
    if not (0 <= question_idx < len(questions)):
        await call.answer()
        return

    question = questions[question_idx]
    if not (0 <= option_idx < len(question.options)):
        await call.answer()
        return

    answer_keys: dict[str, str] = dict(data.get("answers", {}))
    answer_keys[question.id] = question.options[option_idx].key

    total_score, tags, chosen_options = _evaluate_answers(definition, answer_keys)
    next_index = question_idx + 1

    await call.answer()

    if next_index >= len(questions):
        threshold = definition.pick_threshold(total_score)
        result_context = QuizResultContext(
            total_score=total_score,
            chosen_options=chosen_options,
            collected_tags=tags,
            threshold=threshold,
            source=call,
        )

        hooks = QUIZ_HOOKS.get(quiz_name)
        if hooks and hooks.on_finish and call.from_user:
            await hooks.on_finish(call.from_user.id, definition, result_context)

        await _send_default_result(call, definition, result_context)
        await state.clear()
        with suppress(Exception):
            if call.message:
                await call.message.delete()
        return

    await state.update_data(
        answers=answer_keys,
        score=total_score,
        tags=tags,
        index=next_index,
    )
    await state.set_state(_question_state(next_index))

    if call.message:
        await _send_question(call.message, definition, next_index)
        with suppress(Exception):
            await call.message.delete()


async def _handle_back(
    call: CallbackQuery, state: FSMContext, payload: Sequence[str]
) -> None:
    quiz_name, question_idx_raw = payload

    try:
        question_idx = int(question_idx_raw)
    except ValueError:
        await call.answer()
        return

    if question_idx <= 0:
        await call.answer()
        return

    data = await state.get_data()
    if data.get("quiz") != quiz_name:
        await call.answer()
        return

    try:
        definition = load_quiz(quiz_name)
    except FileNotFoundError:
        await call.answer("Тест недоступен")
        return

    questions = definition.questions
    if question_idx > len(questions):
        await call.answer()
        return

    previous_index = question_idx - 1
    answers: dict[str, str] = dict(data.get("answers", {}))
    total_score, tags, _ = _evaluate_answers(definition, answers)

    await state.update_data(
        answers=answers,
        score=total_score,
        tags=tags,
        index=previous_index,
    )
    await state.set_state(_question_state(previous_index))

    await call.answer()

    if call.message:
        await _send_question(call.message, definition, previous_index)
        with suppress(Exception):
            await call.message.delete()


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


def _materialize_answers(
    definition: QuizDefinition, answer_keys: dict[str, str]
) -> dict[str, QuizOption]:
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


def _evaluate_answers(
    definition: QuizDefinition, answer_keys: dict[str, str]
) -> tuple[int, list[str], dict[str, QuizOption]]:
    chosen_options = _materialize_answers(definition, answer_keys)
    total_score = sum(option.score for option in chosen_options.values())
    tags: list[str] = []
    for option in chosen_options.values():
        tags.extend(option.tags)
    return total_score, _unique(tags), chosen_options


def _question_state(index: int) -> State:
    attr = f"Q{index + 1}"
    state = getattr(QuizSession, attr, None)
    if state is None:
        raise ValueError("Unsupported quiz question index: %s" % (index + 1))
    return state


def _unique(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


__all__ = [
    "ANSWER_PREFIX",
    "BACK_PREFIX",
    "QuizDefinition",
    "QuizHooks",
    "QuizOption",
    "QuizQuestion",
    "QuizResultContext",
    "QuizSession",
    "QuizThreshold",
    "build_quiz_image_url",
    "answer_callback",
    "list_quizzes",
    "load_quiz",
    "register_quiz_hooks",
    "start_quiz",
]
