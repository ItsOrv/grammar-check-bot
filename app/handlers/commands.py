import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.billing import resolve_payer
from app.config import Settings
from app.database import repo
from app.keyboards import settings_keyboard, settings_text, stats_keyboard, stats_text
from app.services.llm import GrammarChecker
from app.services.rate import RateProvider, cost_to_toman

logger = logging.getLogger(__name__)

router = Router(name="commands")
router.message.filter(F.chat.type.in_({"group", "supergroup", "private"}))

LEVEL_REPLIES = {
    "strict": "Strict mode: formal English — punctuation, capitalization, everything counts.",
    "normal": "Normal mode: standard grammar checked, minor punctuation ignored.",
    "casual": "Casual mode: slang and abbreviations are fine, only meaning-breaking errors get flagged.",
    "off": "Grammar checking is off here.",
}


def _is_private(message: Message) -> bool:
    return message.chat.type == "private"


async def _is_admin(message: Message, settings: Settings) -> bool:
    # In a private chat the user owns their own settings.
    if _is_private(message):
        return True
    # Anonymous group admins post as the chat itself.
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return True
    if not message.from_user:
        return False
    if message.from_user.id in settings.admin_id_set:
        return True
    try:
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    except Exception:
        logger.exception("get_chat_member failed")
        return False
    return member.status in ("administrator", "creator")


async def _require_admin(message: Message, settings: Settings) -> bool:
    if await _is_admin(message, settings):
        return True
    await message.reply("Only group admins can change my settings.")
    return False


async def _can_see_stats(message: Message, settings: Settings) -> bool:
    """Bot owners see everything; group admins see their own group."""
    if message.from_user and message.from_user.id in settings.admin_id_set:
        return True
    if message.chat.type in ("group", "supergroup"):
        return await _is_admin(message, settings)
    return False


@router.message(Command("strict", "normal", "casual", "off"))
async def cmd_set_level(
    message: Message, command: CommandObject, sessionmaker: async_sessionmaker, settings: Settings
):
    if not await _require_admin(message, settings):
        return
    level = command.command
    async with sessionmaker() as session:
        await repo.set_level(session, message.chat.id, level)
    await message.reply(LEVEL_REPLIES[level])


@router.message(Command("stop"))
async def cmd_stop(message: Message, sessionmaker: async_sessionmaker, settings: Settings):
    user = message.from_user
    if not user:
        return
    async with sessionmaker() as session:
        await repo.set_active(session, user.id, user.full_name, settings.free_credit_toman, False)
    await message.reply("متوقف شد. ربات توی پیویِ تو و همه‌ی گروه‌هایی که اضافه کردی غیرفعاله. برای روشن‌کردن: /resume")


@router.message(Command("resume"))
async def cmd_resume(message: Message, sessionmaker: async_sessionmaker, settings: Settings):
    user = message.from_user
    if not user:
        return
    async with sessionmaker() as session:
        await repo.set_active(session, user.id, user.full_name, settings.free_credit_toman, True)
    await message.reply("روشن شد. دوباره پیام‌ها رو چک می‌کنم.")


@router.message(Command("t", "translate"))
async def cmd_translate(
    message: Message,
    command: CommandObject,
    sessionmaker: async_sessionmaker,
    checker: GrammarChecker,
    settings: Settings,
    rate: RateProvider,
    llm_semaphore: asyncio.Semaphore,
):
    # Text to translate: command args, or the replied-to message's text.
    text = (command.args or "").strip()
    if not text and message.reply_to_message:
        text = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
    if not text:
        await message.reply("Usage: /t <text>  — or reply to a message with /t")
        return

    # Same billing as grammar checking: in a group the owner pays.
    payer = await resolve_payer(message, sessionmaker, settings)
    if payer.problem == "no_owner":
        await message.reply("نمی‌دونم کی منو به این گروه اضافه کرده.")
        return
    if payer.problem == "no_wallet":
        await message.reply("صاحبِ این گروه باید اول ربات رو توی پیوی استارت کنه و موجودی داشته باشه.")
        return
    if not payer.wallet.active:
        await message.reply("ربات الان متوقفه. با /resume روشنش کن.")
        return
    if payer.wallet.balance_toman <= 0:
        await message.reply(
            "موجودیِ صاحبِ این گروه تموم شده." if message.chat.type != "private"
            else "موجودی کیف پولت تموم شده. با /wallet شارژ کن."
        )
        return

    async with sessionmaker() as session:
        level = await repo.get_level(session, message.chat.id)
        model = await repo.get_model(session, message.chat.id, settings.llm_model)

    async with llm_semaphore:
        translation, usage = await checker.translate(text, level, model=model)

    if not translation:
        await message.reply("Couldn't translate right now, please try again.")
        return

    cost = usage.cost(settings.price_input_per_million, settings.price_output_per_million)
    toman = cost_to_toman(cost, await rate.get_rate(), settings.price_markup)
    async with sessionmaker() as session:
        if message.from_user:  # stats to the sender
            await repo.record_usage(
                session, message.chat.id, message.from_user.id, message.from_user.full_name,
                usage.prompt_tokens, usage.completion_tokens, cost, replied=True,
            )
        if toman > 0:  # money from the payer
            await repo.deduct(session, payer.user_id, toman)

    await message.reply(f"{translation}")


