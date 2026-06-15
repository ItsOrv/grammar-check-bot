import asyncio
import logging

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.billing import resolve_payer
from app.config import Settings
from app.database import repo
from app.services import prefilter
from app.services.cooldown import Cooldown
from app.services.llm import GrammarChecker, should_reply
from app.services.rate import RateProvider, cost_to_toman

logger = logging.getLogger(__name__)

router = Router(name="messages")

# Chats we've already nagged about a missing owner (in-memory, resets on restart)
# so we don't spam the group on every message.
_owner_warned: set[int] = set()


async def _warn_group(message: Message, text: str) -> None:
    if message.chat.id in _owner_warned:
        return
    _owner_warned.add(message.chat.id)
    try:
        await message.answer(text)
    except Exception:
        logger.exception("failed to warn group %s", message.chat.id)


@router.message(F.chat.type.in_({"group", "supergroup", "private"}), F.text)
async def on_text(
    message: Message,
    settings: Settings,
    sessionmaker: async_sessionmaker,
    checker: GrammarChecker,
    cooldown: Cooldown,
    rate: RateProvider,
    llm_semaphore: asyncio.Semaphore,
):
    user = message.from_user
    if not user or user.is_bot or message.via_bot:
        return

    is_private = message.chat.type == "private"

    if not prefilter.should_check(
        message.text, message.entities, min_words=settings.min_words, min_chars=settings.min_chars
    ):
        return

    if not is_private and cooldown.is_active(message.chat.id, user.id):
        return

    async with sessionmaker() as session:
        level = await repo.get_level(session, message.chat.id)
        if level == "off":
            return
        whitelist = await repo.get_whitelist(session, message.chat.id)
        model = await repo.get_model(session, message.chat.id, settings.llm_model)

    # --- work out who pays, and whether we can ---
    payer = await resolve_payer(message, sessionmaker, settings)
    if payer.problem == "no_owner":
        await _warn_group(message, "نمی‌دونم کی منو به این گروه اضافه کرده. یه ادمین دوباره اضافه‌م کنه.")
        return
    if payer.problem == "no_wallet":
        await _warn_group(
            message,
            "کسی که منو اضافه کرده هنوز ربات رو استارت نکرده. لطفاً اول توی پیویِ ربات /start بزن "
            "تا گرامرِ گروه چک شه.",
        )
        return

    if payer.granted:  # private only
        try:
            await message.answer(
                f"{int(settings.free_credit_toman):,} تومان اعتبار رایگان بهت دادم. "
                "هر وقت تموم شد با /wallet شارژ کن."
            )
        except Exception:
            logger.exception("failed to send free-credit notice")

    if not payer.wallet.active:
        return  # owner/user paused the bot with /stop

    if payer.wallet.balance_toman <= 0:
        if not payer.wallet.low_balance_notified:
            async with sessionmaker() as session:
                await repo.mark_low_balance_notified(session, payer.user_id)
            try:
                await message.answer(
                    "موجودیِ کیف پولِ صاحبِ این گروه تموم شده. برای ادامه باید شارژ کنه (/wallet)."
                    if not is_private else
                    "موجودی کیف پولت تموم شده. برای ادامه با /wallet شارژ کن."
                )
            except Exception:
                logger.exception("failed to send low-balance notice")
        return

    async with llm_semaphore:
        result, usage = await checker.check(message.text, level, whitelist, model=model)

    will_reply = should_reply(result, level, message.text, settings.confidence_threshold)
    cost_usd = usage.cost(settings.price_input_per_million, settings.price_output_per_million)
    toman = cost_to_toman(cost_usd, await rate.get_rate(), settings.price_markup)
    logger.info(
        "result chat=%s sender=%s payer=%s %s cost=$%.5f/%dT -> reply=%s",
        message.chat.id, user.id, payer.user_id, result, cost_usd, toman, will_reply,
    )

    async with sessionmaker() as session:
        # stats are attributed to the sender; the money comes out of the payer's wallet.
        await repo.record_usage(
            session, message.chat.id, user.id, user.full_name,
            usage.prompt_tokens, usage.completion_tokens, cost_usd, replied=will_reply,
        )
        if toman > 0:
            await repo.deduct(session, payer.user_id, toman)

    if not will_reply:
        return

    try:
        await message.reply(f"{result.corrected}\n\n{result.explanation}")
    except Exception:
        logger.exception("Failed to send correction reply")
        return
    cooldown.mark(message.chat.id, user.id)
