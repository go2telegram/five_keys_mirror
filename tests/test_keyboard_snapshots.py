import json
import re
from pathlib import Path
from typing import Callable

import pytest
from aiogram.types import InlineKeyboardMarkup

from app.keyboards import kb_back_home, kb_calc_menu, kb_main

SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "keyboards"
_ALLOWED_PATTERN = re.compile(r"[^0-9A-Za-zА-Яа-яЁё.,:()/%\-\s]+")


def _strip_emoji(text: str) -> str:
    return _ALLOWED_PATTERN.sub("", text).strip()


def _markup_to_snapshot(markup: InlineKeyboardMarkup) -> str:
    data = markup.model_dump()
    for row in data.get("inline_keyboard", []):
        for button in row:
            text = button.get("text")
            if isinstance(text, str):
                button["text"] = _strip_emoji(text)
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)


@pytest.mark.parametrize(
    ("snapshot", "factory", "kwargs"),
    [
        ("kb_main", kb_main, {}),
        ("kb_back_home_default", kb_back_home, {}),
        ("kb_calc_menu", kb_calc_menu, {}),
    ],
)
def test_keyboard_snapshot(
    snapshot: str, factory: Callable[..., InlineKeyboardMarkup], kwargs: dict
) -> None:
    markup = factory(**kwargs)
    payload = _markup_to_snapshot(markup)

    snapshot_path = SNAPSHOT_DIR / f"{snapshot}.json"
    assert snapshot_path.exists(), f"Snapshot missing: {snapshot_path}"

    expected = snapshot_path.read_text(encoding="utf-8").strip()
    assert payload == expected
