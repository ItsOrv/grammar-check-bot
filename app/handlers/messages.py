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


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def on_group_text(
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

    if not prefilter.should_check(
        message.text, message.entities, min_words=settings.min_words, min_chars=settings.min_chars
    ):
        logger.info("skip (prefilter) chat=%s user=%s text=%.50r", message.chat.id, user.id, message.text)
        return

    if cooldown.is_active(message.chat.id, user.id):
        logger.info("skip (cooldown) chat=%s user=%s", message.chat.id, user.id)
        return

    async with sessionmaker() as session:
        level = await repo.get_level(session, message.chat.id)
        if level == "off":
            return
        whitelist = await repo.get_whitelist(session, message.chat.id)

    logger.info("checking chat=%s user=%s level=%s text=%.80r", message.chat.id, user.id, level, message.text)
    async with llm_semaphore:
        result = await checker.check(message.text, level, whitelist)

    will_reply = should_reply(result, level, message.text, settings.confidence_threshold)
    logger.info("result chat=%s user=%s %s -> reply=%s", message.chat.id, user.id, result, will_reply)
    if not will_reply:
        return

    try:
        await message.reply(f"✏️ {result.corrected}\n\n💡 {result.explanation}")
    except Exception:
        logger.exception("Failed to send correction reply")
        return
    cooldown.mark(message.chat.id, user.id)
