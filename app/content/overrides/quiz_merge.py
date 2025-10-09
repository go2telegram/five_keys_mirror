"""Utilities for applying partial overrides to quiz YAML definitions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class QuizOverrideError(ValueError):
    """Raised when an override payload cannot be applied."""


def apply_quiz_override(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return quiz payload with override applied.

    The override format mirrors the structure of the quiz definition but may omit
    keys that should remain untouched. Questions and options are matched by their
    ``id``/``key`` values to allow partial updates without redefining the whole
    block.
    """

    if not override:
        return base

    merged = deepcopy(base)
    for key, value in override.items():
        if key == "questions":
            merged["questions"] = _merge_questions(base.get("questions"), value)
        elif key == "result":
            merged["result"] = _merge_result(base.get("result"), value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _merge_questions(base: Any, override: Any) -> list[dict[str, Any]]:
    if base is None:
        base_list: list[dict[str, Any]] = []
    elif isinstance(base, list):
        base_list = [deepcopy(q) if isinstance(q, dict) else {} for q in base]
    else:
        raise QuizOverrideError("Base questions payload must be a list")

    if override is None:
        return base_list
    if not isinstance(override, list):
        raise QuizOverrideError("Override questions payload must be a list")

    index = {q.get("id"): q for q in base_list if isinstance(q, dict) and q.get("id")}
    for item in override:
        if not isinstance(item, dict):
            continue
        qid = item.get("id")
        if not qid:
            continue
        target = index.get(qid)
        if target is None:
            index[qid] = deepcopy(item)
            base_list.append(index[qid])
            continue
        for key, value in item.items():
            if key == "options":
                target["options"] = _merge_options(target.get("options"), value)
            elif key != "id":
                target[key] = deepcopy(value)

    return base_list


def _merge_options(base: Any, override: Any) -> list[dict[str, Any]]:
    if base is None:
        base_list: list[dict[str, Any]] = []
    elif isinstance(base, list):
        base_list = [deepcopy(o) if isinstance(o, dict) else {} for o in base]
    else:
        raise QuizOverrideError("Base options payload must be a list")

    if override is None:
        return base_list
    if not isinstance(override, list):
        raise QuizOverrideError("Override options payload must be a list")

    index = {o.get("key"): o for o in base_list if isinstance(o, dict) and o.get("key")}
    for item in override:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not key:
            continue
        target = index.get(key)
        if target is None:
            index[key] = deepcopy(item)
            base_list.append(index[key])
            continue
        for field, value in item.items():
            if field != "key":
                target[field] = deepcopy(value)
    return base_list


def _merge_result(base: Any, override: Any) -> dict[str, Any]:
    base_result = deepcopy(base) if isinstance(base, dict) else {}
    if override is None:
        return base_result
    if not isinstance(override, dict):
        raise QuizOverrideError("Result override must be a mapping")

    for key, value in override.items():
        if key == "thresholds":
            base_result["thresholds"] = _merge_thresholds(base_result.get("thresholds"), value)
        else:
            base_result[key] = deepcopy(value)
    return base_result


def _merge_thresholds(base: Any, override: Any) -> list[dict[str, Any]]:
    if base is None:
        base_list: list[dict[str, Any]] = []
    elif isinstance(base, list):
        base_list = [deepcopy(t) if isinstance(t, dict) else {} for t in base]
    else:
        raise QuizOverrideError("Thresholds payload must be a list")

    if override is None:
        return base_list
    if not isinstance(override, list):
        raise QuizOverrideError("Thresholds override must be a list")

    index = {(t.get("min"), t.get("max")): t for t in base_list if isinstance(t, dict)}
    for item in override:
        if not isinstance(item, dict):
            continue
        key = (item.get("min"), item.get("max"))
        target = index.get(key)
        if target is None:
            copy = deepcopy(item)
            base_list.append(copy)
            index[key] = copy
            continue
        for field, value in item.items():
            target[field] = deepcopy(value)
    return base_list
