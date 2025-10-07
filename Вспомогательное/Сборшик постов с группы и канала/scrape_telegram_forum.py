# -*- coding: utf-8 -*-
"""
Экспорт разделов (forum topics) и примеров контента из телеграм-группы.
Авторизуется через Telethon от имени пользователя.

Выход: ./mito_export/{topics.csv,samples.csv,export.json,README.txt}
"""

import csv
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from dateutil import tz
from telethon import TelegramClient, errors, functions, types
from telethon.tl.custom.message import Message
from telethon.tl.functions.messages import GetHistoryRequest
from tqdm import tqdm

URL_RE = re.compile(r"https?://\S+")

# ======= НАСТРОЙКИ =======
# Рекомендуется положить в .env:
#   TG_API_ID=12345678
#   TG_API_HASH=abcdef123456...
#   MITO_CHAT=-100XXXXXXXXXX  (или @username / t.me/xxx)
# <-- Впиши числом, если не используешь .env
API_ID = int(os.getenv("TG_API_ID", "26864041"))
# <-- Впиши строкой, если не используешь .env
API_HASH = os.getenv("TG_API_HASH", "240b14b4fe642829820754b18889f679")
SESSION = os.getenv("TG_SESSION", "mito_session")  # имя файла сессии
CHAT = os.getenv("MITO_CHAT", "-1001858905974")
TIMEZONE = os.getenv("TZ", "Europe/Moscow")

SAMPLES_PER_TOPIC = 5  # сколько примеров на раздел
SAMPLE_MODE = "mix"  # first|last|mix

EXPORT_DIR = Path("./mito_export")
EXPORT_DIR.mkdir(exist_ok=True)

# ======= МОДЕЛИ =======


@dataclass
class TopicInfo:
    id: int
    title: str
    total_msgs: int
    icon_emoji_id: Optional[int]
    date_last_msg: Optional[str]


@dataclass
class SampleMsg:
    topic_id: Optional[int]  # None — если это не forum-группа
    topic_title: str
    msg_id: int
    date: str
    author: str
    text: str


# ======= УТИЛИТЫ =======


