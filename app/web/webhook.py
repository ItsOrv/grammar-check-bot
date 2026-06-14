import json
import logging

from aiogram import Bot
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
            # Idempotent: only act while still pending, so repeated callbacks don't double-credit.
            if payment.status != "pending":
                return web.Response(text="already handled")

            if status in _PAID:
                await repo.set_payment_status(session, order_id, "finished")
                new_balance = await repo.credit(session, payment.user_id, payment.amount_toman)
                await _notify(
                    bot, payment.user_id,
                    f"✅ پرداختت تایید شد. {int(payment.amount_toman):,} تومان به کیف پولت اضافه شد.\n"
                    f"موجودی: {int(new_balance):,} تومان",
                )
            elif status in _DEAD:
                await repo.set_payment_status(session, order_id, "failed")
                await _notify(bot, payment.user_id, "❌ پرداخت کریپتوت ناموفق بود یا منقضی شد.")

        return web.Response(text="ok")

    app.router.add_get("/", health)
    app.router.add_post("/nowpayments/ipn", ipn)
    return app


async def _notify(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except Exception:
        logger.exception("failed to notify user %s about payment", user_id)


async def start_webhook(app: web.Application, host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("IPN webhook listening on %s:%s", host, port)
    return runner
