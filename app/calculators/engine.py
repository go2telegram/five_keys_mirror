"""Unified calculators engine with declarative step definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Mapping, Sequence

from app.catalog.api import pick_for_context, product_meta
from app.reco import CTX, product_lines

# Types ---------------------------------------------------------------------


@dataclass(slots=True)
class InputStep:
    """Represents a step that expects free-form text input."""

    key: str
    prompt: str
    error: str
    parser: Callable[[str], Any]
    validators: Sequence[Callable[[Any], str | None]] = ()

    kind: str = field(init=False, default="input")


@dataclass(slots=True)
class ChoiceOption:
    """Selectable option in a choice step."""

    key: str
    label: str
    value: Any


@dataclass(slots=True)
class ChoiceStep:
    """Represents a step that expects the user to pick among options."""

    key: str
    prompt: str
    options: Sequence[ChoiceOption]

    kind: str = field(init=False, default="choice")

    def option_by_key(self, key: str) -> ChoiceOption | None:
        for option in self.options:
            if option.key == key:
                return option
        return None


Step = InputStep | ChoiceStep


@dataclass(slots=True)
class CalculationContext:
    """Context object passed to result builders."""

    data: Mapping[str, Any]
    user_id: int
    username: str | None


@dataclass(slots=True)
class CalculationResult:
    """Container for calculator result artifacts."""

    cards_title: str
    cards: Sequence[str | Mapping[str, Any]]
    headline: str
    bullets: Sequence[str]
    plan_payload: Mapping[str, Any]
    event_payload: Mapping[str, Any]
    cards_ctx: str | None = None
    back_cb: str = "calc:menu"
    with_actions: bool = True


@dataclass(slots=True)
class CalculatorDefinition:
    """Describes a calculator flow."""

    slug: str
    title: str
    steps: Sequence[Step]
    build_result: Callable[[CalculationContext], CalculationResult]


# Helpers -------------------------------------------------------------------


def _parse_float(text: str) -> float:
    value = text.replace(",", ".").strip()
    if not value or len(value) > 32:
        raise ValueError
    try:
        number = Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - defensive
        raise ValueError from exc
    if not number.is_finite():
        raise ValueError
    return float(number)


def _parse_int(text: str) -> int:
    value = text.strip()
    if not value or not value.isdigit() or len(value) > 6:
        raise ValueError
    return int(value)


def _range_validator(
    min_value: float, max_value: float, message: str
) -> Callable[[Any], str | None]:
    def validate(value: Any) -> str | None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return message
        if numeric < min_value or numeric > max_value:
            return message
        return None

    return validate


def _int_range_validator(
    min_value: int, max_value: int, message: str
) -> Callable[[Any], str | None]:
    def validate(value: Any) -> str | None:
        try:
            numeric = int(value)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return message
        if numeric < min_value or numeric > max_value:
            return message
        return None

    return validate


def _build_cards_with_overrides(codes: Iterable[str], context_key: str) -> list[dict]:
    overrides = CTX.get(context_key, {})
    cards: list[dict] = []
    for code in codes:
        meta = product_meta(code)
        if not meta:
            continue
        cards.append(
            {
                "code": meta["code"],
                "name": meta.get("name", meta["code"]),
                "short": meta.get("short", ""),
                "props": meta.get("props", []),
                "images": meta.get("images", []),
                "order_url": meta.get("order_url"),
                "helps_text": overrides.get(code),
            }
        )
    return cards


# Water ---------------------------------------------------------------------

_ACTIVITY_LABELS: dict[str, str] = {
    "low": "Низкая активность",
    "moderate": "Умеренная активность",
    "high": "Высокая активность",
}

_CLIMATE_LABELS: dict[str, str] = {
    "temperate": "Умеренный климат",
    "hot": "Жаркий климат",
}


def _water_compute_total(weight: float, activity: str, climate: str) -> tuple[float, int]:
    base = weight * 0.03
    activity_add = {"low": 0.0, "moderate": 0.35, "high": 0.6}.get(activity, 0.35)
    climate_add = {"temperate": 0.0, "hot": 0.7}.get(climate, 0.0)
    total = round(base + activity_add + climate_add, 1)
    glasses = max(1, round(total / 0.25))
    return total, glasses


def _water_headline(total: float, glasses: int) -> str:
    return f"Рекомендуемая дневная норма: <b>{total} л</b> (~{glasses} стаканов по 250 мл)."


def _water_bullets(activity: str, climate: str) -> list[str]:
    hints = {
        "low": "Добавь короткую разминку днём и шаги к вечеру.",
        "moderate": "Держи бутылку воды под рукой и пей по глотку каждый час.",
        "high": "Пополняй воду до и после тренировок, добавь электролиты.",
    }
    climate_hint = {
        "temperate": "Стартуй утро со стакана воды натощак.",
        "hot": "В жару добавляй щепотку соли/лимон к одному-двум стаканам.",
    }
    return [
        "Отслеживай количество через приложение или бутылку с делениями.",
        hints.get(activity, "Поддерживай ровный водный режим днём."),
        climate_hint.get(climate, "Пей по 2-3 больших стакана между приёмами пищи."),
    ]


def _build_water_result(ctx: CalculationContext) -> CalculationResult:
    weight = float(ctx.data["weight"])
    activity = str(ctx.data["activity"])
    climate = str(ctx.data["climate"])

    total, glasses = _water_compute_total(weight, activity, climate)
    bullets = _water_bullets(activity, climate)
    cards = pick_for_context("calc_water", None, ["TEO_GREEN", "OMEGA3"])

    plan_payload = {
        "title": "План: водный баланс",
        "context": "calc_water",
        "context_name": "Калькулятор водного баланса",
        "level": None,
        "products": ["TEO_GREEN", "OMEGA3"],
        "lines": [
            f"— Пить {total} л воды в день (~{glasses} стаканов)",
            "— Обновлять бутылку каждые 2–3 часа",
        ],
        "actions": bullets,
        "notes": (
            "Следи за самочувствием и корректируй норму с врачом при хронических состояниях."
        ),
        "order_url": None,
    }

    event_payload = {
        "calc": "water",
        "total": total,
        "glasses": glasses,
        "weight": weight,
        "activity": activity,
        "climate": climate,
    }

    return CalculationResult(
        cards_title="Итог: водный баланс",
        cards=cards,
        headline=_water_headline(total, glasses),
        bullets=bullets,
        plan_payload=plan_payload,
        event_payload=event_payload,
        cards_ctx=None,
    )


_water_definition = CalculatorDefinition(
    slug="water",
    title="Калькулятор воды",
    steps=[
        InputStep(
            key="weight",
            prompt="Введи вес в килограммах, например: <code>72</code>",
            error="Не удалось распознать вес. Пример: <code>72.5</code>",
            parser=_parse_float,
            validators=(_range_validator(30, 300, "Вес должен быть от 30 до 300 кг."),),
        ),
        ChoiceStep(
            key="activity",
            prompt="Выбери уровень активности:",
            options=[
                ChoiceOption("low", _ACTIVITY_LABELS["low"], "low"),
                ChoiceOption("moderate", _ACTIVITY_LABELS["moderate"], "moderate"),
                ChoiceOption("high", _ACTIVITY_LABELS["high"], "high"),
            ],
        ),
        ChoiceStep(
            key="climate",
            prompt="В каком климате ты живёшь?",
            options=[
                ChoiceOption("temperate", _CLIMATE_LABELS["temperate"], "temperate"),
                ChoiceOption("hot", _CLIMATE_LABELS["hot"], "hot"),
            ],
        ),
    ],
    build_result=_build_water_result,
)


# Calories ------------------------------------------------------------------

_ACTIVITY_FACTORS: dict[str, tuple[str, float]] = {
    "12": ("Минимальная активность", 1.2),
    "1375": ("Лёгкие тренировки 1–3 раза в неделю", 1.375),
    "155": ("Умеренные тренировки 3–5 раз", 1.55),
    "1725": ("Интенсивные тренировки 6–7 раз", 1.725),
    "19": ("Очень высокая активность", 1.9),
}

_GOAL_LABELS: dict[str, str] = {
    "loss": "Снижение веса",
    "maintain": "Поддержание",
    "gain": "Набор массы",
}


def _compute_calories(
    sex: str,
    age: int,
    weight: float,
    height: int,
    factor: float,
    goal: str,
) -> tuple[int, int, int]:
    base = 10 * weight + 6.25 * height - 5 * age + (5 if sex == "m" else -161)
    tdee = base * factor
    if goal == "loss":
        target = tdee * 0.85
    elif goal == "gain":
        target = tdee * 1.1
    else:
        target = tdee
    return round(base), round(tdee), round(target)


def _calorie_headline(base: int, tdee: int, target: int, goal: str) -> str:
    label = _GOAL_LABELS.get(goal, "Поддержание")
    return f"BMR: <b>{base} ккал</b>. Полная норма (TDEE): <b>{tdee} ккал</b>.\nЦель — {label}: <b>{target} ккал/день</b>."


def _calorie_bullets(goal: str) -> list[str]:
    goals = {
        "loss": "Дефицит 10–15%: добавь шаги, держи белок и клетчатку в каждом приёме пищи.",
        "maintain": "Фокус на регулярности сна, белок 1.6 г/кг и 7–9 часов восстановления.",
        "gain": "Слегка избыточные калории + силовые 3 раза в неделю для набора сухой массы.",
    }
    return [
        goals.get(goal, goals["maintain"]),
        "Планируй меню заранее и держи полезные перекусы под рукой.",
        "Пей 30–35 мл воды на кг веса и следи за шагами (8–10 тыс.).",
    ]


def _build_calorie_result(ctx: CalculationContext) -> CalculationResult:
    sex = str(ctx.data["sex"])
    age = int(ctx.data["age"])
    weight = float(ctx.data["weight"])
    height = int(ctx.data["height"])
    factor_key = str(ctx.data["activity"])
    goal = str(ctx.data["goal"])

    factor = _ACTIVITY_FACTORS.get(factor_key, ("", 1.55))[1]
    base, tdee, target = _compute_calories(sex, age, weight, height, factor, goal)
    bullets = _calorie_bullets(goal)

    rec_codes = ["T8_BLEND", "TEO_GREEN", "VITEN"]
    cards = pick_for_context("calc_kcal", goal, rec_codes)

    plan_payload = {
        "title": "План: калории (BMR/TDEE)",
        "context": "calc_kcal",
        "context_name": "Калькулятор калорий",
        "level": goal,
        "products": rec_codes,
        "lines": [
            f"— BMR: {base} ккал",
            f"— TDEE: {tdee} ккал",
            f"— Целевые калории: {target} ккал",
        ],
        "actions": bullets,
        "notes": "Настрой рацион вместе с врачом/коучем при хронических состояниях.",
        "order_url": None,
    }

    event_payload = {
        "calc": "kcal",
        "sex": sex,
        "age": age,
        "weight": weight,
        "height": height,
        "activity": factor_key,
        "goal": goal,
        "bmr": base,
        "tdee": tdee,
        "target": target,
    }

    return CalculationResult(
        cards_title="Итог: калории (BMR/TDEE)",
        cards=cards,
        headline=_calorie_headline(base, tdee, target, goal),
        bullets=bullets,
        plan_payload=plan_payload,
        event_payload=event_payload,
        cards_ctx=goal,
    )


_calorie_definition = CalculatorDefinition(
    slug="kcal",
    title="Калькулятор калорий",
    steps=[
        ChoiceStep(
            key="sex",
            prompt="Выбери пол:",
            options=[
                ChoiceOption("m", "Мужчина", "m"),
                ChoiceOption("f", "Женщина", "f"),
            ],
        ),
        InputStep(
            key="age",
            prompt="Возраст (в годах), например: <code>32</code>",
            error="Возраст должен быть числом лет. Пример: <code>32</code>",
            parser=_parse_int,
            validators=(_int_range_validator(14, 90, "Укажи возраст от 14 до 90 лет."),),
        ),
        InputStep(
            key="weight",
            prompt="Текущий вес в килограммах (например, <code>78.5</code>):",
            error="Вес должен быть числом от 30 до 250 кг.",
            parser=_parse_float,
            validators=(_range_validator(30, 250, "Вес должен быть числом от 30 до 250 кг."),),
        ),
        InputStep(
            key="height",
            prompt="Рост в сантиметрах (например, <code>175</code>):",
            error="Рост должен быть целым числом сантиметров.",
            parser=_parse_int,
            validators=(_int_range_validator(130, 220, "Рост в диапазоне 130–220 см."),),
        ),
        ChoiceStep(
            key="activity",
            prompt="Выбери уровень активности:",
            options=[
                ChoiceOption(key, title, key) for key, (title, _) in _ACTIVITY_FACTORS.items()
            ],
        ),
        ChoiceStep(
            key="goal",
            prompt="Какая цель?",
            options=[
                ChoiceOption("loss", "Снижение веса", "loss"),
                ChoiceOption("maintain", "Поддержание", "maintain"),
                ChoiceOption("gain", "Набор массы", "gain"),
            ],
        ),
    ],
    build_result=_build_calorie_result,
)


# Macros --------------------------------------------------------------------

_PREFERENCE_LABELS: dict[str, tuple[str, float, float]] = {
    "balanced": ("Сбалансированное питание", 1.6, 0.9),
    "lowcarb": ("Сниженные углеводы", 1.4, 1.0),
    "highprotein": ("Высокобелковый подход", 2.0, 0.8),
}


def _target_calories(weight: float, goal: str) -> int:
    maintenance = weight * 30.0
    if goal == "loss":
        return round(maintenance * 0.85)
    if goal == "gain":
        return round(maintenance * 1.1)
    return round(maintenance)


def _macros(weight: float, goal: str, preference: str) -> tuple[int, int, int, int]:
    calories = _target_calories(weight, goal)
    pref = _PREFERENCE_LABELS.get(preference, _PREFERENCE_LABELS["balanced"])
    protein = max(1.2, pref[1]) * weight
    fats = max(0.7, pref[2]) * weight
    carbs_calories = max(0.0, calories - protein * 4 - fats * 9)
    carbs = carbs_calories / 4

    def _round(value: float) -> int:
        return int(round(value / 5.0) * 5)

    return (
        calories,
        _round(protein),
        _round(fats),
        max(0, _round(carbs)),
    )


def _macro_bullets(goal: str) -> list[str]:
    messages = {
        "loss": "Добавь силовые 2–3 раза в неделю и шаги 8–10 тыс.",
        "maintain": "Держи белок в каждом приёме пищи, следи за водой и сном.",
        "gain": "Фокус на прогресс в силовых и качественный сон 7–9 часов.",
    }
    return [
        messages.get(goal, messages["maintain"]),
        "Планируй приёмы пищи заранее и делай замеры раз в 2 недели.",
        "Добавь клетчатку (овощи/TEO GREEN), чтобы держать аппетит под контролем.",
    ]


def _build_macro_result(ctx: CalculationContext) -> CalculationResult:
    weight = float(ctx.data["weight"])
    goal = str(ctx.data["goal"])
    preference = str(ctx.data["preference"])

    calories, protein, fats, carbs = _macros(weight, goal, preference)
    bullets = _macro_bullets(goal)

    rec_codes = ["OMEGA3", "T8_BLEND", "TEO_GREEN"]
    cards = pick_for_context("calc_macros", goal, rec_codes)

    plan_payload = {
        "title": "План: белки/жиры/углеводы",
        "context": "calc_macros",
        "context_name": "Калькулятор БЖУ",
        "level": goal,
        "products": rec_codes,
        "lines": [
            f"— Калории: {calories} ккал",
            f"— Белки: {protein} г",
            f"— Жиры: {fats} г",
            f"— Углеводы: {carbs} г",
        ],
        "actions": bullets,
        "notes": "Подбирай меню вместе со специалистом при хронических состояниях.",
        "order_url": None,
    }

    event_payload = {
        "calc": "macros",
        "weight": weight,
        "goal": goal,
        "preference": preference,
        "calories": calories,
        "protein": protein,
        "fats": fats,
        "carbs": carbs,
    }

    return CalculationResult(
        cards_title="Итог: распределение БЖУ",
        cards=cards,
        headline=(
            f"Калории: <b>{calories} ккал</b>. Белки: <b>{protein} г</b>,"
            f" жиры: <b>{fats} г</b>, углеводы: <b>{carbs} г</b>."
        ),
        bullets=bullets,
        plan_payload=plan_payload,
        event_payload=event_payload,
        cards_ctx=goal,
    )


_macro_definition = CalculatorDefinition(
    slug="macros",
    title="Калькулятор БЖУ",
    steps=[
        InputStep(
            key="weight",
            prompt="Укажи текущий вес в килограммах (например, <code>68</code>):",
            error="Вес должен быть числом от 30 до 250 кг.",
            parser=_parse_float,
            validators=(_range_validator(30, 250, "Вес должен быть числом от 30 до 250 кг."),),
        ),
        ChoiceStep(
            key="goal",
            prompt="Какая цель?",
            options=[
                ChoiceOption("loss", "Жиросжигание", "loss"),
                ChoiceOption("maintain", "Поддержание", "maintain"),
                ChoiceOption("gain", "Набор массы", "gain"),
            ],
        ),
        ChoiceStep(
            key="preference",
            prompt="Какой стиль питания ближе?",
            options=[
                ChoiceOption(key, title, key) for key, (title, _, _) in _PREFERENCE_LABELS.items()
            ],
        ),
    ],
    build_result=_build_macro_result,
)


# BMI -----------------------------------------------------------------------


def _bmi_recommendations(bmi: float) -> tuple[list[str], str]:
    if bmi < 18.5:
        return ["TEO_GREEN", "OMEGA3"], "bmi_deficit"
    if bmi < 25:
        return ["T8_BLEND", "VITEN"], "bmi_norm"
    if bmi < 30:
        return ["TEO_GREEN", "T8_EXTRA"], "bmi_over"
    return ["T8_EXTRA", "TEO_GREEN"], "bmi_obese"


def _bmi_category(bmi: float) -> tuple[str, str]:
    if bmi < 18.5:
        return "дефицит", "Набираем «правильный» вес: белок, клетчатка, мягкая коррекция ЖКТ."
    if bmi < 25:
        return "норма", "Поддерживаем энергию и иммунитет."
    if bmi < 30:
        return "избыток", "Фокус на микробиом и митохондрии для устойчивого снижения массы."
    return "ожирение", "Системно: микробиом + митохондрии + режим сна/движения."


def _bmi_bullets() -> list[str]:
    return [
        "Сон 7–9 часов, ужин за 3 часа до сна.",
        "10 минут утреннего света, 30 минут ходьбы ежедневно.",
        "Клетчатка + белок в каждом приёме пищи.",
    ]


def _build_bmi_result(ctx: CalculationContext) -> CalculationResult:
    height_cm = float(ctx.data["height"])  # already validated
    weight = float(ctx.data["weight"])
    height_m = height_cm / 100.0
    bmi = round(weight / (height_m * height_m), 1)

    category, hint = _bmi_category(bmi)
    rec_codes, ctx_key = _bmi_recommendations(bmi)
    cards = _build_cards_with_overrides(rec_codes, ctx_key)
    lines = product_lines(rec_codes, ctx_key)
    bullets = _bmi_bullets()

    plan_payload = {
        "title": "План: Индекс массы тела (ИМТ)",
        "context": "bmi",
        "context_name": "Калькулятор ИМТ",
        "level": ctx_key,
        "products": rec_codes,
        "lines": lines,
        "actions": bullets,
        "notes": "Если есть ЖКТ-жалобы — начни с TEO GREEN + MOBIO и режима питания.",
        "order_url": None,
    }

    event_payload = {
        "calc": "bmi",
        "bmi": bmi,
        "category": category,
        "height": height_cm,
        "weight": weight,
    }

    headline = (
        f"ИМТ: <b>{bmi}</b> — {category}."
        "\nИМТ оценивает соотношение роста и веса, но не показывает состав тела."
        f"\n{hint}"
    )

    return CalculationResult(
        cards_title="Итог: индекс массы тела",
        cards=cards,
        headline=headline,
        bullets=bullets,
        plan_payload=plan_payload,
        event_payload=event_payload,
        cards_ctx=ctx_key,
    )


_bmi_definition = CalculatorDefinition(
    slug="bmi",
    title="Калькулятор ИМТ",
    steps=[
        InputStep(
            key="height",
            prompt="Рост в сантиметрах (например, <code>170</code>):",
            error="Рост должен быть числом в сантиметрах. Пример: <code>170</code>",
            parser=_parse_float,
            validators=(_range_validator(130, 230, "Рост должен быть в диапазоне 130–230 см."),),
        ),
        InputStep(
            key="weight",
            prompt="Вес в килограммах (например, <code>72.5</code>):",
            error="Вес должен быть числом от 30 до 250 кг.",
            parser=_parse_float,
            validators=(_range_validator(30, 250, "Вес должен быть числом от 30 до 250 кг."),),
        ),
    ],
    build_result=_build_bmi_result,
)


# Registry ------------------------------------------------------------------

CALCULATORS: dict[str, CalculatorDefinition] = {
    _water_definition.slug: _water_definition,
    _calorie_definition.slug: _calorie_definition,
    _macro_definition.slug: _macro_definition,
    _bmi_definition.slug: _bmi_definition,
}


def get_calculator(slug: str) -> CalculatorDefinition | None:
    return CALCULATORS.get(slug)


__all__ = [
    "InputStep",
    "ChoiceOption",
    "ChoiceStep",
    "Step",
    "CalculationContext",
    "CalculationResult",
    "CalculatorDefinition",
    "CALCULATORS",
    "get_calculator",
]
