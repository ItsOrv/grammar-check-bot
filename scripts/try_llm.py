"""Quick standalone check of the configured LLM provider.

Usage:  python -m scripts.try_llm "she go to school yesterday"
"""

import asyncio
import sys

from app.config import Settings
from app.services.llm import create_checker


async def main() -> None:
    text = sys.argv[1] if len(sys.argv) > 1 else "she go to school yesterday and buyed three apple"
    settings = Settings()
    checker = create_checker(settings)
    for level in ("strict", "normal", "casual"):
        result = await checker.check(text, level, whitelist=[])
        print(f"[{level}] {result}")


if __name__ == "__main__":
    asyncio.run(main())
