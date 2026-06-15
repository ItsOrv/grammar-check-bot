"""Premium (custom) emoji helpers.

Every outgoing message goes through :func:`html` (via a session middleware), which
HTML-escapes the text and swaps any known emoji for its premium custom-emoji
version using the ``<tg-emoji>`` tag. Buttons use :func:`icon` to set
``icon_custom_emoji_id`` (Bot API 9.4). Only emojis that actually exist in a
custom-emoji pack are in the map — everything else is kept plain text-free, so no
ordinary emoji is ever shown.
"""
from html import escape as _escape

_MAP: dict[str, str] = {}
_KEYS: list[str] = []  # map keys longest-first so multi-codepoint emojis win


def configure(mapping: dict[str, str]) -> None:
    _MAP.clear()
    _MAP.update(mapping)
    _KEYS[:] = sorted(_MAP, key=len, reverse=True)


def premiumize(text: str) -> str:
    """Replace every known emoji in ``text`` with its premium custom-emoji tag."""
    for emoji in _KEYS:
        if emoji in text:
            text = text.replace(emoji, f'<tg-emoji emoji-id="{_MAP[emoji]}">{emoji}</tg-emoji>')
    return text


def html(text: str) -> str:
    """Escape dynamic content, then premiumize emojis. Send the result as HTML."""
    return premiumize(_escape(text))


def icon(emoji: str) -> str | None:
    """custom_emoji_id for a button icon, or None if this emoji has no premium version."""
    return _MAP.get(emoji)
