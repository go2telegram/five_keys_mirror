# -*- coding: utf-8 -*-
"""
Экспорт разделов (topics) и примеров постов без RAW-методов (Pyrogram high-level).
Работает и с форум-группами, и с обычными чатами.
Достаёт названия тем:
  1) из пользовательского маппинга (TOPIC_TITLES ниже — по твоему списку),
  2) из сервисных событий (forum_topic_created / forum_topic_edited),
  3) иначе — topic_<id>.

Пишет:
- topics.csv : topic_id;title;msgs_total;last_date;topic_url
- samples.csv: topic_id;topic_title;msg_id;date;author;text;message_url
- links.csv  : topic_id;topic_title;url
- stats.csv  : topic_id;topic_title;msgs_total;last_date;avg_text_len
- export.json: сводка

.env:
TG_API_ID=...
TG_API_HASH=...
MITO_CHAT=-1001858905974     # или @username / t.me/xxx
MITO_INVITE=                 # при необходимости: инвайт
TZ=Europe/Moscow
"""

import os
import csv
import json
import re
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict
from dateutil import tz

from pyrogram import Client
from pyrogram.types import Message
from pyrogram.errors import PeerIdInvalid, UsernameInvalid, UsernameNotOccupied
from tqdm import tqdm
from dotenv import load_dotenv

load_dotenv()

# ---------- ENV ----------
API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
CHAT = os.getenv("MITO_CHAT", "")        # -100..., @username или t.me/xxx
# инвайт-ссылка (если приватная группа)
INVITE = os.getenv("MITO_INVITE", "")
TIMEZONE = os.getenv("TZ", "Europe/Moscow")

# ---------- PARAMS ----------
SESSION = "mito_pyro"
EXPORT_DIR = Path("./mito_export")
EXPORT_DIR.mkdir(exist_ok=True)
TOTAL_LIMIT = 100_000         # глубокий проход по истории (можно увеличить)
SAMPLES_PER = 5               # примеров на тему: "голова" и "хвост"
URL_RE = re.compile(r'https?://\S+')

# ---------- Маппинг названий тем по твоему списку ----------
# Берём последний сегмент URL как topic_id и даём красивое имя
TOPIC_TITLES: Dict[int, str] = {
    3331: "МИТОlife (новости)",
    5:    "EXTRA (полипренолы)",
    459:  "Экспертные эфиры",
    16:   "МИТОХОНДРИИ",
    17:   "ПОЛИПРЕНОЛЫ",
    364:  "Напитки (кофе, шоколад, чай…)",
    3332: "МИТОрост (про ментальность)",
    1:    "Разное",
    10:   "BLEND (полипренолы)",
    3745: "ERA Mitomatrix",
    15:   "Серия NASH",
    1031: "Сыворотка (уход)",
    1159: "BEET SHOT (оксид азота)",
    8:    "STONE (детокс)",
    513:  "Масло МСТ (мозг, энергия)",
    359:  "Отзывы",
    13:   "VITEN (иммунитет)",
    275:  "Хвойный хлорофилл",
    221:  "MITOпрограмма",
    2728: "ViMi",
    3670: "IQ - код",
    4583: "Эфиры Олеси Халиной",
    181:  "О! Тест (на омега-3)",
    3343: "Мы в соц.сетях",
    1205: "TÉO GREEN (клетчатка, кишечник)",
    11:   "MOBIO (метабиотик)",
    701:  "drops (pH баланс)",
    592:  "Протеин",
    3100: "Эфиры Натальи Дмитренко",
    9:    "MIT UP (коллаген, уролитин A)",
    383:  "Очки (сон)",
    18:   "Маркетинг",
    539:  "Вебинары доктора Ольги Анатольевны",
    314:  "Онкология",
    101:  "Низкоуглеводное питание",
    3525: "Отзывы МИТОсообщество, бизнес",
    2667: "Эфиры Надежды Гурской",
    3076: "Вебинары доктора Яны Лопастейской",
    3456: "Эфиры Алины Хлебодаровой",
    3:    "Вебинары доктора Марии Павловой",
    1614: "Дети",
    3342: "Материалы",
    3273: "Вебинары Юлии Хохолковой",
    1856: "Документы",
    2979: "T8 ERA TO GO",
    2043: "PARAKILL (антипаразитарка)",
    261:  "EXO (кетоны)",
    1618: "Спорт",
    637:  "Уход",
    1615: "Наборы",
    415:  "Производство",
    4:    "Исследования",
}


