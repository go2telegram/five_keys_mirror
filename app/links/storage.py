"""Persistent storage helpers for partner link manager."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from app.config import settings

_LINKS_PATH = Path(__file__).resolve().parents[1] / "var" / "link_manager.json"


@dataclass(slots=True)
class LinkSnapshot:
    """Snapshot of partner links with optional overrides."""

    register_url: str | None = None
    products: Dict[str, str] = field(default_factory=dict)


_cache: dict[str, object] = {"mtime": None, "snapshot": LinkSnapshot()}


def _ensure_dir(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        # directory creation failure should not crash the bot; storage users handle defaults
        pass


def _load_from_file(path: Path) -> LinkSnapshot:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return LinkSnapshot()
    except OSError:
        return LinkSnapshot()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return LinkSnapshot()

    register = payload.get("register")
    products_raw = payload.get("products", {})

    snapshot = LinkSnapshot()
    if isinstance(register, str) and register.strip():
        snapshot.register_url = register.strip()

    if isinstance(products_raw, dict):
        cleaned: Dict[str, str] = {}
        for key, value in products_raw.items():
            if not isinstance(key, str) or not key.strip():
                continue
            if not isinstance(value, str) or not value.strip():
                continue
            cleaned[key.strip()] = value.strip()
        snapshot.products = cleaned

    return snapshot


def load_snapshot(*, refresh: bool = False) -> LinkSnapshot:
    """Return cached link snapshot, reading from disk when necessary."""

    global _cache
    path = _LINKS_PATH
    if not refresh:
        cached_mtime = _cache.get("mtime")
        try:
            stat = path.stat()
        except FileNotFoundError:
            if cached_mtime is None:
                return _cache["snapshot"]  # type: ignore[return-value]
            _cache = {"mtime": None, "snapshot": LinkSnapshot()}
            return _cache["snapshot"]  # type: ignore[return-value]
        except OSError:
            return _cache["snapshot"]  # type: ignore[return-value]

        if cached_mtime == stat.st_mtime:
            return _cache["snapshot"]  # type: ignore[return-value]

    snapshot = _load_from_file(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    _cache = {"mtime": mtime, "snapshot": snapshot}
    return snapshot


def save_snapshot(snapshot: LinkSnapshot) -> Path:
    """Persist the snapshot atomically and update the in-memory cache."""

    path = _LINKS_PATH
    _ensure_dir(path)
    payload = {
        "register": snapshot.register_url or "",
        "products": dict(sorted(snapshot.products.items())),
    }
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)

    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    global _cache
    _cache = {"mtime": mtime, "snapshot": snapshot}
    return path


def export_records(snapshot: LinkSnapshot | None = None) -> list[dict[str, str]]:
    """Return export-ready records for the provided snapshot."""

    snap = snapshot or load_snapshot()
    records: list[dict[str, str]] = []
    if snap.register_url:
        records.append({"type": "register", "id": "", "url": snap.register_url})
    else:
        fallback = settings.velavie_url
        if fallback:
            records.append({"type": "register", "id": "", "url": fallback})
    for product_id, url in sorted(snap.products.items()):
        records.append({"type": "product", "id": product_id, "url": url})
    return records


def export_json(snapshot: LinkSnapshot | None = None) -> bytes:
    records = export_records(snapshot)
    return json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8")


def export_csv(snapshot: LinkSnapshot | None = None) -> bytes:
    records = export_records(snapshot)
    lines = ["type,id,url"]
    for record in records:
        url = record.get("url", "")
        url = url.replace("\n", " ").strip()
        lines.append(f"{record['type']},{record.get('id', '')},{url}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def override_storage_path(path: Path) -> None:
    """Adjust storage path for tests; clears the cache."""

    global _LINKS_PATH, _cache
    _LINKS_PATH = path
    _cache = {"mtime": None, "snapshot": LinkSnapshot()}


__all__ = [
    "LinkSnapshot",
    "load_snapshot",
    "save_snapshot",
    "export_records",
    "export_json",
    "export_csv",
    "override_storage_path",
]
