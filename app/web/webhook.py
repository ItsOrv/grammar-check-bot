import json
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiohttp import web
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.database import repo
from app.services.payments.nowpayments import NowPayments

logger = logging.getLogger(__name__)

# NOWPayments statuses that mean the money fully arrived / definitely won't.
_PAID = {"finished"}
_DEAD = {"failed", "expired", "refunded"}


def build_app(
    settings: Settings,
    sessionmaker: async_sessionmaker,
    bot: Bot,
    nowpayments: NowPayments,
) -> web.Application:
    app = web.Application()

    async def health(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def ipn(request: web.Request) -> web.Response:
        raw = await request.read()
        signature = request.headers.get("x-nowpayments-sig")
        try:
            payload = json.loads(raw)
        except Exception:
            return web.Response(status=400, text="bad json")

        if not nowpayments.verify_ipn(payload, signature):
            logger.warning("IPN with bad signature: order=%s", payload.get("order_id"))
            return web.Response(status=403, text="bad signature")

        order_id = str(payload.get("order_id") or "")
        status = str(payload.get("payment_status") or "")
        logger.info("IPN order=%s status=%s", order_id, status)

        async with sessionmaker() as session:
            payment = await repo.get_payment_by_order(session, order_id)
            if payment is None:
                return web.Response(text="unknown order")

            if status in _PAID:
                # Atomically claim the pending->finished transition AND credit the wallet in one
                # transaction. Only the caller that wins the claim credits, so duplicate (even
                # concurrent) callbacks never double-credit, and the credit can't be lost halfway.
                claimed, new_balance = await repo.claim_payment_and_credit(session, order_id, "finished")
                if claimed is None:
                    return web.Response(text="already handled")
                await _notify(
                    bot, claimed.user_id,
                    f"پرداختت تایید شد. {int(claimed.amount_toman):,} تومان به کیف پولت اضافه شد.\n"
                    f"موجودی: {int(new_balance):,} تومان",
                )
            elif status in _DEAD:
                claimed = await repo.claim_payment_if_pending(session, order_id, "failed")
                if claimed is None:
                    return web.Response(text="already handled")
                await _notify(bot, claimed.user_id, "پرداخت کریپتوت ناموفق بود یا منقضی شد.")

        return web.Response(text="ok")

    app.router.add_get("/", health)
    app.router.add_post("/nowpayments/ipn", ipn)
    return app


async def _notify(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        # Expected: the user never opened the bot in private ("chat not found") or blocked it.
        # The payment is already credited and they'll see the balance later — this isn't a crash,
        # so log a concise warning instead of a misleading ERROR traceback.
        logger.warning("could not deliver payment notice to user %s: %s", user_id, exc.message)
    except Exception:
        logger.exception("failed to notify user %s about payment", user_id)


async def start_webhook(app: web.Application, host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("IPN webhook listening on %s:%s", host, port)
    return runner