@dataclass
class TopicInfo:
    id: int
    title: str
    total_msgs: int
    last_date: Optional[str]
    topic_url: str


def to_local(dt: datetime, tzname: str) -> str:
    try:
        return dt.astimezone(tz.gettz(tzname)).strftime("%Y-%m-%d %H:%M")
    except:
        return dt.strftime("%Y-%m-%d %H:%M")


def write_csv(path: Path, header: list, rows: list):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        w.writerows(rows)


def resolve_chat(app: Client, chat_ref: str, invite_link: str | None = None):
    """Пытается получить чат: int id / @username / t.me; при необходимости вступает по инвайту."""
    if not chat_ref:
        raise SystemExit(
            "Укажи MITO_CHAT в .env (например, -100..., @username или t.me/xxx)")
    ref = chat_ref.split("/")[-1] if chat_ref.startswith("http") else chat_ref
    # 1) int id
    if ref.startswith("-100") or ref.lstrip("-").isdigit():
        try:
            return app.get_chat(int(ref))
        except PeerIdInvalid:
            for _ in app.get_dialogs():
                pass  # прогреть кеш
            try:
                return app.get_chat(int(ref))
            except PeerIdInvalid:
                pass
    # 2) username
    if ref.startswith("@"):
        ref = ref[1:]
    try:
        return app.get_chat(ref)
    except (PeerIdInvalid, UsernameInvalid, UsernameNotOccupied):
        pass
    # 3) инвайт
    if invite_link:
        print("[i] Пробую присоединиться по инвайту…")
        chat = app.join_chat(invite_link)
        print(f"[i] Вступил в {chat.title} (id {chat.id})")
        return chat
    raise SystemExit(
        "PEER_ID_INVALID: аккаунт не состоит в чате. Вступи вручную или укажи MITO_INVITE в .env.")


