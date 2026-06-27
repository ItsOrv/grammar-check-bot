from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    admin_ids: str = ""  # comma-separated user IDs that can always run settings commands

    llm_provider: Literal["anthropic", "openai"] = "openai"
    llm_model: str = "deepseek-chat"
    llm_api_key: str
    llm_base_url: str | None = None
    # Models a user can pick from the menu. Format: "id:label,id:label".
    available_models: str = "deepseek-v4-flash:Flash (cheaper),deepseek-v4-pro:Pro (sharper)"

    db_path: str = "data/bot.db"

    cooldown_seconds: int = 120
    min_words: int = 3
    min_chars: int = 12
    confidence_threshold: float = 0.8
    max_concurrent_llm: int = 5

    # Token prices (per 1M tokens) so we can work out the raw USD cost of a call.
    price_input_per_million: float = 0.07
    price_output_per_million: float = 0.28

    # --- Wallet / billing (everything the user sees is in Toman) ---
    # Free credit handed out the first time someone starts the bot.
    free_credit_toman: int = 50_000
    # Markup on the raw API cost. 1.40 means we charge 40% over what it costs us.
    price_markup: float = 1.40
    # USD -> Toman. Pulled live from rate_api_url; this is the fallback if that fails.
    usd_to_toman_fallback: float = 170_000.0
    rate_api_url: str = "https://api.wallex.ir/v1/markets"
    rate_ttl_seconds: int = 600
    # Preset top-up amounts (Toman) shown as buttons.
    topup_presets_toman: str = "50000,100000,200000"
    # Upper bound on a single top-up, so a typo can't create an absurd order.
    max_topup_toman: int = 50_000_000
    # Crypto processors reject tiny invoices; refuse a crypto top-up whose USD value
    # falls below this so the user gets a clear message instead of a failed invoice.
    min_crypto_topup_usd: float = 1.0

    # --- Card to card (manual, admin-approved) ---
    card_number: str = ""
    card_holder: str = ""

    # --- Crypto via NOWPayments ---
    nowpayments_api_key: str = ""
    nowpayments_ipn_secret: str = ""
    nowpayments_ipn_url: str = ""  # public https URL NOWPayments will call back
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8080

    # Premium (custom) emoji shown in message text. Format: "key:custom_emoji_id,..."
    # Grab the IDs by sending the emoji to the bot with /emojiid (admin only).
    # Keys used: wave, wallet, usage, model, settings, stats.
    premium_emoji: str = ""

    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def admin_id_set(self) -> set[int]:
        return {int(x) for x in self.admin_ids.split(",") if x.strip().isdigit()}

    @property
    def topup_presets(self) -> list[int]:
        return [int(x) for x in self.topup_presets_toman.split(",") if x.strip().isdigit()]

    @property
    def premium_emoji_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for part in self.premium_emoji.split(","):
            key, _, eid = part.strip().partition(":")
            if key.strip() and eid.strip().isdigit():
                out[key.strip()] = eid.strip()
        return out

    @property
    def model_choices(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for part in self.available_models.split(","):
            part = part.strip()
            if not part:
                continue
            mid, _, label = part.partition(":")
            out.append((mid.strip(), (label.strip() or mid.strip())))
        return out
