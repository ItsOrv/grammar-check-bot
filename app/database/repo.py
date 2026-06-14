from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ChatSettings, Payment, Usage, Wallet, WhitelistEntry

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


async def get_model(session: AsyncSession, chat_id: int, default: str) -> str:
    settings = await session.get(ChatSettings, chat_id)
    return settings.model if (settings and settings.model) else default


async def set_model(session: AsyncSession, chat_id: int, model: str) -> None:
    settings = await _get_or_create_settings(session, chat_id)
    settings.model = model
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


async def get_user_usage(session: AsyncSession, user_id: int) -> dict:
    """This user's own totals, summed across every chat (for the 'my usage' view)."""
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(Usage.requests), 0),
                func.coalesce(func.sum(Usage.replies), 0),
                func.coalesce(func.sum(Usage.prompt_tokens), 0),
                func.coalesce(func.sum(Usage.completion_tokens), 0),
            ).where(Usage.user_id == user_id)
        )
    ).one()
    return {
        "requests": int(row[0]),
        "replies": int(row[1]),
        "prompt_tokens": int(row[2]),
        "completion_tokens": int(row[3]),
    }


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


async def get_stats(session: AsyncSession, chat_id: int | None) -> dict:
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


# --- wallet (Toman) ---------------------------------------------------------


async def get_or_create_wallet(
    session: AsyncSession, user_id: int, name: str, free_credit: float
) -> tuple[Wallet, bool]:
    """Return the wallet, creating it (and granting the one-time free credit) on first touch.
    The bool says whether the free credit was just handed out."""
    wallet = await session.get(Wallet, user_id)
    granted_now = False
    if wallet is None:
        wallet = Wallet(
            user_id=user_id, name=name or "", balance_toman=free_credit, spent_toman=0.0,
            free_granted=True, low_balance_notified=False,
        )
        session.add(wallet)
        granted_now = free_credit > 0
        await session.commit()
    elif name and wallet.name != name:
        wallet.name = name
        await session.commit()
    return wallet, granted_now


async def get_balance(session: AsyncSession, user_id: int) -> float:
    wallet = await session.get(Wallet, user_id)
    return float(wallet.balance_toman) if wallet else 0.0


async def deduct(session: AsyncSession, user_id: int, amount_toman: float) -> float:
    wallet = await session.get(Wallet, user_id)
    if wallet is None:
        return 0.0
    wallet.balance_toman = float(wallet.balance_toman) - amount_toman
    wallet.spent_toman = float(wallet.spent_toman) + amount_toman
    await session.commit()
    return wallet.balance_toman


async def credit(session: AsyncSession, user_id: int, amount_toman: float, name: str = "") -> float:
    wallet = await session.get(Wallet, user_id)
    if wallet is None:
        wallet = Wallet(
            user_id=user_id, name=name or "", balance_toman=0.0, spent_toman=0.0,
            free_granted=True, low_balance_notified=False,
        )
        session.add(wallet)
    wallet.balance_toman = float(wallet.balance_toman) + amount_toman
    wallet.low_balance_notified = False  # they have money again
    await session.commit()
    return wallet.balance_toman


async def is_low_balance_notified(session: AsyncSession, user_id: int) -> bool:
    wallet = await session.get(Wallet, user_id)
    return bool(wallet and wallet.low_balance_notified)


async def mark_low_balance_notified(session: AsyncSession, user_id: int) -> None:
    wallet = await session.get(Wallet, user_id)
    if wallet is not None:
        wallet.low_balance_notified = True
        await session.commit()


# --- payments ---------------------------------------------------------------


async def create_payment(
    session: AsyncSession, order_id: str, user_id: int, method: str,
    amount_toman: float, amount_usd: float = 0.0, provider_id: str = "", note: str = "",
) -> Payment:
    payment = Payment(
        order_id=order_id, user_id=user_id, method=method, amount_toman=amount_toman,
        amount_usd=amount_usd, status="pending", provider_id=provider_id, note=note,
    )
    session.add(payment)
    await session.commit()
    return payment


async def get_payment_by_order(session: AsyncSession, order_id: str) -> Payment | None:
    return await session.scalar(select(Payment).where(Payment.order_id == order_id))


async def set_payment_status(session: AsyncSession, order_id: str, status: str) -> Payment | None:
    payment = await get_payment_by_order(session, order_id)
    if payment is not None:
        payment.status = status
        await session.commit()
    return payment


async def list_user_payments(session: AsyncSession, user_id: int, limit: int = 10) -> list[Payment]:
    rows = await session.scalars(
        select(Payment).where(Payment.user_id == user_id).order_by(Payment.id.desc()).limit(limit)
    )
    return list(rows)


async def get_wallet_stats(session: AsyncSession) -> dict:
    row = (
        await session.execute(
            select(
                func.count(Wallet.user_id),
                func.coalesce(func.sum(Wallet.balance_toman), 0.0),
                func.coalesce(func.sum(Wallet.spent_toman), 0.0),
            )
        )
    ).one()
    topups = (
        await session.execute(
            select(func.coalesce(func.sum(Payment.amount_toman), 0.0)).where(
                Payment.status.in_(("finished", "approved"))
            )
        )
    ).scalar()
    return {
        "wallets": int(row[0]),
        "balance_toman": float(row[1]),
        "spent_toman": float(row[2]),
        "topped_up_toman": float(topups or 0.0),
    }
