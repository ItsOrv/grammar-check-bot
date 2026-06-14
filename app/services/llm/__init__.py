from app.config import Settings
from app.services.llm.base import GrammarChecker, GrammarResult, Usage, should_reply

__all__ = ["GrammarChecker", "GrammarResult", "Usage", "create_checker", "should_reply"]


def create_checker(settings: Settings) -> GrammarChecker:
    if settings.llm_provider == "anthropic":
        from app.services.llm.anthropic_provider import AnthropicChecker

        return AnthropicChecker(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
        )
    from app.services.llm.openai_provider import OpenAICompatibleChecker

    return OpenAICompatibleChecker(
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
    )
