import httpx

from app.config import settings
from nlp.sentiment import SentimentAnalyzer
from nlp.tone_adapter import ToneAdapter


_sentiment_analyzer = SentimentAnalyzer()
_tone_adapter = ToneAdapter()

async def ai_generate(prompt: str, sys: str = "Ты — эксперт по здоровью, пиши кратко и по делу на русском."):
    if not settings.OPENAI_API_KEY:
        return "⚠️ OpenAI API ключ не настроен."
    system_prompt = sys
    user_prompt = prompt
    if settings.ENABLE_EMOTIONAL_MODELING:
        sentiment = _sentiment_analyzer.analyse(prompt)
        system_prompt, user_prompt, _ = _tone_adapter.adapt(sys, prompt, sentiment)
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.7
    }
    try:
        async with httpx.AsyncClient(timeout=60.0, base_url=settings.OPENAI_BASE) as client:
            r = await client.post("/chat/completions", headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"⚠️ Ошибка генерации: {e}"
