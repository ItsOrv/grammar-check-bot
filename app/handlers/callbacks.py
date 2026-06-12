import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.database import repo
from app.keyboards import settings_keyboard, settings_text

logger = logging.getLogger(__name__)

router = Router(name="callbacks")


async def _is_admin(callback: CallbackQuery, settings: Settings) -> bool:
    if callback.from_user.id in settings.admin_id_set:
        return True
    try:
        member = await callback.bot.get_chat_member(callback.message.chat.id, callback.from_user.id)
    except Exception:
        logger.exception("get_chat_member failed in callback")
        return False
    return member.status in ("administrator", "creator")


@router.callback_query(F.data.startswith("level:"))
async def cb_set_level(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings):
    message = callback.message
    if not message or message.chat.type not in ("group", "supergroup"):
        await callback.answer()
        return

    level = callback.data.split(":", 1)[1]
    if level not in repo.LEVELS:
        await callback.answer()
        return

    if not await _is_admin(callback, settings):
        await callback.answer("Only group admins can change my settings.", show_alert=True)
        return

    async with sessionmaker() as session:
        await repo.set_level(session, message.chat.id, level)
        whitelist_count = len(await repo.get_whitelist(session, message.chat.id))

    try:
        await message.edit_text(
            settings_text(level, whitelist_count, settings),
            reply_markup=settings_keyboard(level),
        )
    except TelegramBadRequest:
        pass  # same level clicked twice — nothing to edit
    await callback.answer(f"Level set to {level} ✅")


@router.callback_query(F.data == "whitelist:help")
async def cb_whitelist_help(callback: CallbackQuery):
    await callback.answer(
        "Whitelist = terms I never flag.\n\n"
        "/whitelist — show the list\n"
        "/whitelist add <word ...>\n"
        "/whitelist remove <word>",
        show_alert=True,
    )
