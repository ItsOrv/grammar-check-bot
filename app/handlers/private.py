from aiogram import F, Router
from aiogram.types import Message

from app.keyboards import add_to_group_keyboard

router = Router(name="private")
router.message.filter(F.chat.type == "private")

WELCOME = (
    "👋 Hi! I'm a grammar checker for English group chats.\n\n"
    "Add me to a group and I'll quietly watch messages — "
    "replying only when something is genuinely wrong.\n\n"
    "In the group, admins can use /settings to pick a strictness level "
    "(strict / normal / casual / off)."
)


@router.message()
async def on_private(message: Message):
    me = await message.bot.me()
    await message.answer(WELCOME, reply_markup=add_to_group_keyboard(me.username))
