"""Outgoing-message middleware that turns plain text into premium-emoji HTML.

It only touches sendMessage / editMessageText calls that don't already set a
parse_mode (so the /emojiid HTML helper and the Markdown card message are left
alone), and callback-answer popups are never touched since they can't render
custom emoji anyway.
"""
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import EditMessageText, SendMessage

from app import premium


class PremiumEmojiMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        if isinstance(method, (SendMessage, EditMessageText)):
            text = getattr(method, "text", None)
            # Only when the caller didn't pick a parse_mode explicitly (a real str).
            if text and not isinstance(method.parse_mode, str):
                method.text = premium.html(text)
                method.parse_mode = "HTML"
        return await make_request(bot, method)
