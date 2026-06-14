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


def settings_text(level: str, whitelist_count: int, settings: Settings, enabled: bool) -> str:
    state = "🟢 running" if enabled else "🔴 stopped"
    return (
        "⚙️ Grammar check settings\n"
        f"• Status: {state}\n"
        f"• Level: {level}\n"
        f"• Whitelist: {whitelist_count} term(s)\n"
        f"• Cooldown: {settings.cooldown_seconds}s per user\n"
        f"• Model: {settings.llm_model}\n\n"
        "Pick a strictness level:"
    )


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
