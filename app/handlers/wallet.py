import logging
import uuid

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.database import repo
from app.services.payments.nowpayments import NowPayments
from app.services.rate import RateProvider, toman_to_usd

logger = logging.getLogger(__name__)

router = Router(name="wallet")

MIN_TOPUP_TOMAN = 10_000


class TopUp(StatesGroup):
    amount = State()  # waiting for a custom amount
    receipt = State()  # waiting for the card-to-card receipt


def _fmt(n: float) -> str:
    return f"{int(n):,}"


def _order_id() -> str:
    return uuid.uuid4().hex[:16]


def _wallet_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💳 شارژ کیف پول", callback_data="wallet:topup")
    b.button(text="🧾 تاریخچه", callback_data="wallet:history")
    b.adjust(1)
    return b.as_markup()


def _methods_keyboard(crypto_on: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💳 کارت به کارت", callback_data="m:card")
    if crypto_on:
        b.button(text="🪙 کریپتو", callback_data="m:crypto")
    b.button(text="⬅️ بازگشت", callback_data="wallet:show")
    b.adjust(1)
    return b.as_markup()


def _amount_keyboard(method: str, presets: list[int]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in presets:
        b.button(text=f"{_fmt(p)} تومان", callback_data=f"amt:{method}:{p}")
    b.button(text="✏️ مبلغ دلخواه", callback_data=f"amtx:{method}")
    b.button(text="⬅️ بازگشت", callback_data="wallet:topup")
    b.adjust(1)
    return b.as_markup()


def _approve_keyboard(order_id: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ تایید", callback_data=f"pay:approve:{order_id}")
    b.button(text="❌ رد", callback_data=f"pay:reject:{order_id}")
    b.adjust(2)
    return b.as_markup()


async def _wallet_text(sessionmaker: async_sessionmaker, settings: Settings, user) -> str:
    async with sessionmaker() as session:
        wallet, _ = await repo.get_or_create_wallet(
            session, user.id, user.full_name, settings.free_credit_toman
        )
        balance, spent = wallet.balance_toman, wallet.spent_toman
    return (
        "💰 کیف پول\n\n"
        f"• موجودی: {_fmt(balance)} تومان\n"
        f"• خرج‌شده تا حالا: {_fmt(spent)} تومان"
    )


# --- entry points -----------------------------------------------------------


@router.message(Command("wallet", "balance"))
async def cmd_wallet(message: Message, sessionmaker: async_sessionmaker, settings: Settings):
    text = await _wallet_text(sessionmaker, settings, message.from_user)
    await message.answer(text, reply_markup=_wallet_keyboard())


@router.callback_query(F.data == "wallet:show")
async def cb_wallet_show(
    callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings, state: FSMContext
):
    await state.clear()
    # In a group the settings message is shared, so don't expose one person's
    # balance there — show it as a private popup and send them to PV to top up.
    if callback.message.chat.type != "private":
        async with sessionmaker() as session:
            wallet, _ = await repo.get_or_create_wallet(
                session, callback.from_user.id, callback.from_user.full_name, settings.free_credit_toman
            )
        await callback.answer(
            f"موجودی: {_fmt(wallet.balance_toman)} تومان\nبرای شارژ به پیوی ربات بیا.",
            show_alert=True,
        )
        return
    text = await _wallet_text(sessionmaker, settings, callback.from_user)
    try:
        await callback.message.edit_text(text, reply_markup=_wallet_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=_wallet_keyboard())
    await callback.answer()


@router.callback_query(F.data == "wallet:topup")
async def cb_topup(callback: CallbackQuery, settings: Settings, nowpayments: NowPayments):
    if callback.message.chat.type != "private":
        await callback.answer("برای شارژ به پیوی ربات بیا 🙏", show_alert=True)
        return
    await callback.message.edit_text(
        "روش پرداخت رو انتخاب کن:", reply_markup=_methods_keyboard(nowpayments.configured)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("m:"))
async def cb_method(callback: CallbackQuery, settings: Settings):
    method = callback.data.split(":", 1)[1]
    label = "کارت به کارت" if method == "card" else "کریپتو"
    await callback.message.edit_text(
        f"مبلغ شارژ ({label}) رو انتخاب کن:", reply_markup=_amount_keyboard(method, settings.topup_presets)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("amtx:"))
async def cb_custom_amount(callback: CallbackQuery, state: FSMContext):
    method = callback.data.split(":", 1)[1]
    await state.set_state(TopUp.amount)
    await state.update_data(method=method)
    await callback.message.edit_text(
        f"مبلغ مورد نظرت رو به تومان بفرست (حداقل {_fmt(MIN_TOPUP_TOMAN)} تومان):"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("amt:"))
async def cb_preset_amount(
    callback: CallbackQuery, state: FSMContext, sessionmaker: async_sessionmaker,
    settings: Settings, rate: RateProvider, nowpayments: NowPayments, bot: Bot,
):
    _, method, value = callback.data.split(":", 2)
    await callback.answer()
    await _start_topup(
        callback.message, state, user_id=callback.from_user.id, name=callback.from_user.full_name,
        method=method, amount=int(value), settings=settings, sessionmaker=sessionmaker,
        rate=rate, nowpayments=nowpayments,
    )


@router.message(TopUp.amount, F.text)
async def on_custom_amount(
    message: Message, state: FSMContext, sessionmaker: async_sessionmaker,
    settings: Settings, rate: RateProvider, nowpayments: NowPayments,
):
    digits = "".join(ch for ch in message.text if ch.isdigit())
    if not digits or int(digits) < MIN_TOPUP_TOMAN:
        await message.reply(f"یه عدد معتبر بفرست (حداقل {_fmt(MIN_TOPUP_TOMAN)} تومان).")
        return
    data = await state.get_data()
    await _start_topup(
        message, state, user_id=message.from_user.id, name=message.from_user.full_name,
        method=data.get("method", "card"), amount=int(digits), settings=settings,
        sessionmaker=sessionmaker, rate=rate, nowpayments=nowpayments,
    )


# --- the actual top-up ------------------------------------------------------


async def _start_topup(
    message: Message, state: FSMContext, *, user_id: int, name: str, method: str, amount: int,
    settings: Settings, sessionmaker: async_sessionmaker, rate: RateProvider, nowpayments: NowPayments,
):
    order_id = _order_id()
    if method == "crypto":
        await state.clear()
        if not nowpayments.configured:
            await message.answer("پرداخت کریپتو فعلا فعال نیست.")
            return
        usd = toman_to_usd(amount, await rate.get_rate())
        invoice = await nowpayments.create_invoice(
            order_id, usd, f"Wallet top-up {amount} Toman (user {user_id})"
        )
        if not invoice or not invoice.get("invoice_url"):
            await message.answer("ساخت فاکتور پرداخت با مشکل خورد، یه بار دیگه امتحان کن.")
            return
        async with sessionmaker() as session:
            await repo.create_payment(
                session, order_id, user_id, "crypto", amount, usd,
                provider_id=str(invoice.get("id", "")), note=invoice["invoice_url"],
            )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🪙 پرداخت", url=invoice["invoice_url"])],
            [InlineKeyboardButton(text="⬅️ کیف پول", callback_data="wallet:show")],
        ])
        await message.answer(
            f"مبلغ {_fmt(amount)} تومان (~${usd}) آماده‌ی پرداخته.\n"
            "روی دکمه‌ی پرداخت بزن. به محض تایید شبکه، موجودیت خودکار شارژ میشه.",
            reply_markup=kb,
        )
        return

    # card to card -> wait for a receipt, then admins approve
    async with sessionmaker() as session:
        await repo.create_payment(session, order_id, user_id, "card", amount)
    await state.set_state(TopUp.receipt)
    await state.update_data(order_id=order_id, amount=amount)
    card = settings.card_number or "(شماره کارت تنظیم نشده)"
    holder = f"\nبه نام: {settings.card_holder}" if settings.card_holder else ""
    await message.answer(
        f"مبلغ {_fmt(amount)} تومان رو به کارت زیر واریز کن:\n\n"
        f"`{card}`{holder}\n\n"
        "بعد از واریز، رسید (عکس یا متن) رو همینجا بفرست تا برای ادمین بره.",
        parse_mode="Markdown",
    )


@router.message(TopUp.receipt)
async def on_receipt(message: Message, state: FSMContext, sessionmaker: async_sessionmaker, settings: Settings):
    data = await state.get_data()
    order_id = data.get("order_id")
    amount = data.get("amount", 0)
    await state.clear()
    if not order_id:
        return

    note = message.text or message.caption or "[رسید بدون متن]"
    async with sessionmaker() as session:
        payment = await repo.get_payment_by_order(session, order_id)
        if payment:
            payment.note = note[:500]
            await session.commit()

    admins = settings.admin_id_set
    if not admins:
        await message.reply("رسید ثبت شد ولی ادمینی برای تایید تنظیم نشده. با پشتیبانی تماس بگیر.")
        return

    sent = False
    for admin_id in admins:
        try:
            await message.copy_to(admin_id)
            await message.bot.send_message(
                admin_id,
                f"🧾 درخواست شارژ کارت به کارت\n"
                f"کاربر: {message.from_user.full_name} (id={message.from_user.id})\n"
                f"مبلغ: {_fmt(amount)} تومان\n"
                f"کد سفارش: {order_id}",
                reply_markup=_approve_keyboard(order_id),
            )
            sent = True
        except Exception:
            logger.exception("failed to forward receipt to admin %s", admin_id)
    if sent:
        await message.reply("✅ رسیدت برای ادمین ارسال شد. بعد از تایید، موجودیت شارژ میشه.")
    else:
        await message.reply("ارسال رسید به ادمین با مشکل خورد، بعدا دوباره امتحان کن.")


@router.callback_query(F.data == "wallet:history")
async def cb_history(callback: CallbackQuery, sessionmaker: async_sessionmaker):
    async with sessionmaker() as session:
        payments = await repo.list_user_payments(session, callback.from_user.id, limit=10)
    if not payments:
        await callback.answer("هنوز پرداختی نداشتی.", show_alert=True)
        return
    status_fa = {
        "pending": "در انتظار", "finished": "موفق", "approved": "تایید شده",
        "rejected": "رد شده", "failed": "ناموفق",
    }
    lines = ["🧾 تاریخچه پرداخت‌ها:\n"]
    for p in payments:
        method = "کارت" if p.method == "card" else "کریپتو"
        lines.append(f"• {_fmt(p.amount_toman)} تومان | {method} | {status_fa.get(p.status, p.status)}")
    await callback.message.edit_text("\n".join(lines), reply_markup=_wallet_keyboard())
    await callback.answer()


# --- admin approval (card to card) ------------------------------------------


@router.callback_query(F.data.startswith("pay:"))
async def cb_admin_decide(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings):
    if callback.from_user.id not in settings.admin_id_set:
        await callback.answer("فقط ادمین.", show_alert=True)
        return
    _, action, order_id = callback.data.split(":", 2)
    async with sessionmaker() as session:
        payment = await repo.get_payment_by_order(session, order_id)
        if payment is None:
            await callback.answer("سفارش پیدا نشد.", show_alert=True)
            return
        if payment.status != "pending":
            await callback.answer(f"قبلا بررسی شده ({payment.status}).", show_alert=True)
            return

        if action == "approve":
            await repo.set_payment_status(session, order_id, "approved")
            new_balance = await repo.credit(session, payment.user_id, payment.amount_toman)
            verdict = f"✅ تایید شد ({_fmt(payment.amount_toman)} تومان)"
            user_msg = (
                f"✅ شارژ {_fmt(payment.amount_toman)} تومانی‌ت تایید شد.\n"
                f"موجودی: {_fmt(new_balance)} تومان"
            )
        else:
            await repo.set_payment_status(session, order_id, "rejected")
            verdict = "❌ رد شد"
            user_msg = f"❌ شارژ {_fmt(payment.amount_toman)} تومانی‌ت رد شد. با پشتیبانی تماس بگیر."

    try:
        await callback.message.edit_text(callback.message.text + f"\n\n{verdict}")
    except Exception:
        pass
    try:
        await callback.bot.send_message(payment.user_id, user_msg)
    except Exception:
        logger.exception("failed to notify user %s of decision", payment.user_id)
    await callback.answer(verdict)
