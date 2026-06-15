import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.database import repo
from app.keyboards import settings_keyboard, settings_text, stats_keyboard, stats_text

logger = logging.getLogger(__name__)

router = Router(name="callbacks")


async def _is_admin(callback: CallbackQuery, settings: Settings) -> bool:
    if callback.from_user.id in settings.admin_id_set:
        return True
    chat = callback.message.chat
    if chat.type == "private":
        return True
    try:
        member = await callback.bot.get_chat_member(chat.id, callback.from_user.id)
    except Exception:
        logger.exception("get_chat_member failed in callback")
        return False
    return member.status in ("administrator", "creator")


async def _can_see_stats(callback: CallbackQuery, settings: Settings) -> bool:
    if callback.from_user.id in settings.admin_id_set:
        return True
    if callback.message.chat.type in ("group", "supergroup"):
        return await _is_admin(callback, settings)
    return False


async def _render_settings(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings):
    chat_id = callback.message.chat.id
    show_stats = await _can_see_stats(callback, settings)
    async with sessionmaker() as session:
        level = await repo.get_level(session, chat_id)
        enabled = await repo.is_active(session, callback.from_user.id)
        whitelist_count = len(await repo.get_whitelist(session, chat_id))
        model = await repo.get_model(session, chat_id, settings.llm_model)
    try:
        await callback.message.edit_text(
            settings_text(level, whitelist_count, settings, enabled, model),
            reply_markup=settings_keyboard(level, enabled, is_admin=show_stats),
        )
    except TelegramBadRequest:
        pass  # nothing actually changed — Telegram rejects a no-op edit


@router.callback_query(F.data.startswith("level:"), F.message)
async def cb_set_level(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings):
    message = callback.message
    if not message or message.chat.type not in ("group", "supergroup", "private"):
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
    await _render_settings(callback, sessionmaker, settings)
    await callback.answer(f"Level set to {level}")


@router.callback_query(F.data == "power:toggle", F.message)
async def cb_power_toggle(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings):
    if not callback.message:
        await callback.answer()
        return
    # Personal owner-level switch: affects this user's private chat and every group
    # they added the bot to.
    async with sessionmaker() as session:
        active = await repo.toggle_active(
            session, callback.from_user.id, callback.from_user.full_name, settings.free_credit_toman
        )
    await _render_settings(callback, sessionmaker, settings)
    await callback.answer("روشن شد" if active else "متوقف شد")


@router.callback_query(F.data == "stats:show", F.message)
async def cb_stats_show(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings):
    if not await _can_see_stats(callback, settings):
        await callback.answer("Only admins can see statistics.", show_alert=True)
        return
    is_owner = callback.from_user.id in settings.admin_id_set
    scope_chat = None if is_owner else callback.message.chat.id
    scope_label = "all chats" if is_owner else "this chat"
    async with sessionmaker() as session:
        stats = await repo.get_stats(session, scope_chat)
        stats["wallet"] = await repo.get_wallet_stats(session) if is_owner else None
    try:
        await callback.message.edit_text(
            stats_text(scope_label, stats),
            reply_markup=stats_keyboard(is_owner=is_owner),
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "stats:reset", F.message)
async def cb_stats_reset(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings):
    # Wiping usage stats is owner-only (it doesn't touch balances, but it's still
    # not something group admins or regular users should be able to do).
    if callback.from_user.id not in settings.admin_id_set:
        await callback.answer("فقط مالک ربات می‌تونه آمار رو پاک کنه.", show_alert=True)
        return
    async with sessionmaker() as session:
        deleted = await repo.reset_usage(session, None)
    await callback.answer(f"Cleared {deleted} record(s).", show_alert=True)
    await cb_stats_show(callback, sessionmaker, settings)


@router.callback_query(F.data == "stats:back", F.message)
async def cb_stats_back(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings):
    await _render_settings(callback, sessionmaker, settings)
    await callback.answer()


@router.callback_query(F.data == "whitelist:help", F.message)
async def cb_whitelist_help(callback: CallbackQuery):
    await callback.answer(
        "Whitelist = terms I never flag.\n\n"
        "/whitelist — show the list\n"
        "/whitelist add <word ...>\n"
        "/whitelist remove <word>",
        show_alert=True,
    )
