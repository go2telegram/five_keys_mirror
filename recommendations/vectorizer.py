"""Utility functions for building recommendation vectors."""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from app.products import PRODUCTS
from app.reco import CTX

TOKEN_RE = re.compile(r"[\w\d]+", re.UNICODE)


def _tokenize(text: str) -> List[str]:
    """Split text into lowercase tokens with digits preserved."""
    return [t.lower() for t in TOKEN_RE.findall(text or "")]


def build_product_corpus() -> Dict[str, str]:
    """Return a mapping product_code -> textual description."""
    corpus: Dict[str, List[str]] = {}
    for code, data in PRODUCTS.items():
        parts: List[str] = []
        title = data.get("title")
        if title:
            parts.append(title)
        bullets = data.get("bullets", []) or []
        parts.extend(bullets)
        # добавляем контекстные описания из подсказок
        contextual: List[str] = []
        for ctx in CTX.values():
            phrase = ctx.get(code)
            if phrase:
                contextual.append(phrase)
        if contextual:
            parts.extend(contextual)
        if not parts:
            parts.append(code)
        corpus[code] = " ".join(parts)
    return {code: text for code, text in corpus.items() if text.strip()}


def _tfidf_from_tokens(tokens: Sequence[str], idf: Mapping[str, float]) -> Dict[str, float]:
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = float(sum(counts.values()))
    vec: Dict[str, float] = {}
    for token, freq in counts.items():
        weight = (freq / total) * idf.get(token, 0.0)
        if weight:
            vec[token] = weight
    return vec


def build_item_vectors(corpus: Mapping[str, str]) -> Tuple[Dict[str, Dict[str, float]], Dict[str, float]]:
    """Return tf-idf vectors for items and the idf dictionary."""
    tokenized: Dict[str, List[str]] = {code: _tokenize(text) for code, text in corpus.items()}
    vocab = set(token for tokens in tokenized.values() for token in tokens)
    doc_count = len(tokenized)
    df: Counter[str] = Counter()
    for tokens in tokenized.values():
        df.update(set(tokens))
    idf: Dict[str, float] = {}
    for token in vocab:
        # smooth idf to avoid division by zero
        idf[token] = math.log((1 + doc_count) / (1 + df[token])) + 1.0
    vectors: Dict[str, Dict[str, float]] = {}
    for code, tokens in tokenized.items():
        vec = _tfidf_from_tokens(tokens, idf)
        vectors[code] = normalize(vec)
    return vectors, idf


def vectorize_text(text: str, idf: Mapping[str, float]) -> Dict[str, float]:
    tokens = _tokenize(text)
    vec = _tfidf_from_tokens(tokens, idf)
    return normalize(vec)


def merge_vectors(vectors: Iterable[Tuple[Mapping[str, float], float]]) -> Dict[str, float]:
    """Combine vectors with weights."""
    result: Dict[str, float] = {}
    for vector, weight in vectors:
        if not vector or not weight:
            continue
        for token, value in vector.items():
            result[token] = result.get(token, 0.0) + value * weight
    return result


def normalize(vector: Mapping[str, float]) -> Dict[str, float]:
    norm = math.sqrt(sum(value * value for value in vector.values()))
    if norm == 0:
        return {}
    return {token: value / norm for token, value in vector.items() if value}


def cosine_similarity(vec_a: Mapping[str, float], vec_b: Mapping[str, float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    # iterate over smaller vector for speed
    if len(vec_a) > len(vec_b):
        vec_a, vec_b = vec_b, vec_a
    score = 0.0
    for token, value in vec_a.items():
        score += value * vec_b.get(token, 0.0)
    return score


def rank_items(
    user_vector: Mapping[str, float],
    item_vectors: Mapping[str, Mapping[str, float]],
    *,
    exclude: Iterable[str] | None = None,
    top_k: int | None = None,
) -> List[Tuple[str, float]]:
    if not user_vector:
        return []
    excluded = set(exclude or [])
    scored: List[Tuple[str, float]] = []
    for code, vector in item_vectors.items():
        if code in excluded:
            continue
        score = cosine_similarity(user_vector, vector)
        if score > 0:
            scored.append((code, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    if top_k is not None:
        return scored[:top_k]
    return scored
