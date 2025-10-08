"""FAQ loader for inline help."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import yaml

_FAQ_PATH = Path(__file__).with_name("faq.yaml")


@lru_cache(maxsize=1)
def load_faq() -> List[Dict[str, str]]:
    try:
        with _FAQ_PATH.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return []

    if isinstance(raw, dict):
        items = raw.get("items") or raw.get("faq") or raw.get("questions")
    else:
        items = raw

    result: List[Dict[str, str]] = []
    if isinstance(items, list):
        for entry in items:
            if not isinstance(entry, dict):
                continue
            item_id = str(entry.get("id") or entry.get("slug") or entry.get("question") or "").strip()
            question = str(entry.get("question") or entry.get("title") or "").strip()
            answer = str(entry.get("answer") or entry.get("content") or "").strip()
            if not item_id or not question or not answer:
                continue
            result.append({"id": item_id, "question": question, "answer": answer})
    return result


def get_faq_item(item_id: str) -> Optional[Dict[str, str]]:
    item_id = str(item_id or "").strip()
    if not item_id:
        return None
    for item in load_faq():
        if item.get("id") == item_id:
            return item
    return None