def main():
    if not API_ID or not API_HASH:
        raise SystemExit("Укажи TG_API_ID и TG_API_HASH в .env")

    app = Client(SESSION, api_id=API_ID, api_hash=API_HASH, in_memory=False)
    app.start()

    chat = resolve_chat(app, CHAT, INVITE)
    is_forum = bool(getattr(chat, "is_forum", False))
    abs_id = str(abs(chat.id))  # для ссылок t.me/c/<abs_id>/...

    print(f"[i] Чат: {chat.title} (id {chat.id}), forum={is_forum}")
    print(f"[i] Сканирую историю (до {TOTAL_LIMIT} сообщений)…")

    from collections import defaultdict, deque
    by_tid: Dict[int, dict] = defaultdict(lambda: {
        "title": None,
        "count": 0,
        "last": None,
        "head": deque(maxlen=SAMPLES_PER),
        "tail": deque(maxlen=SAMPLES_PER),
        "links": set(),
        "len_sum": 0,
    })
    title_by_tid: Dict[int, str] = {}

    scanned = 0
    for m in tqdm(app.get_chat_history(chat.id, limit=TOTAL_LIMIT), total=TOTAL_LIMIT):
        if not isinstance(m, Message):
            continue
        scanned += 1

        # Название из сервисных событий (если попадётся)
        tid_service = getattr(m, "message_thread_id", None)
        if tid_service:
            ftc = getattr(m, "forum_topic_created", None)
            fte = getattr(m, "forum_topic_edited", None)
            name = None
            if ftc and getattr(ftc, "name", None):
                name = ftc.name
            elif fte and getattr(fte, "name", None):
                name = fte.name
            if name:
                title_by_tid[tid_service] = name

        # Определяем тему
        tid = m.message_thread_id if hasattr(
            m, "message_thread_id") and m.message_thread_id else 0

        d = by_tid[tid]

        # приоритет имён: 1) ручной маппинг TOPIC_TITLES, 2) сервисные события, 3) общий поток/дефолт
        if d["title"] is None:
            if tid in TOPIC_TITLES:
                d["title"] = TOPIC_TITLES[tid]
            elif tid in title_by_tid:
                d["title"] = title_by_tid[tid]

        d["count"] += 1
        if not d["last"] or m.date > d["last"]:
            d["last"] = m.date

        text = (m.text or m.caption or "").strip()
        if text:
            d["len_sum"] += len(text)
            for u in URL_RE.findall(text):
                d["links"].add(u)
            # сэмплы
            if len(d["head"]) < d["head"].maxlen:
                d["head"].append(m)
            else:
                if len(d["tail"]) >= d["tail"].maxlen:
                    d["tail"].popleft()
                d["tail"].append(m)

    # Добавим темы из ручного маппинга, даже если в видимой истории нет сообщений
    for tid, title in TOPIC_TITLES.items():
        _ = by_tid.setdefault(tid, {"title": title, "count": 0, "last": None,
                                    "head": [], "tail": [], "links": set(), "len_sum": 0})
        if by_tid[tid].get("title") is None:
            by_tid[tid]["title"] = title

    # Формируем выход
    topics: List[TopicInfo] = []
    rows_topics, rows_samples, rows_links, rows_stats = [], [], [], []

    for tid, d in by_tid.items():
        # дефолтные имена
        title = d.get("title") or (
            "Общий поток" if tid == 0 else f"topic_{tid}")
        last_local = d.get("last") and to_local(d["last"], TIMEZONE) or ""
        topic_url = f"https://t.me/c/{abs_id}/{tid}" if (tid != 0) else ""
        topics.append(TopicInfo(tid, title, d.get(
            "count", 0), last_local, topic_url))

        # samples
        head = list(d.get("head", []))
        tail = list(d.get("tail", []))
        for mm in head + tail:
            msg_url = f"https://t.me/c/{abs_id}/{mm.id}"
            rows_samples.append([
                tid, title, mm.id, to_local(mm.date, TIMEZONE),
                (mm.from_user and (
                    mm.from_user.username or f"id{mm.from_user.id}")) or "",
                (mm.text or mm.caption or "").replace("\n", " ")[:1500],
                msg_url
            ])
        # links
        for u in sorted(d.get("links", set()))[:200]:
            rows_links.append([tid, title, u])
        # stats
        avg_len = 0
        if d.get("count", 0):
            avg_len = round(d.get("len_sum", 0) / d["count"])
        rows_stats.append([tid, title, d.get("count", 0), last_local, avg_len])

    # сортировка: темы с сообщениями — выше; общий поток внизу
    topics.sort(key=lambda x: (x.id == 0, -x.total_msgs, x.id))

    # Запись файлов
    write_csv(EXPORT_DIR/"topics.csv",
              ["topic_id", "title", "msgs_total", "last_date", "topic_url"],
              [[t.id, t.title, t.total_msgs, t.last_date or "", t.topic_url] for t in topics])

    write_csv(EXPORT_DIR/"samples.csv",
              ["topic_id", "topic_title", "msg_id",
                  "date", "author", "text", "message_url"],
              rows_samples)

    write_csv(EXPORT_DIR/"links.csv",
              ["topic_id", "topic_title", "url"], rows_links)

    write_csv(EXPORT_DIR/"stats.csv",
              ["topic_id", "topic_title", "msgs_total", "last_date", "avg_text_len"], rows_stats)

    (EXPORT_DIR/"export.json").write_text(json.dumps({
        "chat_id": chat.id, "title": chat.title,
        "exported_at": datetime.utcnow().isoformat(),
        "topics": [asdict(t) for t in topics]
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[✓] Готово: {EXPORT_DIR.resolve()} (topics/samples/links/stats)")
    app.stop()


if __name__ == "__main__":
    main()

