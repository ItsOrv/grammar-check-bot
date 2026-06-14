from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import Settings

LEVEL_BUTTONS = [
    ("strict", "🎓 Strict"),
    ("normal", "✅ Normal"),
    ("casual", "😎 Casual"),
    ("off", "💤 Off"),
]


def settings_keyboard(current_level: str, enabled: bool, is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value, label in LEVEL_BUTTONS:
        text = f"▸ {label} ◂" if value == current_level else label
        builder.button(text=text, callback_data=f"level:{value}")
    builder.adjust(2, 2)
    # The master switch. Shows what tapping it will do, not the current state.
    power = "⏸ Stop the bot" if enabled else "▶️ Start the bot"
    builder.row(InlineKeyboardButton(text=power, callback_data="power:toggle"))
    builder.row(
        InlineKeyboardButton(text="📝 Whitelist", callback_data="whitelist:help"),
        InlineKeyboardButton(text="💰 Wallet", callback_data="wallet:show"),
    )
    if is_admin:
        builder.row(InlineKeyboardButton(text="📊 Statistics", callback_data="stats:show"))
    return builder.as_markup()


def settings_text(level: str, whitelist_count: int, settings: Settings, enabled: bool, model: str) -> str:
    state = "🟢 running" if enabled else "🔴 stopped"
    return (
        "⚙️ Grammar check settings\n"
        f"• Status: {state}\n"
        f"• Level: {level}\n"
        f"• Whitelist: {whitelist_count} term(s)\n"
        f"• Cooldown: {settings.cooldown_seconds}s per user\n"
        f"• Model: {model}\n\n"
        "Pick a strictness level:"
    )


# --- main menu (shown on /start and /menu) ----------------------------------


def main_menu_text(balance_toman: float) -> str:
    return (
        "👋 سلام! من یه ربات گرامر انگلیسی‌ام.\n"
        "اینجا جمله بفرست تا چک کنم، یا منو به گروهت اضافه کن.\n\n"
        f"💰 موجودی: {int(balance_toman):,} تومان\n\n"
        "از منوی زیر انتخاب کن:"
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💰 موجودی و شارژ", callback_data="wallet:show")
    b.button(text="📊 مصرف من", callback_data="menu:usage")
    b.button(text="🧠 مدل زبانی", callback_data="menu:model")
    b.button(text="⚙️ تنظیمات", callback_data="menu:settings")
    b.adjust(2, 2)
    return b.as_markup()


def model_text(current: str) -> str:
    return f"🧠 مدل زبانی فعلی: {current}\n\nیکی از مدل‌های زیر رو انتخاب کن:"


def model_keyboard(current: str, choices: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for mid, label in choices:
        mark = "▸ " if mid == current else ""
        b.button(text=f"{mark}{label}", callback_data=f"model:{mid}")
    b.button(text="⬅️ منوی اصلی", callback_data="menu:home")
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
    b.button(text="⬅️ منوی اصلی", callback_data="menu:home")
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
            lines.append(f"{i}. {u['name']} — ${u['cost']:.4f} ({u['requests']} req)")
    return "\n".join(lines)


def stats_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Refresh", callback_data="stats:show")
    builder.button(text="🧹 Reset", callback_data="stats:reset")
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="stats:back"))
    return builder.as_markup()


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
