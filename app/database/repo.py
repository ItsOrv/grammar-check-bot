from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ChatSettings, Usage, WhitelistEntry

DEFAULT_LEVEL = "normal"
LEVELS = ("strict", "normal", "casual", "off")


async def _get_or_create_settings(session: AsyncSession, chat_id: int) -> ChatSettings:
    settings = await session.get(ChatSettings, chat_id)
    if settings is None:
        # Set defaults explicitly: column defaults only kick in on flush, but we
        # read these attributes (e.g. toggling enabled) before committing.
        settings = ChatSettings(chat_id=chat_id, level=DEFAULT_LEVEL, enabled=True)
        session.add(settings)
    return settings


async def get_level(session: AsyncSession, chat_id: int) -> str:
    settings = await session.get(ChatSettings, chat_id)
    return settings.level if settings else DEFAULT_LEVEL


async def set_level(session: AsyncSession, chat_id: int, level: str) -> None:
    settings = await _get_or_create_settings(session, chat_id)
    settings.level = level
    await session.commit()


async def is_enabled(session: AsyncSession, chat_id: int) -> bool:
    settings = await session.get(ChatSettings, chat_id)
    return settings.enabled if settings else True


async def toggle_enabled(session: AsyncSession, chat_id: int) -> bool:
    """Flip the master switch and return the new state."""
    settings = await _get_or_create_settings(session, chat_id)
    settings.enabled = not settings.enabled
    await session.commit()
    return settings.enabled


async def set_enabled(session: AsyncSession, chat_id: int, enabled: bool) -> None:
    settings = await _get_or_create_settings(session, chat_id)
    settings.enabled = enabled
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


# --- usage / cost tracking --------------------------------------------------


async def _get_usage_row(session: AsyncSession, chat_id: int, user_id: int) -> Usage | None:
    return await session.scalar(
        select(Usage).where(Usage.chat_id == chat_id, Usage.user_id == user_id)
    )


async def record_usage(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost: float,
    replied: bool,
) -> None:
    row = await _get_usage_row(session, chat_id, user_id)
    if row is None:
        row = Usage(
            chat_id=chat_id, user_id=user_id, name="", requests=0, replies=0,
            prompt_tokens=0, completion_tokens=0, cost=0.0, limit_notified=False,
        )
        session.add(row)
    row.name = name or row.name
    row.requests += 1
    row.replies += 1 if replied else 0
    row.prompt_tokens += prompt_tokens
    row.completion_tokens += completion_tokens
    row.cost += cost
    await session.commit()


async def get_user_total_cost(session: AsyncSession, user_id: int) -> float:
    """How much this user has spent across every chat."""
    total = await session.scalar(select(func.coalesce(func.sum(Usage.cost), 0.0)).where(Usage.user_id == user_id))
    return float(total or 0.0)


async def is_limit_notified(session: AsyncSession, chat_id: int, user_id: int) -> bool:
    row = await _get_usage_row(session, chat_id, user_id)
    return bool(row and row.limit_notified)


async def mark_limit_notified(session: AsyncSession, chat_id: int, user_id: int) -> None:
    row = await _get_usage_row(session, chat_id, user_id)
    if row is None:
        row = Usage(
            chat_id=chat_id, user_id=user_id, name="", requests=0, replies=0,
            prompt_tokens=0, completion_tokens=0, cost=0.0, limit_notified=False,
        )
        session.add(row)
    row.limit_notified = True
    await session.commit()


# --- statistics -------------------------------------------------------------


async def get_stats(session: AsyncSession, chat_id: int | None, limit_usd: float) -> dict:
    """Aggregate usage. Pass chat_id=None for global stats across all chats."""
    scope = []
    if chat_id is not None:
        scope.append(Usage.chat_id == chat_id)

    totals = (
        await session.execute(
            select(
                func.count(Usage.id),
                func.coalesce(func.sum(Usage.requests), 0),
                func.coalesce(func.sum(Usage.replies), 0),
                func.coalesce(func.sum(Usage.prompt_tokens), 0),
                func.coalesce(func.sum(Usage.completion_tokens), 0),
                func.coalesce(func.sum(Usage.cost), 0.0),
                func.count(func.distinct(Usage.user_id)),
                func.count(func.distinct(Usage.chat_id)),
            ).where(*scope)
        )
    ).one()

    # Spend per user (summed across chats when global) to count who's over the cap.
    per_user = (
        await session.execute(
            select(Usage.user_id, func.sum(Usage.cost)).where(*scope).group_by(Usage.user_id)
        )
    ).all()
    over_limit = sum(1 for _, c in per_user if (c or 0.0) >= limit_usd)

    top = (
        await session.execute(
            select(
                Usage.user_id,
                func.max(Usage.name),
                func.sum(Usage.cost),
                func.sum(Usage.requests),
            )
            .where(*scope)
            .group_by(Usage.user_id)
            .order_by(func.sum(Usage.cost).desc())
            .limit(5)
        )
    ).all()

    return {
        "rows": totals[0],
        "requests": int(totals[1]),
        "replies": int(totals[2]),
        "prompt_tokens": int(totals[3]),
        "completion_tokens": int(totals[4]),
        "cost": float(totals[5]),
        "users": int(totals[6]),
        "chats": int(totals[7]),
        "over_limit": over_limit,
        "top": [
            {"user_id": uid, "name": name or str(uid), "cost": float(c or 0.0), "requests": int(r or 0)}
            for uid, name, c, r in top
        ],
    }


async def reset_usage(session: AsyncSession, chat_id: int | None) -> int:
    """Wipe usage rows (a single chat, or everything when chat_id is None). Returns rows deleted."""
    stmt = delete(Usage)
    if chat_id is not None:
        stmt = stmt.where(Usage.chat_id == chat_id)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount or 0