def to_local(dt: datetime, tzname: str) -> str:
    try:
        return dt.astimezone(tz.gettz(tzname)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return dt.strftime("%Y-%m-%d %H:%M")


async def resolve_chat(client: TelegramClient, chat_ref: str):
    # поддержка: -100..., @username, t.me/xxx
    if chat_ref.startswith("http"):
        chat_ref = chat_ref.split("/")[-1]
    try:
        entity = await client.get_entity(chat_ref)
    except ValueError:
        entity = await client.get_entity(int(chat_ref))
    if isinstance(entity, (types.Channel, types.Chat)):
        return entity
    raise RuntimeError("Не удалось получить entity для чата")


async def fetch_forum_topics(client: TelegramClient, channel: types.Channel) -> list:
    """
    Универсально: сначала пытаемся GetForumTopics (если есть),
    иначе — fallback на глубокий скан истории (iter_messages).
    """
    topics: list[TopicInfo] = []

    # Попытка 1: messages.GetForumTopics
    if hasattr(functions.messages, "GetForumTopics"):
        try:
            r = await client(
                functions.messages.GetForumTopics(
                    channel=channel, offset_date=None, offset_id=0, offset_topic=0, limit=100
                )
            )
            for t in getattr(r, "topics", []):
                topics.append(
                    TopicInfo(
                        id=t.id,
                        title=t.title or f"topic_{t.id}",
                        total_msgs=t.total_messages or 0,
                        icon_emoji_id=getattr(t, "icon_emoji_id", None),
                        date_last_msg=None,
                    )
                )
            return topics
        except Exception as e:
            print("[!] GetForumTopics(messages) не сработал:", e)

    # Попытка 2: channels.GetForumTopics (встречается в части билдов)
    if hasattr(functions.channels, "GetForumTopics"):
        try:
            r = await client(
                functions.channels.GetForumTopics(  # type: ignore[attr-defined]
                    channel=channel, offset_date=None, offset_id=0, offset_topic=0, limit=100
                )
            )
            for t in getattr(r, "topics", []):
                topics.append(
                    TopicInfo(
                        id=t.id,
                        title=getattr(t, "title", None) or f"topic_{t.id}",
                        total_msgs=getattr(t, "total_messages", 0) or 0,
                        icon_emoji_id=getattr(t, "icon_emoji_id", None),
                        date_last_msg=None,
                    )
                )
            return topics
        except Exception as e:
            print("[!] GetForumTopics(channels) не сработал:", e)

    # Попытка 3: fallback — глубокий скан истории
    print("[i] Fallback: сканирую историю и группирую по forum_topic_id (deep)…")
    return await _fallback_topics_from_history(client, channel)


async def _fallback_topics_from_history(
    client: TelegramClient,
    channel: types.Channel,
    total_limit: int = 100_000,  # глубоко
    per_request: int = 500,
    collect_samples: bool = True,
) -> list:
    """
    Глубокий проход по истории (iter_messages), группировка по forum_topic_id.
    Параллельно собираем:
      - по N примеров на раздел (из головы/хвоста),
      - общий список внешних ссылок,
      - stats по разделам.
    """
    from collections import defaultdict, deque

    by_tid = defaultdict(
        lambda: {
            "count": 0,
            "last": None,
            "head": deque(maxlen=5),
            "tail": deque(maxlen=5),
            "links": set(),
            "len_sum": 0,
        }
    )

    scanned = 0
    async for m in client.iter_messages(channel, limit=total_limit):
        if not isinstance(m, Message):
            continue
        scanned += 1
        tid = getattr(getattr(m, "reply_to", None), "forum_topic_id", None)
        if tid is None:
            continue

        d = by_tid[tid]
        d["count"] += 1
        if not d["last"] or (m.date and m.date > d["last"]):
            d["last"] = m.date

        text = (m.message or "").strip()
        if text:
            d["len_sum"] += len(text)
            # собираем ссылки
            for u in URL_RE.findall(text):
                d["links"].add(u)

            # копим примеры: начало и конец
            if len(d["head"]) < d["head"].maxlen:
                d["head"].appendleft(m)  # первые
            else:
                # для хвоста просто замещаем «самые старые» поздними
                if len(d["tail"]) >= d["tail"].maxlen:
                    d["tail"].popleft()
                d["tail"].append(m)

        if scanned % 5000 == 0:
            print(f"[i] Просканировано сообщений: {scanned}…")

    # Формируем topics.csv
    topics: list[TopicInfo] = []
    rows_topics = []
    rows_samples = []
    rows_links = []
    rows_stats = []

    for tid, d in by_tid.items():
        topics.append(
            TopicInfo(
                id=tid,
                title=f"topic_{tid}",
                total_msgs=d["count"],
                icon_emoji_id=None,
                date_last_msg=(d["last"] and to_local(d["last"], TIMEZONE)) or None,
            )
        )

        # stats
        avg_len = round(d["len_sum"] / max(1, d["count"]))
        rows_stats.append([tid, f"topic_{tid}", d["count"], to_local(d["last"], TIMEZONE), avg_len])

        # links
        for u in sorted(d["links"])[:100]:
            rows_links.append([tid, f"topic_{tid}", u])

        # samples (голова/хвост)
        for m in list(d["head"])[::-1] + list(d["tail"]):
            rows_samples.append(
                [
                    tid,
                    f"topic_{tid}",
                    m.id,
                    to_local(m.date, TIMEZONE),
                    (m.sender_id and f"id{m.sender_id}") or "",
                    (m.message or "").replace("\n", " ").strip()[:1500],
                ]
            )

        rows_topics.append([tid, f"topic_{tid}", d["count"], to_local(d["last"], TIMEZONE), ""])

    # Сохраняем файлы
    topics.sort(key=lambda t: t.total_msgs, reverse=True)

    topics_csv = EXPORT_DIR / "topics.csv"
    with topics_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["topic_id", "title", "msgs_total", "last_date", "emoji_id"])
        for t in topics:
            w.writerow([t.id, t.title, t.total_msgs, t.date_last_msg or "", t.icon_emoji_id or ""])

    samples_csv = EXPORT_DIR / "samples.csv"
    with samples_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["topic_id", "topic_title", "msg_id", "date", "author", "text"])
        for row in rows_samples:
            w.writerow(row)

    links_csv = EXPORT_DIR / "links.csv"
    with links_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["topic_id", "topic_title", "url"])
        for row in rows_links:
            w.writerow(row)

    stats_csv = EXPORT_DIR / "stats.csv"
    with stats_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["topic_id", "topic_title", "msgs_total", "last_date", "avg_text_len"])
        for row in rows_stats:
            w.writerow(row)

    return topics


async def fetch_history_in_topic(
    client: TelegramClient,
    channel: types.Channel,
    topic_id: int,
    limit: int = 200,
):
    """История сообщений конкретного топика (по forum_topic_id)."""
    msgs = []
    offset_id = 0
    while len(msgs) < limit:
        r = await client(
            GetHistoryRequest(
                peer=channel,
                limit=200,
                offset_date=None,
                offset_id=offset_id,
                min_id=0,
                max_id=0,
                add_offset=0,
                hash=0,
            )
        )
        if not r.messages:
            break
        for m in r.messages:
            reply = getattr(m, "reply_to", None)
            topic_ref = getattr(reply, "forum_topic_id", None) if reply else None
            if topic_ref == topic_id:
                msgs.append(m)
        offset_id = r.messages[-1].id
        if len(r.messages) < 200:
            break
    return msgs


