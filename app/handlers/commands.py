import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.database import repo
from app.keyboards import settings_keyboard, settings_text
from app.services.llm import GrammarChecker

logger = logging.getLogger(__name__)

router = Router(name="commands")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

LEVEL_REPLIES = {
    "strict": "✅ Strict mode: formal English — punctuation, capitalization, everything counts.",
    "normal": "✅ Normal mode: standard grammar checked, minor punctuation ignored.",
    "casual": "✅ Casual mode: slang and abbreviations are fine, only meaning-breaking errors get flagged.",
    "off": "💤 Grammar checking is off for this group.",
}


async def _is_admin(message: Message, settings: Settings) -> bool:
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


@router.message(Command("t", "translate"))
async def cmd_translate(
    message: Message,
    command: CommandObject,
    sessionmaker: async_sessionmaker,
    checker: GrammarChecker,
    llm_semaphore: asyncio.Semaphore,
):
    # Text to translate: command args, or the replied-to message's text.
    text = (command.args or "").strip()
    if not text and message.reply_to_message:
        text = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
    if not text:
        await message.reply("Usage: /t <text>  — or reply to a message with /t")
        return

    async with sessionmaker() as session:
        level = await repo.get_level(session, message.chat.id)

    async with llm_semaphore:
        translation = await checker.translate(text, level)

    if not translation:
        await message.reply("Couldn't translate right now, please try again.")
        return
    await message.reply(f"🌐 {translation}")


@router.message(Command("settings", "status"))
async def cmd_settings(message: Message, sessionmaker: async_sessionmaker, settings: Settings):
    async with sessionmaker() as session:
        level = await repo.get_level(session, message.chat.id)
        whitelist = await repo.get_whitelist(session, message.chat.id)
    await message.reply(
        settings_text(level, len(whitelist), settings),
        reply_markup=settings_keyboard(level),
    )


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
            await message.reply("📝 Whitelisted terms:\n" + ", ".join(words))
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
            await message.reply(f"✅ Added: {', '.join(added)}" if added else "Nothing new to add.")
        else:
            removed = await repo.remove_whitelist_word(session, message.chat.id, words[0])
            await message.reply("✅ Removed." if removed else "That term isn't in the whitelist.")
