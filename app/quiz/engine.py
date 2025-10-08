"""Core quiz engine that drives YAML-defined flows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import yaml


@dataclass(slots=True)
class QuizOption:
    key: str
    text: str
    score: int
    tags: tuple[str, ...]


@dataclass(slots=True)
class QuizQuestion:
    id: str
    text: str
    image: str | None
    options: tuple[QuizOption, ...]

    def iter_options(self) -> Iterator[QuizOption]:
        yield from self.options

    def get_option(self, key: str) -> QuizOption:
        for option in self.options:
            if option.key == key:
                return option
        msg = f"Option '{key}' not found for question '{self.id}'"
        raise KeyError(msg)


@dataclass(slots=True)
class QuizThreshold:
    min: int
    max: int
    label: str
    advice: str
    tags: tuple[str, ...]

    def contains(self, score: int) -> bool:
        return self.min <= score <= self.max


@dataclass(slots=True)
class QuizDefinition:
    slug: str
    title: str
    cover: str | None
    questions: tuple[QuizQuestion, ...]
    thresholds: tuple[QuizThreshold, ...]

    def question_count(self) -> int:
        return len(self.questions)

    def get_question(self, index: int) -> QuizQuestion:
        return self.questions[index]

    def find_threshold(self, score: int) -> QuizThreshold:
        for item in self.thresholds:
            if item.contains(score):
                return item
        msg = f"Score {score} is outside of defined thresholds"
        raise ValueError(msg)


@dataclass(slots=True)
class QuizResult:
    score: int
    tags: tuple[str, ...]
    label: str
    advice: str


@dataclass
class QuizSession:
    quiz: QuizDefinition
    index: int = 0
    score: int = 0
    tags: tuple[str, ...] = ()

    def is_finished(self) -> bool:
        return self.index >= self.quiz.question_count()

    def current(self) -> QuizQuestion:
        if self.is_finished():
            msg = "Quiz has already finished"
            raise RuntimeError(msg)
        return self.quiz.get_question(self.index)

    def answer(self, option_key: str) -> bool:
        """Apply answer and advance to the next state.

        Returns True if quiz is finished after the answer, False otherwise.
        """

        question = self.current()
        option = question.get_option(option_key)
        self.score += option.score
        self.tags = _merge_tags(self.tags, option.tags)
        self.index += 1
        return self.is_finished()

    def make_result(self) -> QuizResult:
        if not self.is_finished():
            msg = "Quiz is not finished yet"
            raise RuntimeError(msg)
        threshold = self.quiz.find_threshold(self.score)
        tags = _merge_tags(self.tags, threshold.tags)
        return QuizResult(
            score=self.score,
            tags=tags,
            label=threshold.label,
            advice=threshold.advice,
        )


class QuizEngine:
    """Quiz definition loader + helper factory for sessions."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        if data_dir is None:
            root = Path(__file__).resolve().parent
        else:
            root = Path(data_dir)
        if root.is_file():
            root = root.parent
        self._data_dir = root / "data"
        self._cache: dict[str, QuizDefinition] = {}

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def available(self) -> Iterable[str]:
        for file in sorted(self._data_dir.glob("*.yaml")):
            yield file.stem

    def get_quiz(self, slug: str) -> QuizDefinition:
        if slug not in self._cache:
            definition = self._load_from_disk(slug)
            self._cache[slug] = definition
        return self._cache[slug]

    def start(self, slug: str) -> QuizSession:
        quiz = self.get_quiz(slug)
        return QuizSession(quiz=quiz)

    def _load_from_disk(self, slug: str) -> QuizDefinition:
        path = self._data_dir / f"{slug}.yaml"
        if not path.exists():
            msg = f"Quiz definition '{slug}' not found"
            raise FileNotFoundError(msg)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            msg = f"Invalid payload for quiz '{slug}'"
            raise ValueError(msg)
        title = str(payload.get("title", slug.title()))
        cover = payload.get("cover")
        questions_raw = payload.get("questions", [])
        thresholds_raw = payload.get("result", {}).get("thresholds", [])
        questions = tuple(_parse_question(item) for item in questions_raw)
        thresholds = tuple(_parse_threshold(item) for item in thresholds_raw)
        if not questions:
            msg = f"Quiz '{slug}' must define at least one question"
            raise ValueError(msg)
        if not thresholds:
            msg = f"Quiz '{slug}' must define at least one result threshold"
            raise ValueError(msg)
        return QuizDefinition(
            slug=slug,
            title=title,
            cover=str(cover) if cover else None,
            questions=questions,
            thresholds=thresholds,
        )


def _parse_question(data: dict) -> QuizQuestion:
    qid = str(data.get("id"))
    if not qid:
        msg = "Question must define an id"
        raise ValueError(msg)
    text = str(data.get("text", "")).strip()
    if not text:
        msg = f"Question '{qid}' is missing text"
        raise ValueError(msg)
    image = data.get("image")
    options_raw = data.get("options", [])
    if not options_raw:
        msg = f"Question '{qid}' must define options"
        raise ValueError(msg)
    options = tuple(_parse_option(item) for item in options_raw)
    return QuizQuestion(
        id=qid,
        text=text,
        image=str(image) if image else None,
        options=options,
    )


def _parse_option(data: dict) -> QuizOption:
    key = str(data.get("key"))
    if not key:
        msg = "Option is missing key"
        raise ValueError(msg)
    text = str(data.get("text", "")).strip()
    if not text:
        msg = f"Option '{key}' is missing text"
        raise ValueError(msg)
    score_raw = data.get("score", 0)
    try:
        score = int(score_raw)
    except (TypeError, ValueError) as exc:
        msg = f"Option '{key}' has invalid score: {score_raw!r}"
        raise ValueError(msg) from exc
    tags = _normalize_tags(data.get("tags"))
    return QuizOption(key=key, text=text, score=score, tags=tags)


def _parse_threshold(data: dict) -> QuizThreshold:
    try:
        min_score = int(data.get("min"))
        max_score = int(data.get("max"))
    except (TypeError, ValueError) as exc:
        msg = f"Invalid threshold boundaries: {data!r}"
        raise ValueError(msg) from exc
    label = str(data.get("label", "")).strip()
    advice = str(data.get("advice", "")).strip()
    tags = _normalize_tags(data.get("tags"))
    return QuizThreshold(min=min_score, max=max_score, label=label, advice=advice, tags=tags)


def _normalize_tags(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, Iterable):
        msg = f"Invalid tags value: {raw!r}"
        raise ValueError(msg)
    tags: list[str] = []
    for item in raw:
        if item is None:
            continue
        tag = str(item).strip()
        if not tag:
            continue
        tags.append(tag)
    return tuple(dict.fromkeys(tags))


def _merge_tags(left: Iterable[str], right: Iterable[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {tag: None for tag in left}
    for tag in right:
        if tag not in seen:
            seen[tag] = None
    return tuple(seen.keys())


__all__ = [
    "QuizEngine",
    "QuizOption",
    "QuizQuestion",
    "QuizResult",
    "QuizSession",
]
