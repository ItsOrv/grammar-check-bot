import logging

from aiogram import Router
from aiogram.types import ChatMemberUpdated

logger = logging.getLogger(__name__)

router = Router(name="membership")

GROUP_GREETING = (
    "👋 Hi! I'll quietly check English grammar here and reply only when "
    "something is genuinely wrong.\n\n"
    "Admins: use /settings to pick a strictness level."
)

_IN = ("member", "administrator")
_OUT = ("left", "kicked")


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated):
    old, new = event.old_chat_member.status, event.new_chat_member.status
    logger.info(
        "membership change chat=%s (%r, %s) %s -> %s by user=%s",
        event.chat.id, event.chat.title, event.chat.type, old, new,
        event.from_user.id if event.from_user else None,
    )
    if event.chat.type in ("group", "supergroup") and old in _OUT + ("restricted",) and new in _IN:
        try:
            await event.bot.send_message(event.chat.id, GROUP_GREETING)
        except Exception:
            logger.exception("Failed to send group greeting")
