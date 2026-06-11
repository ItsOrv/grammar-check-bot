import re
import string
from typing import Protocol

# Entity types whose spans are not English prose worth checking.
_STRIP_ENTITY_TYPES = {"url", "text_link", "mention", "text_mention", "hashtag", "cashtag", "bot_command", "email"}
_CODE_ENTITY_TYPES = {"pre", "code"}

_EMOJI_RE = re.compile(
    "["
    "\U0001f000-\U0001faff"  # emoji & symbols
    "\U00002600-\U000027bf"  # misc symbols, dingbats
    "\U0001f1e6-\U0001f1ff"  # flags
    "✀-➿"
    "︎️‍"
    "]+"
)


class EntityLike(Protocol):
    type: str
    offset: int
    length: int


def should_check(
    text: str | None,
    entities: list[EntityLike] | None,
    min_words: int = 3,
    min_chars: int = 12,
) -> bool:
    """Cheap pre-LLM filter: True only when the message looks like English prose worth checking."""
    if not text:
        return False
    if text.lstrip().startswith("/"):
        return False

    entities = entities or []
    if any(e.type in _CODE_ENTITY_TYPES for e in entities):
        return False

    # Blank out URL/mention/etc. spans so they don't count toward length.
    chars = list(text)
    for e in entities:
        if e.type in _STRIP_ENTITY_TYPES:
            for i in range(e.offset, min(e.offset + e.length, len(chars))):
                chars[i] = " "
    cleaned = _EMOJI_RE.sub(" ", "".join(chars)).strip()

    if len(cleaned) < min_chars or len(cleaned.split()) < min_words:
        return False

    # Mostly non-Latin letters → probably not English; skip.
    letters = [c for c in cleaned if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if c in string.ascii_letters)
    if latin / len(letters) < 0.7:
        return False

    return True
