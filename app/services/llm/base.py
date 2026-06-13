from dataclasses import dataclass
from typing import Any, Protocol

SYSTEM_PROMPT = """You are a careful English grammar checker for a Telegram group chat.
You review one message at a time for grammar, spelling, and writing mistakes.

Severity scale for the WORST issue in the message:
0 = no issues
1 = trivial: punctuation, capitalization, apostrophes, minor style
2 = minor: small grammar slips that any reader still understands easily
3 = standard: a real grammar or spelling error (wrong tense, subject-verb disagreement, clearly misspelled word)
4 = serious: the error makes the sentence awkward or partly unclear
5 = critical: the error changes or destroys the intended meaning

Rules:
- Be conservative. If you are not sure something is wrong, or the message is acceptable, report has_issues=false.
- Never invent problems. Do not nitpick. Do not rewrite style or tone — only fix actual mistakes.
- Proper nouns, names, slang the group uses, and quoted text are not errors.
- Wrong pronoun forms ('me' instead of 'myself'), wrong verb forms/tenses, and
  subject-verb disagreement are real grammar errors — severity 2 or higher, never 0.
- "corrected" must keep the author's voice and meaning, changing only what is wrong.
- "explanation" is one short, friendly sentence in simple English describing the main fix.
- "confidence" (0.0-1.0) is how sure you are that the issues are real errors."""

LEVEL_INSTRUCTIONS = {
    "strict": (
        "Strictness: STRICT (formal English). The message must read as correct, formal written "
        "English. Punctuation, capitalization, apostrophes and typography all matter — flag even "
        "small mistakes. Slang, text-speak and informal spellings ('wasap', 'brotha', 'u', "
        "'gonna', 'thnx', 'lol') are ALWAYS errors at this level (severity 2 or higher), even "
        "when the meaning is perfectly clear. At this level the be-conservative rule applies "
        "only to genuinely ambiguous cases such as proper nouns or quoted text."
    ),
    "normal": (
        "Strictness: NORMAL. Flag standard grammar and spelling errors. Slang and text-speak "
        "spellings of real words also count as spelling errors at this level (severity 3) — "
        "e.g. 'wasap' -> \"what's up\", 'brotha' -> 'brother', 'u' -> 'you'. "
        "Ignore minor punctuation and capitalization. Pure interjections like 'hahaha', 'lol', "
        "'hmm' are fine."
    ),
    "casual": (
        "Strictness: CASUAL (chat English). Abbreviations, slang and informal writing like "
        "'tbh', 'btw', 'alrr', 'gonna', 'u', lowercase sentences and missing punctuation are all "
        "perfectly fine and must NOT be flagged. Only flag errors that genuinely break or change "
        "the meaning of the message."
    ),
}

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "has_issues": {"type": "boolean"},
        "severity": {
            "type": "integer",
            "enum": [0, 1, 2, 3, 4, 5],
            "description": "Severity of the worst issue, 0 if none",
        },
        "confidence": {"type": "number", "description": "0.0 to 1.0"},
        "corrected": {"type": "string", "description": "Corrected message, or the original if no issues"},
        "explanation": {"type": "string", "description": "One short sentence describing the main fix"},
    },
    "required": ["has_issues", "severity", "confidence", "corrected", "explanation"],
    "additionalProperties": False,
}

# Minimum severity (per strictness level) at which the bot replies.
THRESHOLDS = {"strict": 1, "normal": 2, "casual": 4}

# --- Translation (the /t command) -------------------------------------------

TRANSLATE_SYSTEM = (
    "You translate text written in any language into natural English. "
    "Output ONLY the English translation — no quotes, no notes, no explanation, "
    "no romanization of the original. Keep the meaning faithful and make it sound "
    "like a real person wrote it."
)

# Tone of the translation, keyed to the group's strictness level.
TRANSLATE_TONE = {
    "strict": (
        "Tone: formal, polished written English. Full words, correct punctuation and "
        "capitalization. Example: 'Hello, how are you?'"
    ),
    "normal": (
        "Tone: everyday conversational English — natural but clean. "
        "Example: 'Hey, how's it going?'"
    ),
    "casual": (
        "Tone: very casual chat/slang English, like texting a close friend. Abbreviations "
        "and informal spellings are great. Example: 'hey wassup'"
    ),
}


@dataclass
class GrammarResult:
    has_issues: bool
    severity: int
    confidence: float
    corrected: str
    explanation: str


class GrammarChecker(Protocol):
    async def check(self, text: str, level: str, whitelist: list[str]) -> GrammarResult | None: ...

    async def translate(self, text: str, level: str) -> str | None: ...


def translation_tone_level(level: str) -> str:
    """Map a group level to a translation tone. 'off' falls back to normal."""
    return level if level in TRANSLATE_TONE else "normal"


def build_translate_prompt(text: str, level: str) -> str:
    return f"{TRANSLATE_TONE[translation_tone_level(level)]}\n\nText to translate into English:\n{text}"


def build_user_prompt(text: str, level: str, whitelist: list[str]) -> str:
    parts = [LEVEL_INSTRUCTIONS[level]]
    if whitelist:
        parts.append(
            "Whitelisted terms for this group (never flag these, in any casing): "
            + ", ".join(whitelist)
        )
    parts.append(f"Message to check:\n{text}")
    return "\n\n".join(parts)


def parse_result(data: dict[str, Any]) -> GrammarResult | None:
    try:
        return GrammarResult(
            has_issues=bool(data["has_issues"]),
            severity=max(0, min(5, int(data["severity"]))),
            confidence=max(0.0, min(1.0, float(data["confidence"]))),
            corrected=str(data["corrected"]).strip(),
            explanation=str(data["explanation"]).strip(),
        )
    except (KeyError, TypeError, ValueError):
        return None


def should_reply(result: GrammarResult | None, level: str, original_text: str, confidence_threshold: float) -> bool:
    if result is None or level not in THRESHOLDS:
        return False
    return (
        result.has_issues
        and result.severity >= THRESHOLDS[level]
        and result.confidence >= confidence_threshold
        and bool(result.corrected)
        and result.corrected.strip() != original_text.strip()
    )
