import asyncio
import logging

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.database import repo
from app.services import prefilter
from app.services.cooldown import Cooldown
from app.services.llm import GrammarChecker, should_reply
from app.services.rate import RateProvider, cost_to_toman

logger = logging.getLogger(__name__)

router = Router(name="messages")


async def _check_wallet(message: Message, settings: Settings, sessionmaker: async_sessionmaker, user) -> bool:
    """Make sure the user has a wallet (with free credit) and some balance left.
    Returns True if they're good to go."""
    async with sessionmaker() as session:
        wallet, granted = await repo.get_or_create_wallet(
            session, user.id, user.full_name, settings.free_credit_toman
        )
        balance = wallet.balance_toman
        low_notified = wallet.low_balance_notified

    if granted and message.chat.type == "private":
        try:
            await message.answer(
                f"🎁 {int(settings.free_credit_toman):,} تومان اعتبار رایگان بهت دادم. "
                "هر وقت تموم شد می‌تونی با /wallet شارژ کنی."
            )
        except Exception:
            logger.exception("failed to send free-credit notice")

    if balance > 0:
        return True

    if not low_notified:
        async with sessionmaker() as session:
            await repo.mark_low_balance_notified(session, user.id)
        try:
            await message.reply(
                "💸 موجودی کیف پولت تموم شده. برای ادامه با /wallet شارژ کن."
            )
        except Exception:
            logger.exception("failed to send low-balance notice")
    return False


@router.message(F.chat.type.in_({"group", "supergroup", "private"}), F.text)
async def on_text(
    message: Message,
    settings: Settings,
    sessionmaker: async_sessionmaker,
    checker: GrammarChecker,
    cooldown: Cooldown,
    rate: RateProvider,
    llm_semaphore: asyncio.Semaphore,
):
    user = message.from_user
    if not user or user.is_bot or message.via_bot:
        return

    is_private = message.chat.type == "private"

    if not prefilter.should_check(
        message.text, message.entities, min_words=settings.min_words, min_chars=settings.min_chars
    ):
        logger.info("skip (prefilter) chat=%s user=%s text=%.50r", message.chat.id, user.id, message.text)
        return

    # In a 1:1 chat there's nobody to spam, so don't rate-limit the user against themselves.
    if not is_private and cooldown.is_active(message.chat.id, user.id):
        logger.info("skip (cooldown) chat=%s user=%s", message.chat.id, user.id)
        return

    async with sessionmaker() as session:
        if not await repo.is_enabled(session, message.chat.id):
            return
        level = await repo.get_level(session, message.chat.id)
        if level == "off":
            return
        whitelist = await repo.get_whitelist(session, message.chat.id)
        model = await repo.get_model(session, message.chat.id, settings.llm_model)

    if not await _check_wallet(message, settings, sessionmaker, user):
        logger.info("skip (no balance) chat=%s user=%s", message.chat.id, user.id)
        return

    logger.info("checking chat=%s user=%s level=%s model=%s", message.chat.id, user.id, level, model)
    async with llm_semaphore:
        result, usage = await checker.check(message.text, level, whitelist, model=model)

    will_reply = should_reply(result, level, message.text, settings.confidence_threshold)
    cost_usd = usage.cost(settings.price_input_per_million, settings.price_output_per_million)
    toman = cost_to_toman(cost_usd, await rate.get_rate(), settings.price_markup)
    logger.info(
        "result chat=%s user=%s %s cost=$%.5f/%dT -> reply=%s",
        message.chat.id, user.id, result, cost_usd, toman, will_reply,
    )

    async with sessionmaker() as session:
        await repo.record_usage(
            session, message.chat.id, user.id, user.full_name,
            usage.prompt_tokens, usage.completion_tokens, cost_usd, replied=will_reply,
        )
        if toman > 0:
            await repo.deduct(session, user.id, toman)

    if not will_reply:
        return

    try:
        await message.reply(f"✏️ {result.corrected}\n\n💡 {result.explanation}")
    except Exception:
        logger.exception("Failed to send correction reply")
        return
    cooldown.mark(message.chat.id, user.id)
