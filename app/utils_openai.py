import httpx
from app.config import settings

async def ai_generate(prompt: str, sys: str = "Ты — эксперт по здоровью, пиши кратко и по делу на русском."):
    if not settings.OPENAI_API_KEY:
        return "⚠️ OpenAI API ключ не настроен."
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": sys},
            {"role": "user", "content": prompt}
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
