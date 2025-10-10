from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, KMeans
from sklearn.preprocessing import StandardScaler

from app.config import settings
from app.storage import get_fallback_events, set_segment_cache

LOG_PATH = Path("logs/events.log")
TARGET_ACTIONS = {"quiz_finish", "purchase", "payment_success"}
PAYER_ACTIONS = {"purchase", "payment_success", "subscription_active"}


def _iter_event_rows(start: dt.datetime, end: dt.datetime) -> Iterable[dict]:
    if start.tzinfo:
        start = start.astimezone(dt.timezone.utc).replace(tzinfo=None)
    if end.tzinfo:
        end = end.astimezone(dt.timezone.utc).replace(tzinfo=None)

    def _within(ts: dt.datetime) -> bool:
        return start <= ts < end

    if LOG_PATH.exists():
        with LOG_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_raw = payload.get("ts")
                if not ts_raw:
                    continue
                try:
                    ts = dt.datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                except Exception:
                    continue
                if ts.tzinfo:
                    ts = ts.astimezone(dt.timezone.utc).replace(tzinfo=None)
                if not _within(ts):
                    continue
                payload["ts"] = ts
                yield payload
    else:
        for e in get_fallback_events():
            ts_raw = e.get("ts")
            if not ts_raw:
                continue
            try:
                ts = dt.datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except Exception:
                continue
            if ts.tzinfo:
                ts = ts.astimezone(dt.timezone.utc).replace(tzinfo=None)
            if not _within(ts):
                continue
            item = dict(e)
            item["ts"] = ts
            yield item


def build_features(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    if start >= end:
        raise ValueError("start must be before end")

    rows = list(_iter_event_rows(start, end))
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["user_id"])
    if df.empty:
        return pd.DataFrame()

    df["ts"] = pd.to_datetime(df["ts"], utc=False)
    df["user_id"] = df["user_id"].astype(int)
    df["action"] = df["action"].astype(str)
    df["date"] = df["ts"].dt.date

    metrics = []
    grouped = df.groupby("user_id")

    for user_id, group in grouped:
        group = group.sort_values("ts")
        actions: list[str] = group["action"].tolist()
        timestamps = group["ts"].tolist()
        event_count = len(actions)
        unique_actions = len(set(actions))
        active_days = int(group["date"].nunique())
        first_ts: dt.datetime = timestamps[0]
        last_ts: dt.datetime = timestamps[-1]

        target_events = [ts for ts, act in zip(timestamps, actions) if act in TARGET_ACTIONS]
        payer_events = [act for act in actions if act in PAYER_ACTIONS]
        conversion = 1 if target_events else 0

        if target_events:
            time_to_first_target = (target_events[0] - first_ts).total_seconds() / 3600.0
        else:
            time_to_first_target = np.nan

        days_since_last = (end - last_ts).total_seconds() / 86400.0
        days_since_first = (end - first_ts).total_seconds() / 86400.0
        events_per_day = event_count / max(active_days, 1)
        target_count = sum(1 for a in actions if a in TARGET_ACTIONS)
        target_share = target_count / event_count if event_count else 0
        payer_flag = 1 if payer_events else 0

        metrics.append(
            {
                "user_id": user_id,
                "event_count": event_count,
                "unique_actions": unique_actions,
                "active_days": active_days,
                "events_per_day": events_per_day,
                "target_count": target_count,
                "target_share": target_share,
                "conversion": conversion,
                "payer_flag": payer_flag,
                "time_to_first_target": time_to_first_target,
                "days_since_last": days_since_last,
                "days_since_first": days_since_first,
            }
        )

    features = pd.DataFrame(metrics).set_index("user_id")
    return features


def _label_cluster(row: pd.Series) -> str:
    days_since_last = row.get("days_since_last", 0)
    events_per_day = row.get("events_per_day", 0)
    conversion = row.get("conversion", 0)
    payer = row.get("payer_flag", 0)
    target_share = row.get("target_share", 0)
    days_since_first = row.get("days_since_first", 0)

    if payer >= 0.3 or (conversion >= 0.6 and target_share >= 0.5):
        return "payer" if events_per_day < 2 else "power"
    if events_per_day >= 3 and conversion >= 0.4:
        return "power"
    if days_since_last >= 14 and events_per_day < 0.5:
        return "dormant"
    if days_since_first <= 3 and conversion < 0.3:
        return "new"
    if events_per_day >= 1:
        return "returning"
    if days_since_last > 7:
        return "dormant"
    return "new"


