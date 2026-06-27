from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
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


async def get_model(session: AsyncSession, chat_id: int, default: str) -> str:
    settings = await session.get(ChatSettings, chat_id)
    return settings.model if (settings and settings.model) else default


async def set_model(session: AsyncSession, chat_id: int, model: str) -> None:
    settings = await _get_or_create_settings(session, chat_id)
    settings.model = model
    await session.commit()


async def get_owner(session: AsyncSession, chat_id: int) -> int | None:
    settings = await session.get(ChatSettings, chat_id)
    return settings.owner_id if settings else None


async def set_owner(session: AsyncSession, chat_id: int, owner_id: int) -> None:
    settings = await _get_or_create_settings(session, chat_id)
    settings.owner_id = owner_id
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
            prompt_tokens=0, completion_tokens=0, cost=0.0,
        )
        session.add(row)
    row.name = name or row.name
    row.requests += 1
    row.replies += 1 if replied else 0
    row.prompt_tokens += prompt_tokens
    row.completion_tokens += completion_tokens
    row.cost += cost
    await session.commit()


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


async def get_wallet(session: AsyncSession, user_id: int) -> Wallet | None:
    return await session.get(Wallet, user_id)


async def get_or_create_wallet(
    session: AsyncSession, user_id: int, name: str, free_credit: float, started: bool = False
) -> tuple[Wallet, bool]:
    """Return the wallet, creating it (and granting the one-time free credit) on first touch.
    The bool says whether the free credit was just handed out. ``started=True`` marks that
    the user has opened the bot in private (required before a group can bill them)."""
    wallet = await session.get(Wallet, user_id)
    if wallet is None:
        wallet = Wallet(
            user_id=user_id, name=name or "", balance_toman=free_credit, spent_toman=0.0,
            active=True, started=started, free_granted=True, low_balance_notified=False,
        )
        session.add(wallet)
        try:
            await session.commit()
            return wallet, free_credit > 0
        except IntegrityError:
            # A concurrent first-touch (e.g. /start racing a group message) already
            # inserted this wallet. Reuse that row instead of crashing / double-granting.
            await session.rollback()
            wallet = await session.get(Wallet, user_id)
            if wallet is None:
                raise
            # fall through and just sync name/started on the existing row
    dirty = False
    if name and wallet.name != name:
        wallet.name = name
        dirty = True
    if started and not wallet.started:
        wallet.started = True
        dirty = True
    if dirty:
        await session.commit()
    return wallet, False


async def toggle_active(session: AsyncSession, user_id: int, name: str, free_credit: float) -> bool:
    """Flip the owner-level stop/resume switch and return the new state."""
    wallet, _ = await get_or_create_wallet(session, user_id, name, free_credit, started=True)
    wallet.active = not wallet.active
    await session.commit()
    return wallet.active


async def set_active(session: AsyncSession, user_id: int, name: str, free_credit: float, active: bool) -> None:
    wallet, _ = await get_or_create_wallet(session, user_id, name, free_credit, started=True)
    wallet.active = active
    await session.commit()


async def is_active(session: AsyncSession, user_id: int) -> bool:
    wallet = await session.get(Wallet, user_id)
    return wallet.active if wallet else True


async def get_balance(session: AsyncSession, user_id: int) -> float:
    wallet = await session.get(Wallet, user_id)
    return float(wallet.balance_toman) if wallet else 0.0


async def _balance_now(session: AsyncSession, user_id: int) -> float:
    balance = await session.scalar(select(Wallet.balance_toman).where(Wallet.user_id == user_id))
    return float(balance) if balance is not None else 0.0


async def deduct(session: AsyncSession, user_id: int, amount_toman: float) -> float:
    # Single conditional UPDATE so concurrent charges on the same wallet (e.g. a busy
    # group all billed to one owner) can't lose each other's deductions — a Python
    # read-modify-write would let two callers both read the old balance and clobber it.
    await session.execute(
        update(Wallet)
        .where(Wallet.user_id == user_id)
        .values(
            balance_toman=Wallet.balance_toman - amount_toman,
            spent_toman=Wallet.spent_toman + amount_toman,
        )
    )
    await session.commit()
    return await _balance_now(session, user_id)


async def credit(session: AsyncSession, user_id: int, amount_toman: float, name: str = "") -> float:
    # Atomic increment for the same reason as deduct(): two top-ups landing on one
    # wallet at once (e.g. a card approval racing a crypto IPN) must both stick.
    result = await session.execute(
        update(Wallet)
        .where(Wallet.user_id == user_id)
        .values(
            balance_toman=Wallet.balance_toman + amount_toman,
            low_balance_notified=False,  # they have money again
        )
    )
    if result.rowcount == 0:
        # No wallet yet — create it. If a concurrent caller wins the insert, retry as
        # an increment so neither top-up is lost.
        session.add(Wallet(
            user_id=user_id, name=name or "", balance_toman=amount_toman, spent_toman=0.0,
            active=True, started=False, free_granted=True, low_balance_notified=False,
        ))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            await session.execute(
                update(Wallet)
                .where(Wallet.user_id == user_id)
                .values(
                    balance_toman=Wallet.balance_toman + amount_toman,
                    low_balance_notified=False,
                )
            )
            await session.commit()
    else:
        await session.commit()
    return await _balance_now(session, user_id)


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


async def claim_payment_if_pending(
    session: AsyncSession, order_id: str, new_status: str
) -> Payment | None:
    """Atomically move a payment out of 'pending' into ``new_status``.

    Returns the payment only if *this* call won the transition; returns None if it was
    already handled (or the order is unknown). The single conditional UPDATE is what makes
    it safe: when the provider delivers the same IPN twice — even concurrently — exactly one
    caller flips the row, so the wallet is credited once and never double-credited.
    """
    result = await session.execute(
        update(Payment)
        .where(Payment.order_id == order_id, Payment.status == "pending")
        .values(status=new_status)
    )
    await session.commit()
    if result.rowcount == 0:
        return None
    return await get_payment_by_order(session, order_id)


async def claim_payment_and_credit(
    session: AsyncSession, order_id: str, new_status: str
) -> tuple[Payment | None, float]:
    """Atomically flip a payment pending->``new_status`` AND credit its wallet, in one commit.

    Returns ``(payment, new_balance)`` only if *this* call won the claim; ``(None, 0.0)``
    if it was already handled or the order is unknown. Doing the status flip and the wallet
    credit in a single transaction means a crash can never leave a payment marked paid while
    the money was never added (which, since the row is no longer pending, would be unrecoverable).
    """
    result = await session.execute(
        update(Payment)
        .where(Payment.order_id == order_id, Payment.status == "pending")
        .values(status=new_status)
    )
    if result.rowcount == 0:
        return None, 0.0
    payment = await get_payment_by_order(session, order_id)
    upd = await session.execute(
        update(Wallet)
        .where(Wallet.user_id == payment.user_id)
        .values(
            balance_toman=Wallet.balance_toman + payment.amount_toman,
            low_balance_notified=False,
        )
    )
    if upd.rowcount == 0:
        session.add(Wallet(
            user_id=payment.user_id, name="", balance_toman=payment.amount_toman, spent_toman=0.0,
            active=True, started=False, free_granted=True, low_balance_notified=False,
        ))
    await session.commit()
    return payment, await _balance_now(session, payment.user_id)


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
