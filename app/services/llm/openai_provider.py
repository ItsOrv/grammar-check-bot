import json
import logging

import openai

from app.services.llm.base import (
    RESULT_SCHEMA,
    SYSTEM_PROMPT,
    GrammarResult,
    build_user_prompt,
    parse_result,
)

logger = logging.getLogger(__name__)

# json_object mode needs the schema spelled out in the prompt itself.
_JSON_INSTRUCTIONS = (
    SYSTEM_PROMPT
    + "\n\nRespond with a single JSON object matching exactly this schema (no extra keys, no prose):\n"
    + json.dumps(RESULT_SCHEMA["properties"], indent=2)
)


class OpenAICompatibleChecker:
    """Works with any OpenAI-compatible API: DeepSeek, OpenRouter, Groq, ..."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        self.model = model
        self.client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def check(self, text: str, level: str, whitelist: list[str]) -> GrammarResult | None:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                # Reasoning models (e.g. deepseek-v4) spend ~2K tokens thinking before the JSON;
                # a low cap leaves the content empty.
                max_tokens=4096,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _JSON_INSTRUCTIONS},
                    {"role": "user", "content": build_user_prompt(text, level, whitelist)},
                ],
            )
        except openai.OpenAIError as e:
            logger.warning("LLM API error: %s", e)
            return None

        raw = response.choices[0].message.content if response.choices else None
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM returned non-JSON output: %.200s", raw)
            return None
        return parse_result(data)
