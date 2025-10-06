"""Simple in-memory throttling helpers."""
from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, Tuple

_BUCKETS: Dict[Tuple[int, str], Deque[float]] = {}


def allow(user_id: int, key: str, limit: int = 5, window: int = 10) -> bool:
    """Return True if the action is allowed for the user within the window.

    Args:
        user_id: Unique identifier of the user to throttle.
        key: Arbitrary action identifier (e.g. "panel:ping").
        limit: Maximum number of allowed actions during the window.
        window: Time window in seconds.
    """

    now = time.monotonic()
    bucket_key = (user_id, key)
    bucket = _BUCKETS.setdefault(bucket_key, deque())

    # Drop outdated timestamps.
    cutoff = now - window
    while bucket and bucket[0] < cutoff:
        bucket.popleft()

    if len(bucket) >= limit:
        return False

    bucket.append(now)
    return True
