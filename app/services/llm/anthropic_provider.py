import json
import logging

import anthropic

from app.services.llm.base import (
    RESULT_SCHEMA,
    SYSTEM_PROMPT,
    GrammarResult,
    build_user_prompt,
    parse_result,
)

logger = logging.getLogger(__name__)


class AnthropicChecker:
    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        self.model = model
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = anthropic.AsyncAnthropic(**kwargs)

    async def check(self, text: str, level: str, whitelist: list[str]) -> GrammarResult | None:
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
            return None

        if response.stop_reason == "refusal":
            logger.warning("Anthropic request refused")
            return None

        raw = next((block.text for block in response.content if block.type == "text"), None)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Anthropic returned non-JSON output: %.200s", raw)
            return None
        return parse_result(data)
