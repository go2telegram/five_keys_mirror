"""Recommendation service backed by Redis cache."""
from __future__ import annotations
import json
import time
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import redis.asyncio as redis

from app.config import settings
from app.products import BUY_URLS, PRODUCTS, GOAL_MAP
from app.storage import EVENTS, USERS, save_event
from recommendations import vectorizer

_CACHE_TTL = 24 * 60 * 60  # 24 hours
_MATRIX_KEY = "reco:item_matrix"
_USER_CACHE_KEY = "reco:user:{user_id}"
_METRIC_KEY = "metrics:recommend_ctr"

_redis_client: redis.Redis | None = None
_local_cache: Dict[str, tuple[Any, float | None]] = {}
_local_metrics = Counter()


async def _get_redis() -> redis.Redis | None:
    global _redis_client
    if not settings.REDIS_URL:
        return None
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def _cache_get(key: str) -> Any:
    client = await _get_redis()
    if client:
        raw = await client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    data = _local_cache.get(key)
    if not data:
        return None
    value, expires = data
    if expires is not None and expires < time.time():
        _local_cache.pop(key, None)
        return None
    return value


async def _cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    client = await _get_redis()
    payload = json.dumps(value)
    if client:
        if ttl:
            await client.set(key, payload, ex=ttl)
        else:
            await client.set(key, payload)
        return
    expires = time.time() + ttl if ttl else None
    _local_cache[key] = (value, expires)


async def _cache_delete(key: str) -> None:
    client = await _get_redis()
    if client:
        await client.delete(key)
        return
    _local_cache.pop(key, None)


async def _hincrby(field: str, amount: int) -> None:
    client = await _get_redis()
    if client:
        await client.hincrby(_METRIC_KEY, field, amount)
        return
    _local_metrics[field] += amount


async def _load_item_matrix() -> Dict[str, Any]:
    cached = await _cache_get(_MATRIX_KEY)
    if cached:
        return cached
    return await rebuild_item_matrix()


async def rebuild_item_matrix() -> Dict[str, Any]:
    corpus = vectorizer.build_product_corpus()
    item_vectors, idf = vectorizer.build_item_vectors(corpus)
    popular = _popular_codes()
    matrix = {
        "vectors": item_vectors,
        "idf": idf,
        "popular": popular,
    }
    await _cache_set(_MATRIX_KEY, matrix)
    return matrix


def _popular_codes(limit: int | None = None) -> List[str]:
    counter: Counter[str] = Counter()
    for event in EVENTS:
        action = event.get("action")
        payload = event.get("payload") or {}
        if action == "quiz_finish":
            quiz = payload.get("quiz")
            if quiz:
                counter.update(GOAL_MAP.get(quiz, []))
        elif action == "recommend_click":
            code = payload.get("code")
            if code:
                counter[code] += 3
        elif action == "recommend_show":
            items = payload.get("items") or []
            counter.update(items)
        elif action == "lead_done":
            items = payload.get("items") or []
            counter.update(items)
    if not counter:
        counter.update(PRODUCTS.keys())
    ranked = [code for code, _ in counter.most_common()]
    if limit:
        return ranked[:limit]
    return ranked


def _collect_user_signals(user_id: int) -> tuple[list[str], set[str]]:
    texts: list[str] = []
    codes: set[str] = set()
    profile = USERS.get(user_id, {})
    last_plan = profile.get("last_plan") or {}
    if last_plan:
        context = last_plan.get("context")
        if context:
            texts.append(str(context))
        level = last_plan.get("level")
        if level:
            texts.append(str(level))
        for code in last_plan.get("products", []) or []:
            codes.add(code)
    for event in EVENTS:
        if event.get("user_id") != user_id:
            continue
        action = event.get("action")
        payload = event.get("payload") or {}
        if action == "quiz_finish":
            quiz = payload.get("quiz")
            level = payload.get("level")
            score = payload.get("score")
            parts = ["quiz", str(quiz or ""), str(level or ""), str(score or "")]
            texts.append(" ".join(filter(None, parts)))
            codes.update(GOAL_MAP.get(quiz, []))
        elif action == "recommend_click":
            code = payload.get("code")
            if code:
                codes.add(code)
        elif action == "recommend_show":
            for code in payload.get("items", []) or []:
                texts.append(f"recommended {code}")
        elif action == "menu_click":
            section = payload.get("section")
            if section:
                texts.append(f"menu {section}")
        elif action == "lead_done":
            for code in payload.get("items", []) or []:
                codes.add(code)
    return texts, codes


