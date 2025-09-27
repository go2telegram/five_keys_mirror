# app/handlers/picker.py
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards import kb_goal_menu, kb_buylist_pdf
from app.products import PRODUCTS, GOAL_MAP
from app.utils_media import send_product_album
from app.reco import product_lines
from app.storage import set_last_plan, SESSIONS
from app.config import settings

router = Router()

# ---- База сценариев по целям ----
GOAL_META = {
    "energy": {
        "title": "План: Энергия",
        "context_name": "Энергия",
        "ctx_basic": "energy_light",
        "ctx_pro": "energy_high",
        "actions": [
            "Ложиться до 23:00 и спать 7–9 часов.",
            "10 минут утреннего света (балкон/улица).",
            "30 минут быстрой ходьбы ежедневно.",
        ],
        "notes": "Гидратация 30–35 мл/кг. Ужин — за 3 часа до сна.",
        "codes_basic": ["T8_BLEND", "OMEGA3"],
        "codes_pro":   ["T8_EXTRA", "VITEN", "MOBIO"],
    },
    "immunity": {
        "title": "План: Иммунитет",
        "context_name": "Иммунитет",
        "ctx_basic": "immunity_mid",
        "ctx_pro": "immunity_low",
        "actions": [
            "Сон 7–9 часов и регулярный режим.",
            "Прогулки ежедневно 30–40 минут.",
            "Белок 1.2–1.6 г/кг, овощи ежедневно.",
        ],
        "notes": "В сезон простуд: тёплые напитки, влажность 40–60%, промывание носа.",
        "codes_basic": ["VITEN", "T8_BLEND"],
        "codes_pro":   ["VITEN", "T8_BLEND", "D3"],
    },
    "gut": {
        "title": "План: ЖКТ / микробиом",
        "context_name": "ЖКТ / микробиом",
        "ctx_basic": "gut_mild",
        "ctx_pro": "gut_high",
        "actions": [
            "Регулярный режим питания (без «донышек»).",
            "Клетчатка ежедневно (TEO GREEN) + вода 30–35 мл/кг.",
            "Минимизируй сахар и ультра-обработанные продукты.",
        ],
        "notes": "Если были антибиотики — курс MOBIO поможет быстрее восстановиться.",
        "codes_basic": ["TEO_GREEN", "MOBIO"],
        "codes_pro":   ["MOBIO", "TEO_GREEN", "OMEGA3"],
    },
    "sleep": {
        "title": "План: Сон",
        "context_name": "Сон",
        "ctx_basic": "sleep_mild",
        "ctx_pro": "sleep_high",
        "actions": [
            "Экран-детокс за 60 минут до сна.",
            "Прохладная тёмная спальня (18–20°C, маска/шторы).",
            "Кофеин — не позже 16:00, ужин за 3 часа до сна.",
        ],
        "notes": "Если сложно расслабиться — дыхание 4–7–8 или тёплый душ перед сном.",
        "codes_basic": ["MAG_B6", "OMEGA3"],
        "codes_pro":   ["MAG_B6", "OMEGA3", "D3"],
    },
    "beauty_joint": {
        "title": "План: Кожа / суставы",
        "context_name": "Кожа / суставы",
        "ctx_basic": "energy_norm",
        "ctx_pro": "energy_norm",
        "actions": [
            "Достаток белка (≈1.4 г/кг) и коллагеновые источники.",
            "Лёгкая нагрузка на суставы (ходьба, плавание).",
            "Сон 7–9 часов (идёт восстановление тканей).",
        ],
        "notes": "Береги связки/сухожилия: растяжка, без резких стартов.",
        "codes_basic": ["ERA_MIT_UP", "OMEGA3"],
        "codes_pro":   ["ERA_MIT_UP", "OMEGA3", "D3"],
    },
}


def _back_home(back_cb: str = "pick:menu"):
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=back_cb)
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(2)
    return kb.as_markup()

# --- ШАГ 0: меню целей ---


@router.callback_query(F.data == "pick:menu")
async def pick_menu(c: CallbackQuery):
    await c.message.edit_text("Выбери цель — подберу продукты:", reply_markup=kb_goal_menu())

# --- ШАГ 1: цель → возраст ---


@router.callback_query(F.data.startswith("pick:goal:"))
async def pick_goal(c: CallbackQuery):
    goal_key = c.data.split(":")[-1]
    if goal_key not in GOAL_META:
        await c.message.edit_text("Пока нет рекомендаций по этой цели.")
        return

    SESSIONS.setdefault(c.from_user.id, {})["pick"] = {"goal": goal_key}

    kb = InlineKeyboardBuilder()
    kb.button(text="До 30", callback_data=f"pick:age:{goal_key}:u30")
    kb.button(text="30–50", callback_data=f"pick:age:{goal_key}:30_50")
    kb.button(text="50+", callback_data=f"pick:age:{goal_key}:50p")
    kb.button(text="⬅️ Назад", callback_data="pick:menu")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(3, 2)
    await c.message.edit_text("Возрастная группа:", reply_markup=kb.as_markup())

