import json
import logging

import anthropic

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


def _usage(response) -> Usage:
    u = getattr(response, "usage", None)
    if not u:
        return Usage()
    return Usage(
        prompt_tokens=getattr(u, "input_tokens", 0) or 0,
        completion_tokens=getattr(u, "output_tokens", 0) or 0,
    )


class AnthropicChecker:
    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        self.model = model
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = anthropic.AsyncAnthropic(**kwargs)

    async def check(self, text: str, level: str, whitelist: list[str]) -> tuple[GrammarResult | None, Usage]:
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_prompt(text, level, whitelist)}],
                output_config={"format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
            )
        except anthropic.APIError as e:
            logger.warning("Anthropic API error: %s", e)
            return None, Usage()

        usage = _usage(response)
        if response.stop_reason == "refusal":
            logger.warning("Anthropic request refused")
            return None, usage

        raw = next((block.text for block in response.content if block.type == "text"), None)
        if raw is None:
            return None, usage
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Anthropic returned non-JSON output: %.200s", raw)
            return None, usage
        return parse_result(data), usage

    async def translate(self, text: str, level: str) -> tuple[str | None, Usage]:
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=TRANSLATE_SYSTEM,
                messages=[{"role": "user", "content": build_translate_prompt(text, level)}],
            )
        except anthropic.APIError as e:
            logger.warning("Anthropic API error (translate): %s", e)
            return None, Usage()

        usage = _usage(response)
        if response.stop_reason == "refusal":
            logger.warning("Anthropic translate request refused")
            return None, usage

        raw = next((block.text for block in response.content if block.type == "text"), None)
        return (raw.strip() if raw and raw.strip() else None), usage
