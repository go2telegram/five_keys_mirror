# app/handlers/navigator.py
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.keyboards import kb_back_home, kb_main

router = Router()

# ====== ДАННЫЕ НАВИГАЦИИ (только ссылки и названия) ======
NAV = {
    "about": {
        "title": "👩‍⚕️ Обо мне",
        "items": [
            ("Обо мне", "https://t.me/c/1780036611/2606"),
            ("Написать мне", "https://t.me/Nat988988"),
            ("Заказать продукт", "https://shop.vilavi.com/?ref=985920"),
            ("Партнёрская ссылка", "https://t.me/c/1780036611/4380"),
            ("МИТОсообщество", "https://t.me/c/1780036611/4364"),
            ("Английский", "https://t.me/c/1780036611/4745"),
        ],
    },
    "mito": {
        "title": "🧬 Митохондрии",
        "items": [
            ("Что такое митохондрии", "https://t.me/c/1780036611/3132"),
            ("Тест митохондрий", "https://t.me/c/1780036611/2514"),
            ("Зачем тест", "https://t.me/c/1780036611/2504"),
            ("МИТО-программа", "https://t.me/c/1780036611/3270"),
            ("Отзывы", "https://t.me/c/1780036611/3287"),
            ("Эфиры", "https://t.me/c/1780036611/3117"),
            ("Клетка", "https://t.me/c/1780036611/3112"),
        ],
    },
    "products": {
        "title": "💊 Продукты для здоровья",
        "items": [
            ("Полипренолы. Продукт", "https://t.me/c/1780036611/3137"),
            ("О полипренолах", "https://t.me/c/1780036611/3128"),
            ("Полипренолы + биофлавоноиды", "https://t.me/c/1780036611/3344"),
            ("Детокс", "https://t.me/c/1780036611/3162"),
            ("Метабиотик", "https://t.me/c/1780036611/3232"),
            ("Коллаген + Уролитин A", "https://t.me/c/1780036611/3266"),
            ("Хлорофилл", "https://t.me/c/1780036611/3312"),
            ("pH баланс", "https://t.me/c/1780036611/3317"),
            ("Иммунитет", "https://t.me/c/1780036611/3365"),
            ("Антипаразитарный комплекс", "https://t.me/c/1780036611/3222"),
            ("Женское здоровье", "https://t.me/c/1780036611/3115"),
        ],
    },
    "functional": {
        "title": "🥤 Функциональное питание",
        "items": [
            ("Омега-3", "https://t.me/c/1780036611/3298"),
            ("Масло МСТ", "https://t.me/c/1780036611/3332"),
            ("Оксид азота", "https://t.me/c/1780036611/3196"),
            ("Клетчатка", "https://t.me/c/1780036611/3246"),
            ("Кофе", "https://t.me/c/1780036611/3110"),
            ("Протеин", "https://t.me/c/1780036611/3207"),
            ("Микроэлементы", "https://t.me/c/1780036611/3318"),
        ],
    },
    "lifestyle": {
        "title": "🌿 Образ жизни",
        "items": [
            ("Ментальность", "https://t.me/c/1780036611/3095"),
            ("Питание", "https://t.me/c/1780036611/3099"),
            ("Сон", "https://t.me/c/1780036611/3167"),
            ("Мозг", "https://t.me/c/1780036611/4710"),
            ("Рецепты", "https://t.me/c/1780036611/3106"),
            ("Уход за собой", "https://t.me/c/1780036611/3125"),
            ("Книги", "https://t.me/c/1780036611/2733"),
            ("Мини-курсы", "https://t.me/c/1780036611/2351"),
        ],
    },
}

# ====== Клавиатуры ======


def kb_nav_root():
    kb = InlineKeyboardBuilder()
    kb.button(text="👩‍⚕️ Обо мне", callback_data="nav:cat:about")
    kb.button(text="🧬 Митохондрии", callback_data="nav:cat:mito")
    kb.button(text="💊 Продукты", callback_data="nav:cat:products")
    kb.button(text="🥤 Функциональное питание",
              callback_data="nav:cat:functional")
    kb.button(text="🌿 Образ жизни", callback_data="nav:cat:lifestyle")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(1, 1, 1, 1, 1, 1)
    return kb.as_markup()


def kb_nav_category(cat_key: str):
    data = NAV[cat_key]
    kb = InlineKeyboardBuilder()
    # по 2 ссылки в ряд
    for title, url in data["items"]:
        kb.button(text=title, url=url)
    kb.button(text="⬅️ Назад", callback_data="nav:root")
    kb.button(text="🏠 Домой", callback_data="home")
    kb.adjust(2, 2)  # 2 в ряд; последняя строка — две кнопки
    return kb.as_markup()

# ====== Хендлеры ======


@router.callback_query(F.data == "nav:root")
async def nav_root(c: CallbackQuery):
    await c.message.edit_text("🧭 Навигатор по каналу — выбери раздел:", reply_markup=kb_nav_root())


@router.callback_query(F.data.startswith("nav:cat:"))
async def nav_category(c: CallbackQuery):
    cat_key = c.data.split(":")[-1]
    if cat_key not in NAV:
        await c.answer("Раздел не найден", show_alert=False)
        return
    title = NAV[cat_key]["title"]
    await c.message.edit_text(f"{title}\nВыбери, что открыть:", reply_markup=kb_nav_category(cat_key))