# --- ШАГ 2: возраст → образ жизни ---


@router.callback_query(F.data.regexp(r"^pick:age:[a-z_]+:(u30|30_50|50p)$"))
async def pick_age(c: CallbackQuery):
    _, _, goal_key, age = c.data.split(":")
    SESSIONS.setdefault(c.from_user.id, {}).setdefault("pick", {})["age"] = age

    kb = InlineKeyboardBuilder()
    kb.button(text="Офис/малоподвижный",
              callback_data=f"pick:life:{goal_key}:{age}:office")
    kb.button(text="Активный/спорт",
              callback_data=f"pick:life:{goal_key}:{age}:active")
    kb.button(text="⬅️ Назад", callback_data=f"pick:goal:{goal_key}")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(2, 2)
    await c.message.edit_text("Образ жизни:", reply_markup=kb.as_markup())

# --- ШАГ 3: образ жизни → уровень ---


@router.callback_query(F.data.regexp(r"^pick:life:[a-z_]+:(u30|30_50|50p):(office|active)$"))
async def pick_life(c: CallbackQuery):
    _, _, goal_key, age, life = c.data.split(":")
    SESSIONS.setdefault(c.from_user.id, {}).setdefault(
        "pick", {})["life"] = life

    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Новичок",
              callback_data=f"pick:lvl:{goal_key}:{age}:{life}:basic")
    kb.button(text="🔵 Продвинутый",
              callback_data=f"pick:lvl:{goal_key}:{age}:{life}:pro")
    kb.button(text="⬅️ Назад", callback_data=f"pick:age:{goal_key}:{age}")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(2, 2)
    await c.message.edit_text("Уровень подхода:", reply_markup=kb.as_markup())

# --- ШАГ 4: уровень → ограничения ---


@router.callback_query(F.data.regexp(r"^pick:lvl:[a-z_]+:(u30|30_50|50p):(office|active):(basic|pro)$"))
async def pick_level(c: CallbackQuery):
    _, _, goal_key, age, life, level = c.data.split(":")
    SESSIONS.setdefault(c.from_user.id, {}).setdefault(
        "pick", {})["level"] = level

    kb = InlineKeyboardBuilder()
    kb.button(
        text="Нет", callback_data=f"pick:all:{goal_key}:{age}:{life}:{level}:none")
    kb.button(text="Аллергия на травы",
              callback_data=f"pick:all:{goal_key}:{age}:{life}:{level}:herbs")
    kb.button(text="Веган",
              callback_data=f"pick:all:{goal_key}:{age}:{life}:{level}:vegan")
    kb.button(text="⬅️ Назад",
              callback_data=f"pick:life:{goal_key}:{age}:{life}")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(2, 3)
    await c.message.edit_text("Аллергии/ограничения:", reply_markup=kb.as_markup())

# --- ШАГ 5: ограничения → сезон ---


@router.callback_query(F.data.regexp(r"^pick:all:[a-z_]+:(u30|30_50|50p):(office|active):(basic|pro):(none|herbs|vegan)$"))
async def pick_allergies(c: CallbackQuery):
    _, _, goal_key, age, life, level, allerg = c.data.split(":")
    SESSIONS.setdefault(c.from_user.id, {}).setdefault(
        "pick", {})["allerg"] = allerg

    kb = InlineKeyboardBuilder()
    kb.button(
        text="Лето", callback_data=f"pick:season:{goal_key}:{age}:{life}:{level}:{allerg}:summer")
    kb.button(
        text="Зима", callback_data=f"pick:season:{goal_key}:{age}:{life}:{level}:{allerg}:winter")
    kb.button(text="Другое",
              callback_data=f"pick:season:{goal_key}:{age}:{life}:{level}:{allerg}:other")
    kb.button(text="⬅️ Назад",
              callback_data=f"pick:lvl:{goal_key}:{age}:{life}:{level}")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(3, 2)
    await c.message.edit_text("Сезон:", reply_markup=kb.as_markup())

# --- ШАГ 6: сезон → бюджет ---