@router.message(Command("settings", "status"))
async def cmd_settings(message: Message, sessionmaker: async_sessionmaker, settings: Settings):
    show_stats = await _can_see_stats(message, settings)
    async with sessionmaker() as session:
        level = await repo.get_level(session, message.chat.id)
        enabled = await repo.is_active(session, message.from_user.id) if message.from_user else True
        whitelist = await repo.get_whitelist(session, message.chat.id)
        model = await repo.get_model(session, message.chat.id, settings.llm_model)
    await message.reply(
        settings_text(level, len(whitelist), settings, enabled, model),
        reply_markup=settings_keyboard(level, enabled, is_admin=show_stats),
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message, sessionmaker: async_sessionmaker, settings: Settings):
    if not await _can_see_stats(message, settings):
        await message.reply("Only admins can see statistics.")
        return
    is_owner = bool(message.from_user and message.from_user.id in settings.admin_id_set)
    scope_chat = None if is_owner else message.chat.id
    scope_label = "all chats" if is_owner else "this chat"
    async with sessionmaker() as session:
        stats = await repo.get_stats(session, scope_chat)
        stats["wallet"] = await repo.get_wallet_stats(session) if is_owner else None
    await message.reply(
        stats_text(scope_label, stats),
        reply_markup=stats_keyboard(is_owner=is_owner),
    )


@router.message(Command("emojiid"))
async def cmd_emojiid(message: Message, settings: Settings):
    """Admin tool: reply to (or include) premium emoji to get their custom_emoji_id."""
    if not (message.from_user and message.from_user.id in settings.admin_id_set):
        return
    src = message.reply_to_message or message
    text = src.text or src.caption or ""
    entities = src.entities or src.caption_entities or []
    customs = [e for e in entities if e.type == "custom_emoji"]
    if not customs:
        await message.reply(
            "یه پیامی که ایموجی پرمیوم داره ریپلای کن، یا همراه همین دستور ایموجی‌ها رو بفرست."
        )
        return
    # Telegram entity offsets/lengths are in UTF-16 code units.
    u16 = text.encode("utf-16-le")
    lines = []
    for e in customs:
        char = u16[e.offset * 2 : (e.offset + e.length) * 2].decode("utf-16-le", "ignore")
        lines.append(f"{char} : <code>{e.custom_emoji_id}</code>")
    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("whitelist"))
async def cmd_whitelist(
    message: Message, command: CommandObject, sessionmaker: async_sessionmaker, settings: Settings
):
    args = (command.args or "").split()

    if not args:  # show list — allowed for everyone
        async with sessionmaker() as session:
            words = await repo.get_whitelist(session, message.chat.id)
        if not words:
            await message.reply("Whitelist is empty. Add terms with /whitelist add <word ...>")
        else:
            await message.reply("Whitelisted terms:\n" + ", ".join(words))
        return

    action, *words = args
    action = action.lower()
    if action not in ("add", "remove") or not words:
        await message.reply("Usage: /whitelist | /whitelist add <word ...> | /whitelist remove <word>")
        return
    if not await _require_admin(message, settings):
        return

    async with sessionmaker() as session:
        if action == "add":
            added = await repo.add_whitelist_words(session, message.chat.id, words)
            await message.reply(f"Added: {', '.join(added)}" if added else "Nothing new to add.")
        else:
            removed = await repo.remove_whitelist_word(session, message.chat.id, words[0])
            await message.reply("Removed." if removed else "That term isn't in the whitelist.")
