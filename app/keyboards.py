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
