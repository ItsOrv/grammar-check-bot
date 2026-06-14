import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.database import repo
from app.handlers.callbacks import _is_admin as _cb_is_admin
from app.keyboards import (
    main_menu_keyboard,
    main_menu_text,
    model_keyboard,
    model_text,
    settings_keyboard,
    settings_text,
    usage_keyboard,
    usage_text,
)

logger = logging.getLogger(__name__)

router = Router(name="menu")


async def _render_menu(message: Message, sessionmaker: async_sessionmaker, settings: Settings, user, edit: bool):
    async with sessionmaker() as session:
        wallet, _ = await repo.get_or_create_wallet(session, user.id, user.full_name, settings.free_credit_toman)
        balance = wallet.balance_toman
    text, kb = main_menu_text(balance), main_menu_keyboard()
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=kb)


@router.message(Command("start", "menu"), F.chat.type == "private")
async def cmd_menu(message: Message, sessionmaker: async_sessionmaker, settings: Settings, state: FSMContext):
    await state.clear()
    await _render_menu(message, sessionmaker, settings, message.from_user, edit=False)


@router.callback_query(F.data == "menu:home")
async def cb_home(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings, state: FSMContext):
    await state.clear()
    await _render_menu(callback.message, sessionmaker, settings, callback.from_user, edit=True)
    await callback.answer()


@router.callback_query(F.data == "menu:usage")
async def cb_usage(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings):
    async with sessionmaker() as session:
        u = await repo.get_user_usage(session, callback.from_user.id)
        wallet, _ = await repo.get_or_create_wallet(
            session, callback.from_user.id, callback.from_user.full_name, settings.free_credit_toman
        )
    text = usage_text(
        callback.from_user.full_name, u["requests"], u["replies"],
        u["prompt_tokens"], u["completion_tokens"], wallet.spent_toman, wallet.balance_toman,
    )
    try:
        await callback.message.edit_text(text, reply_markup=usage_keyboard())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "menu:model")
async def cb_model(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings):
    async with sessionmaker() as session:
        current = await repo.get_model(session, callback.message.chat.id, settings.llm_model)
    try:
        await callback.message.edit_text(model_text(current), reply_markup=model_keyboard(current, settings.model_choices))
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("model:"))
async def cb_set_model(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings):
    model_id = callback.data.split(":", 1)[1]
    if model_id not in {m for m, _ in settings.model_choices}:
        await callback.answer()
        return
    if not await _cb_is_admin(callback, settings):
        await callback.answer("فقط ادمین گروه می‌تونه مدل رو عوض کنه.", show_alert=True)
        return
    async with sessionmaker() as session:
        await repo.set_model(session, callback.message.chat.id, model_id)
    try:
        await callback.message.edit_text(model_text(model_id), reply_markup=model_keyboard(model_id, settings.model_choices))
    except Exception:
        pass
    await callback.answer(f"مدل: {model_id} ✅")


@router.callback_query(F.data == "menu:settings")
async def cb_settings(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings):
    chat_id = callback.message.chat.id
    show_stats = callback.from_user.id in settings.admin_id_set
    async with sessionmaker() as session:
        level = await repo.get_level(session, chat_id)
        enabled = await repo.is_enabled(session, chat_id)
        whitelist = len(await repo.get_whitelist(session, chat_id))
        model = await repo.get_model(session, chat_id, settings.llm_model)
    try:
        await callback.message.edit_text(
            settings_text(level, whitelist, settings, enabled, model),
            reply_markup=settings_keyboard(level, enabled, is_admin=show_stats),
        )
    except Exception:
        pass
    await callback.answer()
