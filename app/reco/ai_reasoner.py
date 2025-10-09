"""AI helpers: quiz tips and weekly plan prompt renderer."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable

try:  # pragma: no cover - optional dependency
    from jinja2 import Environment, Template
except ModuleNotFoundError:  # pragma: no cover - fallback to minimal templating
    Environment = None  # type: ignore[assignment]
    Template = None  # type: ignore[assignment]

from app.reco.engine import get_reco
from app.repo.calculators import get_user_calcs
from app.repo.quiz_results import get_user_quiz_results
from app.repo.user_profile import get_user_profile
from app.utils.cards import build_order_link

_PROMPTS_DIR = Path("app/reco/prompts")
_AI_PLAN_MODEL = os.getenv("AI_PLAN_MODEL", "gpt-4o-mini")


def _json_default(value):  # noqa: ANN001 - helper for json dumps
    if isinstance(value, (set, tuple)):
        return list(value)
    return str(value)


if Environment is None or Template is None:  # pragma: no cover - fallback path for tests
    class Template:  # type: ignore[override]
        def __init__(self, text: str) -> None:
            self._text = text

        def render(self, **context: object) -> str:
            result = self._text
            for key, value in context.items():
                json_placeholder = f"{{{{ {key} | tojson }}}}"
                result = result.replace(
                    json_placeholder,
                    json.dumps(value, ensure_ascii=False, default=_json_default),
                )
                simple_placeholder = f"{{{{ {key} }}}}"
                result = result.replace(simple_placeholder, str(value))
            return result

    class Environment:  # type: ignore[override]
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002
            self.filters: dict[str, object] = {}

        def from_string(self, text: str) -> Template:
            return Template(text)


_env = Environment(autoescape=False, trim_blocks=False, lstrip_blocks=False)
_env.filters["tojson"] = lambda value: json.dumps(  # noqa: E731 - short lambda for filter registration
    value,
    ensure_ascii=False,
    default=_json_default,
)


def _load_template(name: str) -> Template:
    path = _PROMPTS_DIR / name
    if not path.exists():  # pragma: no cover - defensive guard for deployment issues
        raise FileNotFoundError(f"Prompt template {name!r} is missing")
    return _env.from_string(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def _prompt_template(lang: str) -> Template:
    return _load_template(f"plan_{lang}.md")


def _resolve_lang(profile: dict | None) -> str:
    if profile and str(profile.get("lang")).lower() == "en":
        return "en"
    return "ru"


async def build_ai_plan(user_id: int, horizon: str = "7d") -> str:
    """Render the AI plan prompt for the provided user."""

    del horizon  # horizon reserved for future use
    profile = await get_user_profile(user_id)
    quizzes = await get_user_quiz_results(user_id)
    calculators = await get_user_calcs(user_id)

    reco_items = await get_reco(user_id, limit=5, verbose=True)

    lang = _resolve_lang(profile)
    template = _prompt_template(lang)
    catalog_subset = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "utm_category": item.get("utm_category", "catalog"),
            "why": item.get("why", ""),
            "tags": list(item.get("tags") or []),
            "buy_url": build_order_link(item.get("id"), item.get("utm_category", "catalog")),
        }
        for item in reco_items
        if item.get("id") and item.get("title")
    ]
    tags = sorted({tag for item in catalog_subset for tag in item.get("tags", []) if tag})

    rendered = template.render(
        profile=profile or {},
        quizzes=quizzes or [],
        calculators=calculators or [],
        tags=tags,
        catalog=catalog_subset,
        model=_AI_PLAN_MODEL,
    )

    # Placeholder: the rendered prompt is returned for offline tests.
    # Real deployment should call the LLM and return its response instead.
    return rendered


_TAG_TIPS: dict[str, str] = {
    "adaptogens": "Попробуй мягкие адаптогены утром — они сгладят стресс и добавят устойчивой энергии.",
    "b_complex": "Курс витаминов группы B поддержит нервы и метаболизм, особенно в период нагрузок.",
    "brain_coffee": "Тёплый напиток с Brain Coffee или МСТ даёт фокус без резких скачков энергии.",
    "caffeine": "Оставь максимум 1–2 чашки кофе и чередуй с водой или матча — нервная система скажет спасибо.",
    "collagen": "Коллаген с витамином C днём помогает коже и связкам восстанавливаться быстрее.",
    "digest_support": "Добавь лёгкие ферменты после плотных приёмов пищи, чтобы снять тяжесть и поддержать ЖКТ.",
    "electrolytes": "Стакан воды с электролитами утром удержит энергию и снизит усталость к вечеру.",
    "energy": "Делай динамичные перерывы каждые 90 минут — кровь разгоняется и тонус возвращается сразу.",
    "fiber": "Держи норму клетчатки 25–30 г в день: овощи, ягоды или TÉO Green стабилизируют микробиом.",
    "glycine": "Глицин или тёплая ванна на ночь помогают нервной системе переключиться и легче заснуть.",
    "gut": "Ежедневная порция ферментированных продуктов и пребиотиков поддерживает ЖКТ  иммунитет.",
    "immunity": "Следи за витамином D3 и режимом сна — иммунитет заметно крепнет уже через пару недель.",
    "magnesium": "Вечерний магний с витамином B6 снимает зажимы и улучшает глубину сна.",
    "mct": "Ложка МСТ перед завтраком даёт ровную энергию без скачков сахара и перегруза кофеином.",
    "mitochondria": "Утренний свет + короткая зарядка включают митохондрии и дают больше живой энергии.",
    "mitup": "Курс MIT UP усиливает митохондрии — сочетай с белком и регулярным сном для максимального эффекта.",
    "ok": "Ты уже держишь базу — продолжай режим сна, воды и движения, чтобы удержать результат.",
    "overstim": "Сделай детокс от стимуляторов на 5–7 дней и добавь дыхательные практики для разгрузки нервной системы.",
    "probiotic": "Пробиотики вместе с пребиотической клетчаткой укрепят микробиом и повысят устойчивость к стрессу.",
    "recovery": "Запланируй 1–2 дня активного восстановления с растяжкой и ранним сном — тело быстрее откликнется.",
    "reduce_caffeine": "Меняй вторую чашку кофе на травяной чай или матча — кортизол перестанет скакать.",
    "sleep_calm": "Выключай яркие экраны за час до сна и оставляй только приглушённый свет — нервная система успокаивается быстрее.",
    "sleep_focus": "Попробуй дыхание 4-7-8 и затемнение спальни — глубина сна вырастет уже через несколько вечеров.",
    "sleep_ok": "Продолжай держать стабильный график сна, даже в выходные — так организм восстанавливается быстрее.",
    "sleep_support": "Вечерняя прогулка и лёгкий ужин за 3 часа до сна заметно улучшают восстановление.",
    "steady": "Хороший ритм! Сохраняй прогулки, белок и гидратацию — это поддержит иммунитет круглый год.",
    "stress": "Делай короткие паузы с дыханием «коробочка» и разминкой — стресс уходит мягче.",
    "stress_support": "Дневник благодарности и дыхание 4-4-4-4 вечером снижают кортизол и выравнивают настроение.",
    "support": "Вода утром, белковый завтрак и 30 минут движения — базовый набор для высокой энергии.",
    "theanine": "L-теанин с зелёным чаем смягчает действие кофеина и помогает держать фокус.",
    "tonus": "Контрастный душ и лёгкая зарядка утром помогут просыпаться без тяжести.",
    "vitamin_d3": "Проверь уровень витамина D3 и держи поддерживающую дозу — он влияет на иммунитет и настроение.",
    "vitamins": "Курс сбалансированных витаминов в сезон нагрузок помогает не выгорать.",
    "watch": "Прислушивайся к сигналам тела и закладывай день отдыха, если чувствуешь накопившуюся усталость.",
}


_QUIZ_DEFAULT_TAG: dict[str, str] = {
    "energy": "support",
    "immunity": "immunity",
    "gut": "gut",
    "sleep": "sleep_support",
    "stress": "stress",
    "deficits": "vitamins",
    "skin_joint": "collagen",
}


def _normalize(tag: str) -> str:
    return tag.strip().lower().replace("-", "_")


async def ai_tip_for_quiz(quiz_name: str, tags: Iterable[str] | None) -> str | None:
    """Return a short motivational tip for the finished quiz."""

    normalized = [_normalize(tag) for tag in (tags or []) if tag]
    for tag in normalized:
        tip = _TAG_TIPS.get(tag)
        if tip:
            return tip

    fallback_tag = _QUIZ_DEFAULT_TAG.get(quiz_name)
    if fallback_tag:
        return _TAG_TIPS.get(fallback_tag)
    return None


__all__ = ["ai_tip_for_quiz", "build_ai_plan"]
