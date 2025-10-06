from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

BASE_PATH = Path(__file__).resolve().parent / "base.json"
HISTORY_PATH = Path(__file__).resolve().parent / "history.jsonl"


def _load_json(path: Path) -> Any:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fp:
        content = fp.read().strip()
        if not content:
            return []
        return json.loads(content)


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
        fp.write("\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalise_actions(actions: Iterable[str] | None) -> List[str]:
    if not actions:
        return []
    normalised: List[str] = []
    for action in actions:
        if action is None:
            continue
        text = str(action).strip()
        if text:
            normalised.append(text)
    return normalised


def load_base() -> Dict[str, Dict[str, Any]]:
    raw = _load_json(BASE_PATH)
    entries: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            event = str(item.get("event", "")).strip()
            if not event:
                continue
            entries[event] = {
                "event": event,
                "reason": str(item.get("reason", "")).strip(),
                "actions": _normalise_actions(item.get("actions")),
                "timestamp": str(item.get("timestamp", "")).strip(),
            }
    elif isinstance(raw, dict):
        for event, item in raw.items():
            if not isinstance(item, dict):
                continue
            event_key = str(event).strip()
            if not event_key:
                continue
            entries[event_key] = {
                "event": event_key,
                "reason": str(item.get("reason", "")).strip(),
                "actions": _normalise_actions(item.get("actions")),
                "timestamp": str(item.get("timestamp", "")).strip(),
            }
    return entries


def save_base(entries: Dict[str, Dict[str, Any]]) -> None:
    payload = []
    for event, item in sorted(entries.items()):
        payload.append(
            {
                "event": event,
                "reason": item.get("reason", ""),
                "actions": _normalise_actions(item.get("actions")),
                "timestamp": item.get("timestamp", ""),
            }
        )
    _save_json(BASE_PATH, payload)


def record_history(record: Dict[str, Any]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False))
        fp.write("\n")


def upsert_event(
    event: str,
    reason: str,
    actions: Iterable[str] | None = None,
    actor: str | None = None,
) -> Dict[str, Any]:
    event_key = event.strip()
    if not event_key:
        raise ValueError("Event name must not be empty")

    entries = load_base()
    now_iso = _now_iso()
    payload = {
        "event": event_key,
        "reason": reason.strip(),
        "actions": _normalise_actions(actions),
        "timestamp": now_iso,
    }
    op = "update" if event_key in entries else "create"
    entries[event_key] = payload
    save_base(entries)

    history_record = {
        "op": op,
        "event": event_key,
        "reason": payload["reason"],
        "actions": payload["actions"],
        "timestamp": payload["timestamp"],
        "actor": actor or "system",
        "recorded_at": _now_iso(),
    }
    record_history(history_record)
    return payload


def get_event(event: str) -> Dict[str, Any] | None:
    event_key = event.strip()
    if not event_key:
        return None
    entries = load_base()
    return entries.get(event_key)


def list_events() -> List[str]:
    entries = load_base()
    return sorted(entries.keys())
