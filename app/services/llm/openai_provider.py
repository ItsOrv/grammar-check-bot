import json
import logging

import openai

from app.services.llm.base import (
    RESULT_SCHEMA,
    SYSTEM_PROMPT,
    TRANSLATE_SYSTEM,
    GrammarResult,
    Usage,
    build_translate_prompt,
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


def _usage(response) -> Usage:
    u = getattr(response, "usage", None)
    if not u:
        return Usage()
    return Usage(prompt_tokens=u.prompt_tokens or 0, completion_tokens=u.completion_tokens or 0)


class OpenAICompatibleChecker:
    """Works with any OpenAI-compatible API: DeepSeek, OpenRouter, Groq, ..."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        self.model = model
        self.client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def check(self, text: str, level: str, whitelist: list[str]) -> tuple[GrammarResult | None, Usage]:
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
            return None, Usage()

        usage = _usage(response)
        raw = response.choices[0].message.content if response.choices else None
        if not raw:
            return None, usage
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM returned non-JSON output: %.200s", raw)
            return None, usage
        return parse_result(data), usage

    async def translate(self, text: str, level: str) -> tuple[str | None, Usage]:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=2048,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": TRANSLATE_SYSTEM},
                    {"role": "user", "content": build_translate_prompt(text, level)},
                ],
            )
        except openai.OpenAIError as e:
            logger.warning("LLM API error (translate): %s", e)
            return None, Usage()

        usage = _usage(response)
        raw = response.choices[0].message.content if response.choices else None
        return (raw.strip() if raw and raw.strip() else None), usage
