import hashlib
import hmac
import json
import logging
import time

import aiohttp

logger = logging.getLogger(__name__)


class RialEX:
    """Thin client for the RialEX card-to-card gateway.

    Flow: we POST a payment (amount in Toman) and get back a ``payment_url`` — a
    Telegram deep link into the gateway's bot where the user pays card-to-card and
    uploads a receipt. The gateway calls our ``callback_url`` (an HMAC-signed
    webhook) when an admin approves/rejects it.

    Auth is Stripe-style HMAC: ``X-Signature = HMAC_SHA256(secret, "{ts}." + body)``
    over the EXACT body bytes we send, with ``Authorization: Bearer <public_key>``.
    The webhook is signed with the same secret, so we verify it the same way.
    """

    def __init__(self, base_url: str, public_key: str, secret_key: str, callback_url: str):
        self.base_url = base_url.rstrip("/")
        self.public_key = public_key
        self.secret_key = secret_key
        self.callback_url = callback_url

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.public_key and self.secret_key and self.callback_url)

    def _sign(self, ts: str, raw: bytes) -> str:
        return hmac.new(
            self.secret_key.encode("utf-8"), f"{ts}.".encode() + raw, hashlib.sha256
        ).hexdigest()

    async def create_payment(self, order_id: str, amount_toman: int) -> dict | None:
        """Create a payment. Returns the parsed response (with payment_url) or None."""
        body = {
            "amount": int(amount_toman),
            "merchant_order_id": order_id,
            "callback_url": self.callback_url,
        }
        raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ts = str(int(time.time()))
        headers = {
            "Authorization": f"Bearer {self.public_key}",
            "X-Timestamp": ts,
            "X-Signature": self._sign(ts, raw),
            "Content-Type": "application/json",
            "Idempotency-Key": order_id,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/v1/payments",
                    data=raw,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status >= 400:
                        logger.warning("RialEX create error %s: %s", resp.status, data)
                        return None
                    return data
        except Exception:
            logger.exception("RialEX create_payment request failed")
            return None

    def verify_webhook(self, raw_body: bytes, timestamp: str | None, signature: str | None) -> bool:
        """Verify an inbound webhook (X-Webhook-Timestamp / X-Webhook-Signature)."""
        if not self.secret_key or not timestamp or not signature:
            return False
        expected = self._sign(timestamp, raw_body)
        return hmac.compare_digest(expected, signature)
