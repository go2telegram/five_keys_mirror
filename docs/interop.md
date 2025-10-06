# Cross-AI Interoperability

This module enables Five Keys Bot to forward selected admin queries to external AI providers (OpenAI, Anthropic Claude, Google Gemini) and relay their answers back into recommendations.

## Configuration

Set the following environment variables in `.env`:

```env
ENABLE_CROSS_AI_COMM=true
CROSS_AI_PROVIDER=openai  # or "anthropic" / "gemini"
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GEMINI_API_KEY=...
```

Optional overrides allow you to point to alternative API endpoints or models:

```env
OPENAI_BASE=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
ANTHROPIC_BASE=https://api.anthropic.com/v1
ANTHROPIC_MODEL=claude-3-haiku-20240307
GEMINI_BASE=https://generativelanguage.googleapis.com/v1
GEMINI_MODEL=gemini-1.5-flash
```

Disable the feature at any time by setting `ENABLE_CROSS_AI_COMM=false` and restarting the bot.

## Usage

The admin-only command `/ask_external <query>` validates the prompt through the ethics validator and dispatches it to the configured provider. The bot replies with the provider response and a concise summary (also cached in memory to avoid redundant calls).

Example:

```
/ask_external оптимизируй метрики
```

## Safety & Compliance

All requests pass through `ethics.validator.ensure_allowed`, which blocks empty, overlong or sensitive prompts. Only short summaries are cached in-memory (`interop.bridge`), avoiding persistent storage of full model responses.

## Rollback

To roll back the feature:

1. Set `ENABLE_CROSS_AI_COMM=false`.
2. Remove the `interop` package if necessary.
3. Reload the application.
