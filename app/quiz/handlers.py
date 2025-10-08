"""Router for YAML-driven quizzes."""

from __future__ import annotations

from pathlib import Path

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.storage import SESSIONS

from .engine import QuizEngine, QuizSession

router = Router()
_engine = QuizEngine()


def _resolve_image(path_str: str) -> Path | None:
    path = Path(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    if path.exists():
        return path
    return None


def _build_options_keyboard(slug: str, question_id: str, *, options: list[tuple[str, str]]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for key, text in options:
        kb.button(text=text, callback_data=f"tests:{slug}:{question_id}:{key}")
    kb.button(text="🏠 Домой", callback_data="home:main")
    layout = [1] * (len(options) + 1)
    kb.adjust(*layout)
    return kb


def _format_question_text(session: QuizSession, total: int) -> str:
    question = session.quiz.get_question(session.index)
    return (
        f"{session.quiz.title}\n\n"
        f"Вопрос {session.index + 1}/{total}:\n"
        f"{question.text}"
    )


async def _render_question(c: CallbackQuery, session: QuizSession) -> None:
    question = session.quiz.get_question(session.index)
    kb = _build_options_keyboard(
        session.quiz.slug,
        question.id,
        options=[(option.key, option.text) for option in question.options],
    )
    text = _format_question_text(session, session.quiz.question_count())
    markup = kb.as_markup()

    if question.image:
        image_path = _resolve_image(question.image)
        if image_path:
            media = InputMediaPhoto(media=FSInputFile(image_path), caption=text)
            try:
                await c.message.edit_media(media, reply_markup=markup)
                return
            except Exception:
                try:
                    await c.message.edit_reply_markup()
                except Exception:
                    pass
                await c.message.answer_photo(photo=FSInputFile(image_path), caption=text, reply_markup=markup)
                return
    try:
        await c.message.edit_text(text, reply_markup=markup)
    except Exception:
        try:
            await c.message.edit_reply_markup()
        except Exception:
            pass
        await c.message.answer(text, reply_markup=markup)


async def _render_result(c: CallbackQuery, session: QuizSession) -> None:
    result = session.make_result()
    tags = ", ".join(result.tags) if result.tags else "—"
    text = (
        f"{session.quiz.title} — итог\n\n"
        f"Баллы: {result.score}\n"
        f"Уровень: {result.label or '—'}\n\n"
        f"{result.advice or 'Без рекомендаций.'}\n\n"
        f"Теги: {tags}"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="quiz:menu")
    kb.button(text="🏠 Домой", callback_data="home:main")
    markup = kb.adjust(2).as_markup()

    try:
        if c.message.photo:
            await c.message.edit_caption(text, reply_markup=markup)
        else:
            await c.message.edit_text(text, reply_markup=markup)
    except Exception:
        try:
            await c.message.edit_reply_markup()
        except Exception:
            pass
        await c.message.answer(text, reply_markup=markup)


def _start_session(user_id: int, slug: str) -> QuizSession:
    session_data = SESSIONS.setdefault(user_id, {})
    quiz = _engine.get_quiz(slug)
    session_data["tests"] = {
        "slug": slug,
        "index": 0,
        "score": 0,
        "tags": [],
    }
    return QuizSession(quiz=quiz)


def _load_session(user_id: int, slug: str) -> QuizSession | None:
    session_data = SESSIONS.get(user_id)
    if not session_data:
        return None
    state = session_data.get("tests")
    if not state or state.get("slug") != slug:
        return None
    quiz = _engine.get_quiz(slug)
    tags = tuple(state.get("tags", []))
    index = int(state.get("index", 0))
    score = int(state.get("score", 0))
    return QuizSession(quiz=quiz, index=index, score=score, tags=tags)


def _save_session(user_id: int, session: QuizSession) -> None:
    session_data = SESSIONS.setdefault(user_id, {})
    session_data["tests"] = {
        "slug": session.quiz.slug,
        "index": session.index,
        "score": session.score,
        "tags": list(session.tags),
    }


def _clear_session(user_id: int) -> None:
    session_data = SESSIONS.get(user_id)
    if session_data:
        session_data.pop("tests", None)


@router.callback_query(F.data.regexp(r"^tests:(?P<slug>[a-z0-9_\-]+)$"))
async def start_quiz(callback: CallbackQuery, regexp: dict[str, str]) -> None:
    slug = regexp["slug"]
    try:
        quiz_session = _start_session(callback.from_user.id, slug)
    except FileNotFoundError:
        await callback.answer("Тест пока недоступен", show_alert=True)
        return
    await _render_question(callback, quiz_session)
    await callback.answer()


@router.callback_query(F.data.regexp(r"^tests:(?P<slug>[a-z0-9_\-]+):(?P<qid>[^:]+):(?P<option>[^:]+)$"))
async def handle_answer(callback: CallbackQuery, regexp: dict[str, str]) -> None:
    slug = regexp["slug"]
    session = _load_session(callback.from_user.id, slug)
    if session is None or session.is_finished():
        await callback.answer()
        return

    question = session.quiz.get_question(session.index)
    if question.id != regexp["qid"]:
        await callback.answer()
        return

    try:
        finished = session.answer(regexp["option"])
    except KeyError:
        await callback.answer()
        return

    _save_session(callback.from_user.id, session)

    if finished:
        await _render_result(callback, session)
        _clear_session(callback.from_user.id)
    else:
        await _render_question(callback, session)
    await callback.answer()
