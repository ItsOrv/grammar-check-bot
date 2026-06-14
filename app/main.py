import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

from app.config import Settings
from app.database.session import create_engine_and_sessionmaker, init_db
from app.handlers import callbacks, commands, membership, messages, private, wallet
from app.services.cooldown import Cooldown
from app.services.llm import create_checker
from app.services.payments.nowpayments import NowPayments
from app.services.rate import RateProvider
from app.web.webhook import build_app, start_webhook

logger = logging.getLogger(__name__)

GROUP_COMMANDS = [
    BotCommand(command="settings", description="Open the settings panel (buttons)"),
    BotCommand(command="strict", description="Strict: formal English, every mistake counts"),
    BotCommand(command="normal", description="Normal: standard grammar, minor stuff ignored"),
    BotCommand(command="casual", description="Casual: slang ok, only meaning-breaking errors"),
    BotCommand(command="off", description="Turn grammar checking off"),
    BotCommand(command="stop", description="Pause the bot"),
    BotCommand(command="resume", description="Start the bot again"),
    BotCommand(command="t", description="Translate text to English (tone matches the level)"),
    BotCommand(command="status", description="Show current settings"),
    BotCommand(command="stats", description="Usage statistics (admins)"),
    BotCommand(command="whitelist", description="Show/add/remove never-flag terms"),
]

PRIVATE_COMMANDS = [
    BotCommand(command="start", description="What I do and how to use me"),
    BotCommand(command="settings", description="Pick a strictness level"),
    BotCommand(command="wallet", description="Your balance and top-up"),
    BotCommand(command="t", description="Translate text to English"),
    BotCommand(command="stop", description="Pause checking here"),
    BotCommand(command="resume", description="Resume checking here"),
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
    rate = RateProvider(settings)
    nowpayments = NowPayments(
        settings.nowpayments_api_key, settings.nowpayments_ipn_secret, settings.nowpayments_ipn_url
    )
    dp = Dispatcher(
        storage=MemoryStorage(),
        settings=settings,
        sessionmaker=sessionmaker,
        checker=create_checker(settings),
        cooldown=Cooldown(settings.cooldown_seconds),
        rate=rate,
        nowpayments=nowpayments,
        llm_semaphore=asyncio.Semaphore(settings.max_concurrent_llm),
    )
    dp.include_router(commands.router)
    dp.include_router(callbacks.router)
    dp.include_router(wallet.router)
    dp.include_router(membership.router)
    dp.include_router(private.router)
    dp.include_router(messages.router)

    # IPN webhook for crypto payments, run next to the polling loop.
    runner = None
    if nowpayments.configured:
        app = build_app(settings, sessionmaker, bot, nowpayments)
        runner = await start_webhook(app, settings.webhook_host, settings.webhook_port)
    else:
        logger.info("NOWPayments not configured, IPN webhook disabled")

    await bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())
    logger.info("Starting polling (provider=%s, model=%s)", settings.llm_provider, settings.llm_model)
    try:
        await dp.start_polling(bot)
    finally:
        if runner is not None:
            await runner.cleanup()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
