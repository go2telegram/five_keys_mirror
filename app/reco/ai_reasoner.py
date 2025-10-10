import json
import re
from pathlib import Path

try:  # pragma: no cover - optional dependency
    from jinja2 import Template  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback renderer
    class Template:
        """Minimal template engine supporting {{ var }} and {{ var | tojson }}."""

        def __init__(self, text: str) -> None:
            self._text = text

        def render(self, **context):  # noqa: ANN003 - dynamic mapping
            def _resolve(expr: str):
                parts = [part.strip() for part in expr.split(".") if part.strip()]
                value = context
                for part in parts:
                    if isinstance(value, dict):
                        value = value.get(part, "")
                    else:
                        value = getattr(value, part, "")
                return value

            def _replace(match: re.Match[str]) -> str:
                expr = match.group(1).strip()
                if "|" in expr:
                    base, _, filt = expr.partition("|")
                    if filt.strip() == "tojson":
                        return json.dumps(_resolve(base), ensure_ascii=False)
                value = _resolve(expr)
                if isinstance(value, (dict, list)):
                    return json.dumps(value, ensure_ascii=False)
                return str(value)

            return re.sub(r"{{\s*(.+?)\s*}}", _replace, self._text)

from app.reco.engine import get_reco  # твой rule-based top-N
from app.repo.quiz_results import get_user_quiz_results
from app.repo.calculators import get_user_calcs
from app.repo.user_profile import get_user_profile
from app.utils.cards import build_order_link

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
LANG = lambda prof: ("en" if (prof and prof.get("lang") == "en") else "ru")


def _load_prompt(lang: str) -> str:
    name = f"plan_{lang}.md"
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


async def build_ai_plan(user_id: int, horizon: str = "7d") -> str:
    profile = await get_user_profile(user_id)
    quizzes = await get_user_quiz_results(user_id)
    calculators = await get_user_calcs(user_id)

    # Получаем top-N из rule-based
    reco_items = await get_reco(user_id, limit=5, verbose=True)  # [{id,title,utm_category,why,buy_url}, ...]

    # Подготовим контекст для LLM
    lang = LANG(profile)
    prompt_tpl = Template(_load_prompt(lang))
    catalog_subset = [
        {
            "id": x["id"],
            "title": x["title"],
            "utm_category": x.get("utm_category", "catalog"),
            "why": x.get("why", ""),
            "buy_url": build_order_link(x["id"], x.get("utm_category", "catalog")),
        }
        for x in reco_items
    ]
    rendered = prompt_tpl.render(
        profile=profile or {},
        quizzes=quizzes or [],
        calculators=calculators or [],
        tags=list({t for x in reco_items for t in x.get("tags", [])}),
        catalog=catalog_subset,
    )

    # Вызов LLM (через OpenAI / твой клиент). Псевдокод:
    # text = await call_openai(rendered, model=settings.AI_PLAN_MODEL)
    # return text
    return rendered  # временно, чтобы тесты шли без сети