def _format_items(ranked: Sequence[tuple[str, float]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for code, score in ranked:
        product = PRODUCTS.get(code, {})
        bullets = product.get("bullets", []) or []
        description = bullets[0] if bullets else ""
        items.append(
            {
                "code": code,
                "title": product.get("title", code),
                "description": description,
                "image_url": product.get("image_url"),
                "buy_url": BUY_URLS.get(code),
                "score": round(float(score), 4),
            }
        )
    return items


def _user_vector(
    signals: Iterable[str],
    engaged_codes: Iterable[str],
    matrix: Mapping[str, Any],
) -> Dict[str, float]:
    idf = matrix.get("idf", {})
    vectors = matrix.get("vectors", {})
    text = " ".join(signals)
    base = vectorizer.vectorize_text(text, idf) if text else {}
    additions = []
    for code in engaged_codes:
        vec = vectors.get(code)
        if vec:
            additions.append((vec, 0.6))
    if additions:
        merged = vectorizer.merge_vectors([(base, 1.0)] + additions)
    else:
        merged = base
    return vectorizer.normalize(merged)


async def refresh_user_cache(user_id: int, matrix: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    matrix = matrix or await _load_item_matrix()
    signals, engaged = _collect_user_signals(user_id)
    user_vec = _user_vector(signals, engaged, matrix)
    ranked = vectorizer.rank_items(user_vec, matrix.get("vectors", {}), exclude=engaged, top_k=10)
    if not ranked:
        popular = matrix.get("popular") or _popular_codes()
        ranked = [(code, 0.0) for code in popular[:5]]
    items = _format_items(ranked)
    await _cache_set(_USER_CACHE_KEY.format(user_id=user_id), items, ttl=_CACHE_TTL)
    return items


async def get_reco(user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    key = _USER_CACHE_KEY.format(user_id=user_id)
    cached = await _cache_get(key)
    if cached:
        return cached[:limit]
    items = await refresh_user_cache(user_id)
    return items[:limit]


async def mark_recommendation_shown(user_id: int, codes: Sequence[str]) -> None:
    await _hincrby("shows", len(codes))
    save_event(user_id, USERS.get(user_id, {}).get("source"), "recommend_show", {"items": list(codes)})


async def mark_recommendation_click(user_id: int, code: str) -> None:
    await _hincrby("clicks", 1)
    save_event(user_id, USERS.get(user_id, {}).get("source"), "recommend_click", {"code": code})
    # invalidate cache to encourage re-ranking based on click feedback
    await _cache_delete(_USER_CACHE_KEY.format(user_id=user_id))


async def get_metrics() -> Dict[str, Any]:
    client = await _get_redis()
    if client:
        data = await client.hgetall(_METRIC_KEY)
        shows = int(data.get("shows", 0))
        clicks = int(data.get("clicks", 0))
    else:
        shows = int(_local_metrics.get("shows", 0))
        clicks = int(_local_metrics.get("clicks", 0))
    ctr = (clicks / shows) if shows else 0.0
    return {"shows": shows, "clicks": clicks, "ctr": ctr}


def active_user_ids(limit: Optional[int] = None) -> List[int]:
    ids = {uid for uid in USERS.keys()}
    ids.update(event.get("user_id") for event in EVENTS if event.get("user_id"))
    result = [int(uid) for uid in ids if uid]
    result.sort()
    if limit:
        return result[:limit]
    return result
