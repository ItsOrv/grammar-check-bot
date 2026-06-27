import hashlib
import hmac
import json
import logging

import aiohttp

logger = logging.getLogger(__name__)

API_BASE = "https://api.nowpayments.io/v1"


class NowPayments:
    """Thin client for the bits we use: create an invoice and verify IPN callbacks."""

    def __init__(self, api_key: str, ipn_secret: str, ipn_url: str):
        self.api_key = api_key
        self.ipn_secret = ipn_secret
        self.ipn_url = ipn_url

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def create_invoice(
        self, order_id: str, amount_usd: float, description: str, pay_currency: str = ""
    ) -> dict | None:
        """Create a hosted invoice. Returns the parsed response (with invoice_url) or None.

        ``pay_currency`` locks the invoice to a single coin (e.g. "trx"), so the order is
        bound by that coin's minimum rather than NOWPayments' much higher aggregate floor.
        """
        payload = {
            "price_amount": amount_usd,
            "price_currency": "usd",
            "order_id": order_id,
            "order_description": description,
        }
        if pay_currency:
            payload["pay_currency"] = pay_currency
        if self.ipn_url:
            payload["ipn_callback_url"] = self.ipn_url
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{API_BASE}/invoice",
                    json=payload,
                    headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status >= 400:
                        logger.warning("NOWPayments invoice error %s: %s", resp.status, data)
                        return None
                    return data
        except Exception:
            logger.exception("NOWPayments invoice request failed")
            return None

    def verify_ipn(self, payload: dict, signature: str | None) -> bool:
        """IPN signature is HMAC-SHA512 of the key-sorted JSON body, signed with the IPN secret."""
        if not self.ipn_secret or not signature:
            return False
        message = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        expected = hmac.new(self.ipn_secret.encode(), message, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature)
