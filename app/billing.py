"""Shared billing logic: who pays for a given message.

In a private chat the user pays for themselves. In a group, the person who added
the bot (ChatSettings.owner_id, falling back to the group creator) pays for
everything. Both passive grammar checking and the /t command use this so they
charge the same wallet.
"""
import logging
from dataclasses import dataclass

from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.database import repo
from app.database.models import Wallet

logger = logging.getLogger(__name__)


@dataclass
class Payer:
    user_id: int | None
    wallet: Wallet | None
    problem: str | None = None  # None | "no_owner" | "no_wallet"
    granted: bool = False        # free credit was just handed out (private only)


async def resolve_owner(message: Message, sessionmaker: async_sessionmaker) -> int | None:
    """Who pays for this group: the adder, falling back to the creator (cached)."""
    async with sessionmaker() as session:
        owner_id = await repo.get_owner(session, message.chat.id)
    if owner_id is not None:
        return owner_id
    try:
        admins = await message.bot.get_chat_administrators(message.chat.id)
        creator = next((a for a in admins if a.status == "creator"), None)
    except Exception:
        creator = None
    if creator and creator.user and not creator.user.is_bot:
        async with sessionmaker() as session:
            await repo.set_owner(session, message.chat.id, creator.user.id)
        return creator.user.id
    return None


async def resolve_payer(message: Message, sessionmaker: async_sessionmaker, settings: Settings) -> Payer:
    """Figure out whose wallet to charge for this message."""
    if message.chat.type == "private":
        user = message.from_user
        async with sessionmaker() as session:
            wallet, granted = await repo.get_or_create_wallet(
                session, user.id, user.full_name, settings.free_credit_toman, started=True
            )
        return Payer(user.id, wallet, None, granted)

    owner_id = await resolve_owner(message, sessionmaker)
    if owner_id is None:
        return Payer(None, None, "no_owner")
    async with sessionmaker() as session:
        wallet = await repo.get_wallet(session, owner_id)
    # Having a wallet means the owner has engaged with the bot (and got free credit).
    if wallet is None:
        return Payer(None, None, "no_wallet")
    return Payer(owner_id, wallet, None)