def cluster(features: pd.DataFrame, k_min: int = 4, k_max: int = 6) -> dict[int, str]:
    if features.empty:
        return {}

    numeric = features.fillna(0.0)
    numeric_cols = [
        "event_count",
        "unique_actions",
        "active_days",
        "events_per_day",
        "target_count",
        "target_share",
        "conversion",
        "payer_flag",
        "time_to_first_target",
        "days_since_last",
        "days_since_first",
    ]
    matrix = numeric[numeric_cols].to_numpy(dtype=float)
    scaler = StandardScaler()
    scaled = scaler.fit_transform(matrix)

    n_samples = len(features)
    k = min(max(k_min, 1), n_samples)
    k = min(k, k_max)

    if n_samples >= k and n_samples >= k_min:
        model = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = model.fit_predict(scaled)
    elif n_samples >= 3:
        model = DBSCAN(eps=1.5, min_samples=2)
        labels = model.fit_predict(scaled)
        if (labels == -1).any():
            next_cluster = labels.max(initial=-1) + 1
            labels = labels.copy()
            for idx, label in enumerate(labels):
                if label == -1:
                    labels[idx] = next_cluster
                    next_cluster += 1
    else:
        labels = np.arange(n_samples)

    result = {}
    cluster_profiles = defaultdict(list)
    for (user_id, row), cluster_id in zip(features.iterrows(), labels):
        cluster_profiles[cluster_id].append(row)

    cluster_summary = {}
    for cluster_id, rows in cluster_profiles.items():
        frame = pd.DataFrame(rows)
        cluster_summary[cluster_id] = frame.mean(numeric_only=True)

    cluster_labels = {}
    for cluster_id, summary in cluster_summary.items():
        cluster_labels[cluster_id] = _label_cluster(summary)

    for (user_id, _), cluster_id in zip(features.iterrows(), labels):
        cluster_name = cluster_labels.get(cluster_id, "new")
        result[int(user_id)] = cluster_name

    return result


def persist(mapping: dict[int, str]) -> None:
    updated_at = dt.datetime.utcnow()
    summary = Counter(mapping.values())
    set_segment_cache(mapping, summary, updated_at)

    redis_url = getattr(settings, "REDIS_URL", None)
    if redis_url:
        try:
            import redis

            client = redis.Redis.from_url(redis_url, decode_responses=True)
            pipe = client.pipeline()
            if mapping:
                pipe.hset("segments:users", mapping)
            else:
                pipe.delete("segments:users")
            if summary:
                pipe.hset("segments:summary", {k: str(v) for k, v in summary.items()})
            else:
                pipe.delete("segments:summary")
            pipe.set("segments:updated_at", updated_at.isoformat())
            pipe.execute()
        except Exception:
            pass

    database_url = getattr(settings, "DATABASE_URL", None)
    if database_url:
        try:
            from sqlalchemy import (
                Column,
                DateTime,
                Integer,
                MetaData,
                String,
                Table,
                create_engine,
                delete,
                insert,
            )
            if "postgres" in database_url.lower():
                from sqlalchemy.dialects.postgresql import insert as pg_insert
            else:
                pg_insert = None

            engine = create_engine(database_url, future=True)
            metadata = MetaData()
            table = Table(
                "user_segments",
                metadata,
                Column("user_id", Integer, primary_key=True),
                Column("segment", String(32), nullable=False),
                Column("updated_at", DateTime(timezone=False), nullable=False),
                extend_existing=True,
            )
            metadata.create_all(engine)
            with engine.begin() as conn:
                rows = [
                    {"user_id": uid, "segment": seg, "updated_at": updated_at}
                    for uid, seg in mapping.items()
                ]
                if rows:
                    if pg_insert is not None:
                        stmt = pg_insert(table).values(rows)
                        stmt = stmt.on_conflict_do_update(
                            index_elements=[table.c.user_id],
                            set_={"segment": stmt.excluded.segment, "updated_at": stmt.excluded.updated_at},
                        )
                        conn.execute(stmt)
                    else:
                        conn.execute(
                            delete(table).where(table.c.user_id.in_(list(mapping.keys())))
                        )
                        conn.execute(insert(table), rows)
                if rows:
                    conn.execute(
                        delete(table).where(~table.c.user_id.in_(list(mapping.keys())))
                    )
                else:
                    conn.execute(delete(table))
        except Exception:
            pass
