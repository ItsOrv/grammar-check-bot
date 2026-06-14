from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.keyboards import add_to_group_keyboard

router = Router(name="private")
router.message.filter(F.chat.type == "private")

WELCOME = (
    "👋 Hi! I'm an English grammar checker.\n\n"
    "You can just type a sentence here and I'll check it, replying only when "
    "something is genuinely wrong. Or add me to a group and I'll do the same there.\n\n"
    "Useful commands:\n"
    "• /settings — pick a strictness level (strict / normal / casual)\n"
    "• /t <text> — translate anything into English\n"
    "• /stop and /resume — pause or wake me up"
)


@router.message(Command("help"))
async def on_help(message: Message):
    me = await message.bot.me()
    await message.answer(WELCOME, reply_markup=add_to_group_keyboard(me.username))
