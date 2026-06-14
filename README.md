# Grammar Check Bot

A Telegram bot that reads every text message in an English-speaking group, checks it for grammar, spelling, and writing mistakes with an LLM, and replies with a correction **only when something is genuinely wrong**. No nitpicking — if the message is fine or the model isn't sure, the bot stays silent.

## Features

- **Reads all group messages** (not just commands or mentions)
- **Per-group strictness levels**, persisted across restarts:
  - `/strict` — formal English; punctuation, capitalization, apostrophes all count
  - `/normal` — standard grammar checked, minor punctuation/capitalization ignored
  - `/casual` — slang and abbreviations (tbh, btw, gonna, ...) are fine; only meaning-breaking errors get flagged
  - `/off` — temporarily disable checking
- `/status` — show the active level, whitelist size, and model
- `/whitelist add|remove <word>` — terms the bot must never flag (per group)
- **Cheap pre-filter** before any LLM call: skips commands, short messages, emoji-only, links, code blocks, and non-English text
- **Per-user cooldown** so nobody gets corrected repeatedly
- **Structured LLM output** (severity 0–5 + confidence) with a per-level reply threshold; the model is explicitly told to stay silent when unsure
- **Two LLM backends** behind one interface: any **OpenAI-compatible** API (DeepSeek, OpenRouter, Groq, ...) or the **Anthropic API**
- Settings commands are restricted to **group admins**

## Setup

### 1. Create the bot

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. **Important:** disable group privacy so the bot can read all messages:
   `/setprivacy` → select your bot → **Disable**.
3. Add the bot to your group.

### 2. Configure

```bash
cp .env.example .env
# edit .env: BOT_TOKEN, LLM_API_KEY, and provider/model
```

For DeepSeek (default):

```env
LLM_PROVIDER=openai
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com
```

For Anthropic:

```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-opus-4-8
LLM_BASE_URL=
```

### 3. Run

```bash
pip install -r requirements.txt
python -m app.main
```

Or with Docker:

```bash
docker build -t grammar-check-bot .
docker run -d --env-file .env -v $(pwd)/data:/app/data grammar-check-bot
```

## Testing

```bash
pip install pytest
pytest

# one-off LLM smoke test (needs LLM_API_KEY in .env):
python -m scripts.try_llm "she go to school yesterday"
```

## How the reply decision works

The LLM returns structured JSON: `has_issues`, `severity` (0–5), `confidence` (0–1), `corrected`, `explanation`. The bot replies only when all of these hold:

- `has_issues` is true
- `severity` ≥ the level threshold (strict: 1, normal: 3, casual: 4)
- `confidence` ≥ 0.8 (configurable)
- the corrected text actually differs from the original

Group whitelist terms are injected into the prompt so the model never flags them.
