from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ChatSettings(Base):
    __tablename__ = "chat_settings"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    level: Mapped[str] = mapped_column(String(16), default="normal")
    # Master on/off switch flipped by the stop/start button, kept separate from
    # the strictness level so pausing doesn't forget which level you were on.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Which LLM model this chat uses; null = fall back to the configured default.
    model: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    # In a group, the user who added the bot (falls back to the group creator).
    # Their wallet pays for the whole group's checks.
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Wallet(Base):
    """A user's money. Everything here is in Toman."""

    __tablename__ = "wallet"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    balance_toman: Mapped[float] = mapped_column(Float, default=0.0)
    spent_toman: Mapped[float] = mapped_column(Float, default=0.0)
    # Owner-level on/off switch (stop/resume). Pauses this user's private chat
    # and every group they added the bot to.
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # True once the user has actually opened the bot in private (/start). A group
    # owner must have started the bot before we can bill them.
    started: Mapped[bool] = mapped_column(Boolean, default=False)
    # Whether the one-time free credit was already handed out.
    free_granted: Mapped[bool] = mapped_column(Boolean, default=False)
    # So we only nag about an empty balance once.
    low_balance_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Payment(Base):
    """A top-up attempt, card-to-card or crypto."""

    __tablename__ = "payment"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    method: Mapped[str] = mapped_column(String(16))  # "card" or "crypto"
    amount_toman: Mapped[float] = mapped_column(Float, default=0.0)
    amount_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # pending -> finished/approved (credited) or rejected/failed/expired
    status: Mapped[str] = mapped_column(String(16), default="pending")
    provider_id: Mapped[str] = mapped_column(String(128), default="")  # NOWPayments invoice/payment id
    note: Mapped[str] = mapped_column(String(512), default="")  # receipt text, admin note, etc.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Usage(Base):
    """What each user spent, per chat. Cost is in USD."""

    __tablename__ = "usage"
    __table_args__ = (UniqueConstraint("chat_id", "user_id", name="uq_usage_chat_user"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    requests: Mapped[int] = mapped_column(Integer, default=0)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class WhitelistEntry(Base):
    __tablename__ = "whitelist"
    __table_args__ = (UniqueConstraint("chat_id", "word", name="uq_whitelist_chat_word"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    word: Mapped[str] = mapped_column(String(128))
