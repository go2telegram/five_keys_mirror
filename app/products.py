# app/products.py

PRODUCTS = {
    "T8_EXTRA": {
        "title": "T8 EXTRA",
        "bullets": [
            "Полипренолы 90% для мембран митохондрий",
            "Больше АТФ, меньше утомляемости",
        ],
    },
    "T8_BLEND": {
        "title": "T8 BLEND",
        "bullets": [
            "6 таёжных ягод + SibXP",
            "Антиоксидантная поддержка каждый день",
        ],
    },
    "VITEN": {
        "title": "NASH ViTEN",
        "bullets": [
            "Природный индуктор интерферона",
            "Поддержка иммунитета в сезон простуд",
        ],
    },
    "TEO_GREEN": {
        "title": "T8 TEO GREEN",
        "bullets": [
            "Растворимая/нерастворимая клетчатка",
            "Питает микробиом и ЖКТ",
        ],
    },
    "MOBIO": {
        "title": "MOBIO+",
        "bullets": [
            "Метабиотик с высокой биодоступностью",
            "После антибиотиков/стрессов — восстановление",
        ],
    },
    "OMEGA3": {
        "title": "NASH Омега-3",
        "bullets": [
            "Высокая концентрация EPA/DHA",
            "Сосуды, мозг, противовоспалительно",
        ],
    },
    "MAG_B6": {
        "title": "Magnesium + B6",
        "bullets": [
            "Антистресс и мышечное расслабление",
            "Поддержка качества сна",
        ],
    },
    "D3": {
        "title": "Vitamin D3",
        "bullets": [
            "Иммунитет, кости, настроение",
            "Осенне-зимняя поддержка",
        ],
    },
    "ERA_MIT_UP": {
        "title": "T8 ERA MIT UP",
        "bullets": [
            "Коллаген + Уролитин A + SibXP",
            "Кожа/связки и энергия митохондрий",
        ],
    },
}

# Прямые ссылки на покупку (кнопки «Купить …»)
BUY_URLS = {
    "T8_EXTRA": "https://shop.vilavi.com/Item/47086?ref=735861&utm_source=bot&utm_medium=telegram&utm_campaign=product_menu&utm_content=t8_extra",  # T8 EXTRA
    "T8_BLEND": "https://shop.vilavi.com/Item/79666?ref=735861&utm_source=bot&utm_medium=telegram&utm_campaign=product_menu&utm_content=t8_blend",  # T8 BLEND
    "VITEN": "https://shop.vilavi.com/Item/28146?ref=735861&utm_source=bot&utm_medium=telegram&utm_campaign=product_menu&utm_content=viten",  # NASH ViTEN
    "TEO_GREEN": "https://shop.vilavi.com/Item/56176?ref=735861&utm_source=bot&utm_medium=telegram&utm_campaign=product_menu&utm_content=teo_green",  # T8 TEO GREEN
    "MOBIO": "https://shop.vilavi.com/Item/53056?ref=735861&utm_source=bot&utm_medium=telegram&utm_campaign=product_menu&utm_content=mobio",  # MOBIO+
    "OMEGA3": "https://shop.vilavi.com/Item/49596?ref=735861&utm_source=bot&utm_medium=telegram&utm_campaign=product_menu&utm_content=omega3",  # NASH Омега-3
    "MAG_B6": "https://shop.vilavi.com/Item/49576?ref=735861&utm_source=bot&utm_medium=telegram&utm_campaign=product_menu&utm_content=mag_b6",  # Magnesium + B6
    "D3": "https://shop.vilavi.com/Item/49586?ref=735861&utm_source=bot&utm_medium=telegram&utm_campaign=product_menu&utm_content=d3",  # Vitamin D3
    "ERA_MIT_UP": "https://shop.vilavi.com/Item/39176?ref=735861&utm_source=bot&utm_medium=telegram&utm_campaign=product_menu&utm_content=era_mit_up",  # T8 ERA MIT UP
}

GOAL_MAP = {
    "energy": ["T8_EXTRA", "T8_BLEND"],
    "immunity": ["VITEN", "T8_BLEND", "D3"],
    "gut": ["TEO_GREEN", "MOBIO"],
    "sleep": ["MAG_B6", "OMEGA3", "D3"],
    "beauty_joint": ["ERA_MIT_UP", "OMEGA3"],
}
