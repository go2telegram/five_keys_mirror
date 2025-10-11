"""Lightweight heuristic helpers for Premium flows."""

from __future__ import annotations

import datetime as dt
from typing import Iterable

from app.services.weekly_ai_plan import PlanPayload, build_ai_plan

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
    "gut": "Ежедневная порция ферментированных продуктов и пребиотиков поддерживает ЖКТ и иммунитет.",
    "immunity": "Следи за витамином D3 и режимом сна — иммунитет заметно крепнет уже через пару недель.",
    "magnesium": "Вечерний магний с витамином B6 снимает зажимы и улучшает глубину сна.",
    "mct": "Ложка МСТ перед завтраком даёт ровную энергию без скачков сахара и перегруза кофеином.",
    "mitochondria": "Утренний свет + короткая зарядка включают митохондрии и дают больше живой энергии.",
    "mitup": "Курс MIT UP усиливает митохондрии — сочетай с белком и регулярным сном для максимального эффекта.",
    "ok": "Ты уже держишь базу — продолжай режим сна, воды и движения, чтобы удержать результат.",
    "overstim": (
        "Сделай детокс от стимуляторов на 5–7 дней и добавь дыхательные практики для разгрузки нервной системы."
    ),
    "probiotic": "Пробиотики вместе с пребиотической клетчаткой укрепят микробиом и повысят устойчивость к стрессу.",
    "recovery": "Запланируй 1–2 дня активного восстановления с растяжкой и ранним сном — тело быстрее откликнется.",
    "reduce_caffeine": "Меняй вторую чашку кофе на травяной чай или матча — кортизол перестанет скакать.",
    "sleep_calm": (
        "Выключай яркие экраны за час до сна и оставляй только приглушённый свет — "
        "нервная система успокаивается быстрее."
    ),
    "sleep_focus": "Попробуй дыхание 4-7-8 и затемнение спальни — глубина сна вырастет уже через несколько вечеров.",
    "sleep_ok": "Продолжай держать стабильный график сна, даже в выходные — так организм восстанавливается быстрее.",
    "sleep_support": "Вечерняя прогулка и лёгкий ужин за 3 часа до сна заметно улучшает восстановление.",
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


_GOAL_FOCUS = {
    "energy": ("энергии", "динамичный"),
    "sleep": ("качественного сна", "успокаивающий"),
    "stress": ("устойчивости к стрессу", "поддерживающий"),
    "detox": ("мягкого восстановления", "бережный"),
    "recovery": ("восстановления", "спокойный"),
}


def _profile_from_diff(diff: dict | None) -> dict:
    diff = diff or {}
    goals = [str(item) for item in diff.get("goals", [])]
    focus = diff.get("focus")
    tone = diff.get("tone")

    for goal in goals:
        mapped = _GOAL_FOCUS.get(goal)
        if mapped:
            focus = focus or mapped[0]
            tone = tone or mapped[1]

    if not focus:
        focus = "энергии"
    if not tone:
        tone = "спокойный" if "stress" in goals else "динамичный"

    profile = {
        "goals": goals,
        "focus": focus,
        "tone": tone,
        "source": diff.get("source", "edit"),
    }
    if diff.get("need_short"):
        profile["need_short"] = True
    tags = diff.get("tags")
    if isinstance(tags, Iterable) and not isinstance(tags, (str, bytes)):
        profile["tags"] = [str(tag) for tag in tags]
    return profile


async def edit_ai_plan(user_id: int, diff_json: dict | None) -> PlanPayload:
    """Rebuild the AI plan applying overrides from user-selected goals."""

    profile = _profile_from_diff(diff_json)
    plan = await build_ai_plan(profile)
    if plan.plan_json is not None:
        payload = dict(plan.plan_json)
        payload["edited_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        payload["edited_by"] = user_id
        payload["diff"] = diff_json or {}
        payload["source"] = "edit"
        plan.plan_json = payload
    return plan


__all__ = ["ai_tip_for_quiz", "edit_ai_plan", "PlanPayload", "build_ai_plan"]
