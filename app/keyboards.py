from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import Settings

LEVEL_BUTTONS = [
    ("strict", "🎓 Strict"),
    ("normal", "✅ Normal"),
    ("casual", "😎 Casual"),
    ("off", "💤 Off"),
]


def settings_keyboard(current_level: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value, label in LEVEL_BUTTONS:
        text = f"▸ {label} ◂" if value == current_level else label
        builder.button(text=text, callback_data=f"level:{value}")
    builder.adjust(2, 2)
    builder.row(InlineKeyboardButton(text="📝 Whitelist", callback_data="whitelist:help"))
    return builder.as_markup()


def settings_text(level: str, whitelist_count: int, settings: Settings) -> str:
    return (
        "⚙️ Grammar check settings\n"
        f"• Level: {level}\n"
        f"• Whitelist: {whitelist_count} term(s)\n"
        f"• Cooldown: {settings.cooldown_seconds}s per user\n"
        f"• Model: {settings.llm_model}\n\n"
        "Pick a strictness level:"
    )


def add_to_group_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="➕ Add me to a group",
            # tg:// deep link — opens the group picker directly in the app;
            # some clients drop the startgroup param on plain t.me links.
            url=f"tg://resolve?domain={bot_username}&startgroup=true",
        )
    )
    return builder.as_markup()
