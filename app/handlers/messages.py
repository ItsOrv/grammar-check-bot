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

logger = logging.getLogger(__name__)

router = Router(name="messages")


async def _over_limit(message: Message, settings: Settings, sessionmaker: async_sessionmaker, user_id: int) -> bool:
    """True if the user blew through their spending cap. Tells them once, then stays quiet."""
    async with sessionmaker() as session:
        spent = await repo.get_user_total_cost(session, user_id)
        if spent < settings.usage_limit_usd:
            return False
        already_told = await repo.is_limit_notified(session, message.chat.id, user_id)
        if not already_told:
            await repo.mark_limit_notified(session, message.chat.id, user_id)
    if not already_told:
        try:
            await message.reply(
                f"😅 You've hit your usage limit (${settings.usage_limit_usd:.2f} of API credit), "
                "so I'll stop checking your messages for now."
            )
        except Exception:
            logger.exception("Failed to send limit notice")
    return True


@router.message(F.chat.type.in_({"group", "supergroup", "private"}), F.text)
async def on_text(
    message: Message,
    settings: Settings,
    sessionmaker: async_sessionmaker,
    checker: GrammarChecker,
    cooldown: Cooldown,
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

    if await _over_limit(message, settings, sessionmaker, user.id):
        logger.info("skip (limit) chat=%s user=%s", message.chat.id, user.id)
        return

    logger.info("checking chat=%s user=%s level=%s text=%.80r", message.chat.id, user.id, level, message.text)
    async with llm_semaphore:
        result, usage = await checker.check(message.text, level, whitelist)

    will_reply = should_reply(result, level, message.text, settings.confidence_threshold)
    cost = usage.cost(settings.price_input_per_million, settings.price_output_per_million)
    logger.info(
        "result chat=%s user=%s %s cost=$%.5f -> reply=%s", message.chat.id, user.id, result, cost, will_reply
    )

    async with sessionmaker() as session:
        await repo.record_usage(
            session,
            message.chat.id,
            user.id,
            user.full_name,
            usage.prompt_tokens,
            usage.completion_tokens,
            cost,
            replied=will_reply,
        )

    if not will_reply:
        return

    try:
        await message.reply(f"✏️ {result.corrected}\n\n💡 {result.explanation}")
    except Exception:
        logger.exception("Failed to send correction reply")
        return
    cooldown.mark(message.chat.id, user.id)
