from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import Settings
from app.premium import icon

# Message text is premium-ified centrally by the session middleware, so the
# builders here just use the plain emoji and let that pass do the work. Buttons
# can't carry tg-emoji in their text, so they use icon_custom_emoji_id instead —
# and any emoji without a premium version is simply dropped for a clean look.


def picon_button(emoji: str, text: str, callback_data: str) -> InlineKeyboardButton:
    eid = icon(emoji)
    if eid:
        return InlineKeyboardButton(text=text, callback_data=callback_data, icon_custom_emoji_id=eid)
    return InlineKeyboardButton(text=text, callback_data=callback_data)


LEVELS = [("strict", "Strict"), ("normal", "Normal"), ("casual", "Casual"), ("off", "Off")]


def settings_keyboard(current_level: str, enabled: bool, is_admin: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for value, label in LEVELS:
        text = f"▸ {label} ◂" if value == current_level else label
        b.button(text=text, callback_data=f"level:{value}")
    b.adjust(2, 2)
    b.row(InlineKeyboardButton(text="Stop" if enabled else "Start", callback_data="power:toggle"))
    b.row(
        picon_button("📋", "Whitelist", "whitelist:help"),
        picon_button("💰", "Wallet", "wallet:show"),
    )
    if is_admin:
        b.row(picon_button("📊", "Statistics", "stats:show"))
    return b.as_markup()


def settings_text(level: str, whitelist_count: int, settings: Settings, enabled: bool, model: str) -> str:
    return (
        "⚙️ Grammar check settings\n"
        f"• Status: {'running' if enabled else 'stopped'}\n"
        f"• Level: {level}\n"
        f"• Whitelist: {whitelist_count} term(s)\n"
        f"• Cooldown: {settings.cooldown_seconds}s per user\n"
        f"• Model: {model}\n\n"
        "Pick a strictness level:"
    )


# --- main menu (shown on /start and /menu) ----------------------------------


def main_menu_text(balance_toman: float) -> str:
    return (
        "👋 سلام! من یه ربات گرامر چک و ترجمه انگلیسی‌ام.\n"
        "اینجا جمله بفرست تا چک کنم، یا منو به گروهت اضافه کن.\n\n"
        f"💰 موجودی: {int(balance_toman):,} تومان\n\n"
        "از منوی زیر انتخاب کن:"
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(picon_button("💰", "موجودی و شارژ", "wallet:show"))
    b.add(picon_button("📊", "مصرف من", "menu:usage"))
    b.add(picon_button("💬", "مدل زبانی", "menu:model"))
    b.add(picon_button("⚙️", "تنظیمات", "menu:settings"))
    b.adjust(2, 2)
    return b.as_markup()


def model_text(current: str) -> str:
    return f"💬 مدل زبانی فعلی: {current}\n\nیکی از مدل‌های زیر رو انتخاب کن:"


def model_keyboard(current: str, choices: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for mid, label in choices:
        mark = "▸ " if mid == current else ""
        b.button(text=f"{mark}{label}", callback_data=f"model:{mid}")
    b.button(text="بازگشت", callback_data="menu:home")
    b.adjust(1)
    return b.as_markup()


def usage_text(name: str, requests: int, replies: int, prompt_t: int, completion_t: int, spent_toman: float, balance_toman: float) -> str:
    return (
        f"📊 مصرف {name}\n\n"
        f"• درخواست‌ها: {requests:,}\n"
        f"• اصلاحیه‌های دریافتی: {replies:,}\n"
        f"• توکن‌ها: {prompt_t:,} ورودی / {completion_t:,} خروجی\n"
        f"• هزینه‌ی کسرشده: {int(spent_toman):,} تومان\n"
        f"• موجودی فعلی: {int(balance_toman):,} تومان"
    )


def usage_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="بازگشت", callback_data="menu:home")
    return b.as_markup()


def stats_text(scope: str, stats: dict) -> str:
    lines = [
        f"📊 Statistics ({scope})",
        "",
        f"• Users: {stats['users']}",
        f"• Chats: {stats['chats']}",
        f"• LLM requests: {stats['requests']}",
        f"• Corrections sent: {stats['replies']}",
        f"• Tokens: {stats['prompt_tokens']:,} in / {stats['completion_tokens']:,} out",
        f"• Raw API cost: ${stats['cost']:.4f}",
    ]
    wallet = stats.get("wallet")
    if wallet:
        lines += [
            "",
            "💰 Wallets:",
            f"• Wallets: {wallet['wallets']}",
            f"• Balance held: {int(wallet['balance_toman']):,} Toman",
            f"• Charged to users: {int(wallet['spent_toman']):,} Toman",
            f"• Topped up: {int(wallet['topped_up_toman']):,} Toman",
        ]
    if stats["top"]:
        lines.append("")
        lines.append("Top spenders:")
        for i, u in enumerate(stats["top"], 1):
            lines.append(f"{i}. {u['name']} - ${u['cost']:.4f} ({u['requests']} req)")
    return "\n".join(lines)


def stats_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Refresh", callback_data="stats:show")
    b.button(text="Reset", callback_data="stats:reset")
    b.row(InlineKeyboardButton(text="Back", callback_data="stats:back"))
    return b.as_markup()


def add_to_group_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    kwargs = {"text": "Add me to a group", "url": f"tg://resolve?domain={bot_username}&startgroup=true"}
    eid = icon("➕")
    if eid:
        kwargs["icon_custom_emoji_id"] = eid
    b.row(InlineKeyboardButton(**kwargs))
    return b.as_markup()
