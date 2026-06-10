from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ChatSettings, WhitelistEntry

DEFAULT_LEVEL = "normal"
LEVELS = ("strict", "normal", "casual", "off")


async def get_level(session: AsyncSession, chat_id: int) -> str:
    settings = await session.get(ChatSettings, chat_id)
    return settings.level if settings else DEFAULT_LEVEL


async def set_level(session: AsyncSession, chat_id: int, level: str) -> None:
    settings = await session.get(ChatSettings, chat_id)
    if settings:
        settings.level = level
    else:
        session.add(ChatSettings(chat_id=chat_id, level=level))
    await session.commit()


async def get_whitelist(session: AsyncSession, chat_id: int) -> list[str]:
    rows = await session.scalars(
        select(WhitelistEntry.word).where(WhitelistEntry.chat_id == chat_id).order_by(WhitelistEntry.word)
    )
    return list(rows)


async def add_whitelist_words(session: AsyncSession, chat_id: int, words: list[str]) -> list[str]:
    existing = set(await get_whitelist(session, chat_id))
    added = []
    for word in words:
        word = word.strip().lower()
        if word and word not in existing:
            session.add(WhitelistEntry(chat_id=chat_id, word=word))
            existing.add(word)
            added.append(word)
    await session.commit()
    return added


async def remove_whitelist_word(session: AsyncSession, chat_id: int, word: str) -> bool:
    result = await session.execute(
        delete(WhitelistEntry).where(
            WhitelistEntry.chat_id == chat_id,
            WhitelistEntry.word == word.strip().lower(),
        )
    )
    await session.commit()
    return result.rowcount > 0
