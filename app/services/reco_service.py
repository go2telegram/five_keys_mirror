"""HTTP handlers exposing the recommendation engine."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from app.reco import get_engine
from app.storage import commit_safely
from app.db.session import session_scope
from app.repo import events as events_repo

log = logging.getLogger("reco_service")


async def _log_event(name: str, meta: dict[str, Any], user_id: int | None) -> None:
    try:
        async with session_scope() as session:
            await events_repo.log(session, user_id, name, meta)
            await commit_safely(session)
    except Exception:  # pragma: no cover - logging should not break responses
        log.exception("Failed to persist recommendation event")


def _parse_tags(data: Any) -> list[str]:
    if isinstance(data, (list, tuple)):
        tags: list[str] = []
        for item in data:
            if isinstance(item, str):
                tags.append(item)
        return tags
    return []


async def handle_recommend(request: web.Request) -> web.Response:
    payload = await request.json()
    tags = _parse_tags(payload.get("tags"))
    if not tags:
        raise web.HTTPBadRequest(text="поле 'tags' обязательно и должно быть списком строк")

    audience = payload.get("audience")
    if audience is not None and not isinstance(audience, str):
        raise web.HTTPBadRequest(text="поле 'audience' должно быть строкой")

    limit_raw = payload.get("limit", 5)
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):  # pragma: no cover - defensive guard
        raise web.HTTPBadRequest(text="поле 'limit' должно быть числом") from None

    user_id = payload.get("user_id")
    if user_id is not None:
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="поле 'user_id' должно быть числом") from None

    engine = get_engine()
    results = engine.recommend(tags, audience=audience, limit=limit)

    await _log_event(
        "reco_served",
        {
            "tags": tags,
            "audience": audience,
            "limit": limit,
            "products": [result.product_id for result in results],
            "mode": "summary",
        },
        user_id if isinstance(user_id, int) else None,
    )

    return web.json_response({"products": [result.to_summary() for result in results]})


async def handle_recommend_full(request: web.Request) -> web.Response:
    payload = await request.json()
    tags = _parse_tags(payload.get("tags"))
    if not tags:
        raise web.HTTPBadRequest(text="поле 'tags' обязательно и должно быть списком строк")

    audience = payload.get("audience")
    if audience is not None and not isinstance(audience, str):
        raise web.HTTPBadRequest(text="поле 'audience' должно быть строкой")

    limit_raw = payload.get("limit", 5)
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="поле 'limit' должно быть числом") from None

    user_id = payload.get("user_id")
    if user_id is not None:
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="поле 'user_id' должно быть числом") from None

    engine = get_engine()
    results = engine.recommend_full(tags, audience=audience, limit=limit)

    await _log_event(
        "reco_served",
        {
            "tags": tags,
            "audience": audience,
            "limit": limit,
            "products": [result.product_id for result in results],
            "mode": "full",
        },
        user_id if isinstance(user_id, int) else None,
    )

    payload = {
        "products": [
            {
                **result.to_full(),
                "explain": result.explain(),
            }
            for result in results
        ]
    }
    return web.json_response(payload)


async def handle_recommend_click(request: web.Request) -> web.Response:
    payload = await request.json()
    product_id = payload.get("product_id")
    if not isinstance(product_id, str) or not product_id.strip():
        raise web.HTTPBadRequest(text="поле 'product_id' обязательно")

    user_id = payload.get("user_id")
    if user_id is not None:
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="поле 'user_id' должно быть числом") from None

    meta = {
        "product_id": product_id,
        "tags": _parse_tags(payload.get("tags")),
        "audience": payload.get("audience"),
        "source": payload.get("source"),
    }
    await _log_event("reco_click", meta, user_id if isinstance(user_id, int) else None)
    return web.json_response({"status": "ok"})


__all__ = [
    "handle_recommend",
    "handle_recommend_full",
    "handle_recommend_click",
]