def pick_samples(msgs: List[types.Message], n: int, mode: str) -> List[types.Message]:
    if not msgs:
        return []
    msgs_sorted = sorted(msgs, key=lambda m: (m.date or datetime.min))
    if mode == "first":
        return msgs_sorted[:n]
    if mode == "last":
        return msgs_sorted[-n:]
    a = max(1, n // 2)
    b = n - a
    return msgs_sorted[:a] + (msgs_sorted[-b:] if b > 0 else [])


async def export_forum(client: TelegramClient, channel: types.Channel):
    topics = await fetch_forum_topics(client, channel)
    samples: List[SampleMsg] = []

    if not topics:
        print("[i] Похоже, это не форум-группа. Соберу примеры из общей ленты…")
        hist = await client(
            GetHistoryRequest(
                peer=channel,
                limit=500,
                offset_id=0,
                offset_date=None,
                add_offset=0,
                max_id=0,
                min_id=0,
                hash=0,
            )
        )
        msgs = [m for m in hist.messages if isinstance(m, types.Message) and (m.message or m.media)]
        for m in pick_samples(msgs, SAMPLES_PER_TOPIC, SAMPLE_MODE):
            samples.append(
                SampleMsg(
                    topic_id=None,
                    topic_title="Общий поток",
                    msg_id=m.id,
                    date=to_local(m.date, TIMEZONE),
                    author=(m.sender_id and f"id{m.sender_id}") or "",
                    text=(m.message or "").replace("\n", " ").strip()[:1500],
                )
            )
        topics_csv = EXPORT_DIR / "topics.csv"
        with topics_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["topic_id", "title", "msgs_total", "last_date", "emoji_id"])
            w.writerow([0, "Общий поток", len(msgs), (msgs and to_local(msgs[-1].date, TIMEZONE)) or "", ""])
    else:
        for t in tqdm(topics, desc="Топики"):
            msgs = await fetch_history_in_topic(client, channel, t.id, limit=1500)
            if msgs:
                t.date_last_msg = to_local(sorted(msgs, key=lambda m: (m.date or datetime.min))[-1].date, TIMEZONE)
            for m in pick_samples(msgs, SAMPLES_PER_TOPIC, SAMPLE_MODE):
                samples.append(
                    SampleMsg(
                        topic_id=t.id,
                        topic_title=t.title,
                        msg_id=m.id,
                        date=to_local(m.date, TIMEZONE),
                        author=(m.sender_id and f"id{m.sender_id}") or "",
                        text=(m.message or "").replace("\n", " ").strip()[:1500],
                    )
                )
        topics_csv = EXPORT_DIR / "topics.csv"
        with topics_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["topic_id", "title", "msgs_total", "last_date", "emoji_id"])
            for t in topics:
                w.writerow([t.id, t.title, t.total_msgs, t.date_last_msg or "", t.icon_emoji_id or ""])

    samples_csv = EXPORT_DIR / "samples.csv"
    with samples_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["topic_id", "topic_title", "msg_id", "date", "author", "text"])
        for s in samples:
            w.writerow([s.topic_id or "", s.topic_title, s.msg_id, s.date, s.author, s.text])

    export_json = EXPORT_DIR / "export.json"
    with export_json.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "chat_id": channel.id,
                "title": channel.title,
                "exported_at": datetime.utcnow().isoformat(),
                "topics": [asdict(t) for t in topics],
                "samples": [asdict(s) for s in samples],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    (EXPORT_DIR / "README.txt").write_text(
        "Экспорт МИТОсообщества\n"
        f"Группа: {channel.title} (id {channel.id})\n"
        f"Темы/разделы: см. topics.csv\n"
        f"Примеры постов: см. samples.csv\n"
        f"JSON для автоматизации: export.json\n",
        encoding="utf-8",
    )
    print(f"[✓] Готово: {EXPORT_DIR.resolve()}")


async def main():
    # safety: если ключи пустые — явно предупредим
    if not API_ID or not API_HASH:
        raise SystemExit("Укажи TG_API_ID/TG_API_HASH (или впиши в файл скрипта).")

    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        phone = input("Телефон с +7: ").strip()
        await client.send_code_request(phone)
        code = input("Код из Telegram: ").strip()
        try:
            await client.sign_in(phone=phone, code=code)
        except errors.SessionPasswordNeededError:
            pw = input("Пароль 2FA: ").strip()
            await client.sign_in(password=pw)

    me = await client.get_me()
    print(f"[i] Авторизован как {me.username or me.id}")
    entity = await resolve_chat(client, CHAT)
    if isinstance(entity, types.Channel) and entity.forum:
        print("[i] Это forum-группа: вытащу список разделов.")
    else:
        print("[i] Это обычная группа/канал: соберу примеры из общей ленты.")
    await export_forum(client, entity)
    await client.disconnect()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
