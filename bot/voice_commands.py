"""Логика обработки голосовых команд."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, List

from aiogram.types import Message

from app.keyboards import kb_main
from app.texts import WELCOME
from app.utils_openai import ai_generate
from app.handlers.report import pdf_cmd

CommandHandler = Callable[[Message, str, str], Awaitable[None]]


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = text.replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@dataclass(slots=True)
class VoiceCommand:
    """Описание голосовой команды."""

    name: str
    keywords: tuple[str, ...]
    handler: CommandHandler
    description: str = ""

    def __post_init__(self) -> None:
        self.keywords = tuple(_normalize(k) for k in self.keywords)


@dataclass
class VoiceCommandMatch:
    command: VoiceCommand
    remainder_original: str
    remainder_normalized: str


class VoiceCommandProcessor:
    """Находит подходящую голосовую команду и выполняет её."""

    def __init__(self, commands: Iterable[VoiceCommand] | None = None) -> None:
        self._commands: List[VoiceCommand] = list(commands or [])

    def register(self, command: VoiceCommand) -> None:
        self._commands.append(command)

    def match(self, transcription: str) -> VoiceCommandMatch | None:
        normalized = _normalize(transcription)
        norm_tokens = normalized.split()
        orig_tokens = transcription.strip().split()

        for command in self._commands:
            for kw in command.keywords:
                kw_tokens = kw.split()
                if len(norm_tokens) < len(kw_tokens):
                    continue
                if norm_tokens[: len(kw_tokens)] != kw_tokens:
                    continue
                remainder_norm_tokens = norm_tokens[len(kw_tokens) :]
                remainder_orig_tokens = orig_tokens[len(kw_tokens) :]
                remainder_normalized = " ".join(remainder_norm_tokens).strip()
                remainder_original = " ".join(remainder_orig_tokens).strip()
                return VoiceCommandMatch(
                    command=command,
                    remainder_original=remainder_original,
                    remainder_normalized=remainder_normalized,
                )
        return None

    async def execute(self, message: Message, transcription: str) -> bool:
        match = self.match(transcription)
        if not match:
            return False
        remainder = match.remainder_original or match.remainder_normalized
        await match.command.handler(message, transcription, remainder)
        return True

    def describe(self) -> list[tuple[str, str]]:
        return [
            (", ".join(cmd.keywords), cmd.description)
            for cmd in self._commands
        ]


async def _handle_menu(message: Message, _: str, __: str) -> None:
    await message.answer(WELCOME, reply_markup=kb_main())


async def _handle_pdf(message: Message, _: str, __: str) -> None:
    await pdf_cmd(message)


async def _handle_assistant(message: Message, _: str, remainder: str) -> None:
    prompt = remainder.strip()
    if not prompt:
        await message.answer(
            "Сформулируйте запрос после ключевого слова «ассистент»."
        )
        return
    reply = await ai_generate(prompt)
    await message.answer(reply)


voice_processor = VoiceCommandProcessor(
    commands=[
        VoiceCommand(
            name="menu",
            keywords=("меню", "главное меню", "домой", "старт"),
            handler=_handle_menu,
            description="Показать главное меню",
        ),
        VoiceCommand(
            name="pdf",
            keywords=("отчет", "отчёт", "pdf", "план"),
            handler=_handle_pdf,
            description="Отправить последний PDF-план",
        ),
        VoiceCommand(
            name="assistant",
            keywords=("ассистент", "помощник", "бот"),
            handler=_handle_assistant,
            description="Задать вопрос ассистенту",
        ),
    ]
)

__all__ = ["voice_processor", "VoiceCommand", "VoiceCommandProcessor"]
