"""Premium (custom) emoji helpers.

Telegram lets a bot put custom emoji in *message text* (not in buttons — button
text can't carry entities). We render them with the HTML ``<tg-emoji>`` tag, so
any message using ``pe()`` must be sent with ``parse_mode="HTML"``. When an emoji
isn't configured we just fall back to a plain unicode emoji, so nothing breaks.
"""
from html import escape

_MAP: dict[str, str] = {}


def configure(mapping: dict[str, str]) -> None:
    _MAP.clear()
    _MAP.update(mapping)


def pe(key: str, fallback: str) -> str:
    """Premium emoji for ``key`` if configured, otherwise the plain ``fallback``."""
    eid = _MAP.get(key)
    return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>' if eid else fallback


def esc(text: str) -> str:
    """HTML-escape dynamic text (e.g. user names) before putting it in an HTML message."""
    return escape(text or "")
