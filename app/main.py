import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats

from app.config import Settings
from app.database.session import create_engine_and_sessionmaker, init_db
from app.handlers import callbacks, commands, membership, messages, private
from app.services.cooldown import Cooldown
from app.services.llm import create_checker

logger = logging.getLogger(__name__)

GROUP_COMMANDS = [
    BotCommand(command="settings", description="Open the settings panel (buttons)"),
    BotCommand(command="strict", description="Strict: formal English, every mistake counts"),
    BotCommand(command="normal", description="Normal: standard grammar, minor stuff ignored"),
    BotCommand(command="casual", description="Casual: slang ok, only meaning-breaking errors"),
    BotCommand(command="off", description="Turn grammar checking off"),
    BotCommand(command="status", description="Show current settings"),
    BotCommand(command="whitelist", description="Show/add/remove never-flag terms"),
]


async def main() -> None:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    engine, sessionmaker = create_engine_and_sessionmaker(settings.db_path)
    await init_db(engine)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(
        settings=settings,
        sessionmaker=sessionmaker,
        checker=create_checker(settings),
        cooldown=Cooldown(settings.cooldown_seconds),
        llm_semaphore=asyncio.Semaphore(settings.max_concurrent_llm),
    )
    dp.include_router(commands.router)
    dp.include_router(callbacks.router)
    dp.include_router(membership.router)
    dp.include_router(private.router)
    dp.include_router(messages.router)

    await bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())
    logger.info("Starting polling (provider=%s, model=%s)", settings.llm_provider, settings.llm_model)
    try:
        await dp.start_polling(bot)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
