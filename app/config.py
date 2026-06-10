from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    admin_ids: str = ""  # comma-separated user IDs that can always run settings commands

    llm_provider: Literal["anthropic", "openai"] = "openai"
    llm_model: str = "deepseek-chat"
    llm_api_key: str
    llm_base_url: str | None = None

    db_path: str = "data/bot.db"

    cooldown_seconds: int = 120
    min_words: int = 3
    min_chars: int = 12
    confidence_threshold: float = 0.8
    max_concurrent_llm: int = 5

    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def admin_id_set(self) -> set[int]:
        return {int(x) for x in self.admin_ids.split(",") if x.strip().isdigit()}
