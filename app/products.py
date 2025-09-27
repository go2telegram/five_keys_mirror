# app/products.py

BASE = "https://raw.githubusercontent.com/go2telegram/media/main/media/products"

PRODUCTS = {
    "T8_EXTRA": {
        "title": "T8 EXTRA",
        "bullets": [
            "Полипренолы 90% для мембран митохондрий",
            "Больше АТФ, меньше утомляемости",
        ],
        "image_url": f"{BASE}/extra.jpg",
    },
    "T8_BLEND": {
        "title": "T8 BLEND",
        "bullets": [
            "6 таёжных ягод + SibXP",
            "Антиоксидантная поддержка каждый день",
        ],
        "image_url": f"{BASE}/blend.jpg",
    },
    "VITEN": {
        "title": "NASH ViTEN",
        "bullets": [
            "Природный индуктор интерферона",
            "Поддержка иммунитета в сезон простуд",
        ],
        "image_url": f"{BASE}/viten.jpg",
    },
    "TEO_GREEN": {
        "title": "T8 TEO GREEN",
        "bullets": [
            "Растворимая/нерастворимая клетчатка",
            "Питает микробиом и ЖКТ",
        ],
        "image_url": f"{BASE}/teogreen.jpg",
    },
    "MOBIO": {
        "title": "MOBIO+",
        "bullets": [
            "Метабиотик с высокой биодоступностью",
            "После антибиотиков/стрессов — восстановление",
        ],
        "image_url": f"{BASE}/mobio.jpg",
    },
    "OMEGA3": {
        "title": "NASH Омега-3",
        "bullets": [
            "Высокая концентрация EPA/DHA",
            "Сосуды, мозг, противовоспалительно",
        ],
        "image_url": f"{BASE}/omega3.jpg",
    },
    "MAG_B6": {
        "title": "Magnesium + B6",
        "bullets": [
            "Антистресс и мышечное расслабление",
            "Поддержка качества сна",
        ],
        # оставляю текущее имя файла, как у тебя в репо
        "image_url": f"{BASE}/magniyb6.jpg",
    },
    "D3": {
        "title": "Vitamin D3",
        "bullets": [
            "Иммунитет, кости, настроение",
            "Осенне-зимняя поддержка",
        ],
        "image_url": f"{BASE}/d3.jpg",
    },
    "ERA_MIT_UP": {
        "title": "T8 ERA MIT UP",
        "bullets": [
            "Коллаген + Уролитин A + SibXP",
            "Кожа/связки и энергия митохондрий",
        ],
        "image_url": f"{BASE}/mitup.jpg",
    },
}

# Прямые ссылки на покупку (кнопки «Купить …»)
BUY_URLS = {
    "T8_EXTRA":   "https://shop.vilavi.com/Item/47086?ref=735861",  # T8 EXTRA
    "T8_BLEND":   "https://shop.vilavi.com/Item/79666?ref=735861",  # T8 BLEND
    "VITEN":      "https://shop.vilavi.com/Item/28146?ref=735861",  # NASH ViTEN
    "TEO_GREEN":  "https://shop.vilavi.com/Item/56176?ref=735861",  # T8 TEO GREEN
    "MOBIO":      "https://shop.vilavi.com/Item/53056?ref=735861",  # MOBIO+
    "OMEGA3":     "https://shop.vilavi.com/Item/49596?ref=735861",  # NASH Омега-3
    "MAG_B6":     "https://shop.vilavi.com/Item/49576?ref=735861",  # Magnesium + B6
    "D3":         "https://shop.vilavi.com/Item/49586?ref=735861",  # Vitamin D3
    "ERA_MIT_UP": "https://shop.vilavi.com/Item/39176?ref=735861",  # T8 ERA MIT UP
}

GOAL_MAP = {
    "energy": ["T8_EXTRA", "T8_BLEND"],
    "immunity": ["VITEN", "T8_BLEND", "D3"],
    "gut": ["TEO_GREEN", "MOBIO"],
    "sleep": ["MAG_B6", "OMEGA3", "D3"],
    "beauty_joint": ["ERA_MIT_UP", "OMEGA3"],
}
