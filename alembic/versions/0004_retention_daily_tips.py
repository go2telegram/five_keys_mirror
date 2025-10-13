"""Retention settings and daily tips"""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_retention_daily_tips"
down_revision = ("0003_add_track_events_and_profiles", "0003_commerce_tables")
branch_labels = None
depends_on = None


_TIPS = [
    "Проснись и выпей стакан тёплой воды.",
    "Выйди на 5 минут к дневному свету без телефона.",
    "Добавь горсть зелени к одному приёму пищи.",
    "Поставь напоминание сделать 10 глубоких вдохов.",
    "Сделай растяжку шеи и плеч в течение минуты.",
    "Съешь фрукт вместо сладкого перекуса.",
    "Завари травяной чай вместо позднего кофе.",
    "Пройди одну остановку пешком после работы.",
    "Запиши три благодарности перед сном.",
    "Выключи экраны за 30 минут до отбоя.",
    "Поставь бутылку воды на стол на видное место.",
    "Добавь белок в первый приём пищи.",
    "Сделай 20 приседаний или отжиманий.",
    "Съешь что-то ферментированное — кефир или йогурт.",
    "Откажись от сахара в одном напитке сегодня.",
    "Сделай паузу и потянись каждые 60 минут.",
    "Добавь ложку льняного или оливкового масла в салат.",
    "Пройди 1000 шагов после обеда.",
    "Потренируй осанку: встань у стены на 60 секунд.",
    "Сверь план на день и отметь три ключевые задачи.",
    "Слушай любимую музыку во время прогулки.",
    "Приготовь простой овощной суп на завтра.",
    "Добавь орехи или семечки к перекусу.",
    "Проветри комнату перед сном на 5 минут.",
    "Откажись от лифта один раз и поднимись по лестнице.",
    "Выполни дыхание 4-7-8 перед сном.",
    "Съешь тарелку овощей разного цвета.",
    "Сделай самомассаж стоп 2–3 минуты.",
    "Подготовь бутылку воды рядом с кроватью.",
    "Заверши ужин за 2 часа до сна.",
    "Добавь 5 минут медленной растяжки утром.",
    "Поставь напоминание сделать паузу для обеда.",
    "Попробуй отказ от гаджетов во время еды.",
    "Сделай план на выходные с активностью на свежем воздухе.",
    "Съешь завтрак с источником клетчатки.",
    "Выпиши мысли перед сном, чтобы разгрузить голову.",
    "Почитай 10 страниц книги вместо соцсетей.",
    "Запланируй встречу с другом или прогулку.",
    "Используй таймер помодоро для фокусной работы.",
    "Добавь к воде ломтик лимона или огурца.",
    "Сделай зарядку для глаз — посмотри вдаль на 20 секунд.",
    "Съешь жменю ягод или сезонных фруктов.",
    "Построй ужин вокруг белка и овощей.",
    "Устрой мини-разгрузку от новостей сегодня.",
    "Поставь напоминание лечь спать в одно и то же время.",
    "Подготовь полезный перекус заранее.",
    "Запиши цель на неделю и один шаг к ней.",
    "Выдели 5 минут на глубокие приседания или планку.",
    "Поменяй позу сидя, используй подушку под поясницу.",
    "Выпей стакан воды перед каждым приёмом пищи.",
]


def _json_type(bind) -> sa.types.TypeEngine:
    if bind.dialect.name == "postgresql":
        return postgresql.JSONB()
    return sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    json_type = _json_type(bind)

    op.create_table(
        "daily_tips",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "retention_settings",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "timezone", sa.String(length=64), nullable=False, server_default=sa.text("'UTC'")
        ),
        sa.Column("tips_enabled", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("tips_time", sa.Time(), nullable=False, server_default=sa.text("'10:00'")),
        sa.Column("last_tip_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_tip_id", sa.Integer(), nullable=True),
        sa.Column("water_enabled", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column(
            "water_window_start", sa.Time(), nullable=False, server_default=sa.text("'09:00'")
        ),
        sa.Column("water_window_end", sa.Time(), nullable=False, server_default=sa.text("'21:00'")),
        sa.Column("water_last_sent_date", sa.Date(), nullable=True),
        sa.Column("water_sent_count", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("water_goal_ml", sa.Integer(), nullable=False, server_default="2000"),
        sa.Column("water_reminders", sa.SmallInteger(), nullable=False, server_default="3"),
        sa.Column("weight_kg", sa.Float(asdecimal=False), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    json_default = sa.text("'{}'")
    if bind.dialect.name == "postgresql":
        json_default = sa.text("'{}'::jsonb")

    op.create_table(
        "retention_journeys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("journey", sa.String(length=32), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", json_type, nullable=False, server_default=json_default),
    )
    op.create_index(
        "ix_retention_journeys_schedule",
        "retention_journeys",
        ["journey", "scheduled_at"],
    )

    tips_table = sa.table(
        "daily_tips",
        sa.column("text", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    now = dt.datetime.now(dt.timezone.utc)
    op.bulk_insert(
        tips_table,
        [{"text": tip, "created_at": now} for tip in _TIPS],
    )


def downgrade() -> None:
    op.drop_index("ix_retention_journeys_schedule", table_name="retention_journeys")
    op.drop_table("retention_journeys")
    op.drop_table("retention_settings")
    op.drop_table("daily_tips")