@router.callback_query(F.data.regexp(r"^pick:season:[a-z_]+:(u30|30_50|50p):(office|active):(basic|pro):(none|herbs|vegan):(summer|winter|other)$"))
async def pick_season(c: CallbackQuery):
    _, _, goal_key, age, life, level, allerg, season = c.data.split(":")
    SESSIONS.setdefault(c.from_user.id, {}).setdefault(
        "pick", {})["season"] = season

    kb = InlineKeyboardBuilder()
    kb.button(text="💡 Лайт (1–2 поз.)",
              callback_data=f"pick:budget:{goal_key}:{age}:{life}:{level}:{allerg}:{season}:lite")
    kb.button(text="⚖ Стандарт",
              callback_data=f"pick:budget:{goal_key}:{age}:{life}:{level}:{allerg}:{season}:std")
    kb.button(text="🚀 Про",
              callback_data=f"pick:budget:{goal_key}:{age}:{life}:{level}:{allerg}:{season}:pro")
    kb.button(text="⬅️ Назад",
              callback_data=f"pick:all:{goal_key}:{age}:{life}:{level}:{allerg}")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(3, 2)
    await c.message.edit_text("Бюджет:", reply_markup=kb.as_markup())

# --- ШАГ 7: финальная выдача ---


@router.callback_query(F.data.regexp(r"^pick:budget:[a-z_]+:(u30|30_50|50p):(office|active):(basic|pro):(none|herbs|vegan):(summer|winter|other):(lite|std|pro)$"))
async def pick_finalize(c: CallbackQuery):
    _, _, goal_key, age, life, level, allerg, season, budget = c.data.split(
        ":")
    meta = GOAL_META[goal_key]

    # Базовый набор по уровню
    if level == "basic":
        rec_codes = meta["codes_basic"].copy()
        ctx = meta["ctx_basic"]
    else:
        rec_codes = meta["codes_pro"].copy()
        ctx = meta["ctx_pro"]

    # Возраст/образ жизни
    if age == "50p" and "D3" in PRODUCTS and "D3" not in rec_codes:
        rec_codes.append("D3")
    if life == "active" and "OMEGA3" in PRODUCTS and "OMEGA3" not in rec_codes:
        rec_codes.append("OMEGA3")

    # Ограничения
    if allerg == "herbs":
        rec_codes = [c for c in rec_codes if c not in ("TEO_GREEN",)]
    if allerg == "vegan":
        rec_codes = [c for c in rec_codes if c not in ("ERA_MIT_UP", "OMEGA3")]

    # Сезон
    if season == "winter" and "D3" in PRODUCTS and "D3" not in rec_codes:
        rec_codes.append("D3")

    # Бюджет
    if budget == "lite":
        rec_codes = rec_codes[:2]
    elif budget == "std":
        rec_codes = rec_codes[:3]
    # pro — оставляем всё

    # Подстраховка
    if not rec_codes:
        rec_codes = GOAL_MAP.get(goal_key, [])[:2]

    # Фото
    await send_product_album(c.bot, c.message.chat.id, rec_codes[:3])

    # Карточка и PDF-план
    lines = product_lines(rec_codes[:3], ctx)
    level_label = "Новичок" if level == "basic" else "Продвинутый"
    desc = (
        f"возраст: {'50+' if age=='50p' else ('30–50' if age=='30_50' else 'до 30')}, "
        f"образ жизни: {'активный' if life=='active' else 'офис'}, "
        f"ограничения: {'нет' if allerg=='none' else ('травы' if allerg=='herbs' else 'веган')}, "
        f"сезон: {'зима' if season=='winter' else ('лето' if season=='summer' else 'другой')}, "
        f"бюджет: {'лайт' if budget=='lite' else ('стандарт' if budget=='std' else 'про')}"
    )

    msg = [
        f"<b>{meta['context_name']}</b> — {level_label}\n",
        desc + "\n",
        "Поддержка:\n" + "\n".join(lines),
    ]
    await c.message.answer("".join(msg), reply_markup=kb_buylist_pdf("pick:menu", rec_codes[:3]))

    # Сохраняем план для PDF
    actions = meta["actions"]
    notes = meta["notes"]
    if allerg == "herbs":
        notes += " Учитываем чувствительный ЖКТ/аллергии: начни с половинных порций, избегай острых блюд и алкоголя."
    if age == "50p":
        notes += " Сфокусируй внимание на костях/суставах: витамин D3 при дефиците по согласованию с врачом."

    set_last_plan(
        c.from_user.id,
        {
            "title": meta["title"],
            "context": goal_key,
            "context_name": meta["context_name"],
            "level": f"{level_label}, {desc}",
            "products": rec_codes[:3],
            "lines": lines,
            "actions": actions,
            "notes": notes,
            "order_url": settings.VILAVI_ORDER_NO_REG,
        }
    )

