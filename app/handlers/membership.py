import logging

from aiogram import Router
from aiogram.types import ChatMemberUpdated
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import repo

logger = logging.getLogger(__name__)

router = Router(name="membership")

GROUP_GREETING = (
    "Hi! I check English grammar here and reply only when something is genuinely wrong.\n\n"
    "The person who added me covers this group's usage from their wallet, so make sure "
    "you've started me in private (/start) and have some balance.\n\n"
    "Admins can use /settings to pick a strictness level."
)

_IN = ("member", "administrator")
_OUT = ("left", "kicked")


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated, sessionmaker: async_sessionmaker):
    old, new = event.old_chat_member.status, event.new_chat_member.status
    logger.info(
        "membership change chat=%s (%r, %s) %s -> %s by user=%s",
        event.chat.id, event.chat.title, event.chat.type, old, new,
        event.from_user.id if event.from_user else None,
    )
    if event.chat.type in ("group", "supergroup") and old in _OUT + ("restricted",) and new in _IN:
        # Whoever added the bot owns (and pays for) this group.
        if event.from_user and not event.from_user.is_bot:
            async with sessionmaker() as session:
                await repo.set_owner(session, event.chat.id, event.from_user.id)
        try:
            await event.bot.send_message(event.chat.id, GROUP_GREETING)
        except Exception:
            logger.exception("Failed to send group greeting")
