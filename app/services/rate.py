import asyncio
import logging
import math
import time

import aiohttp

from app.config import Settings

logger = logging.getLogger(__name__)


class RateProvider:
    """USD -> Toman, pulled live (default: USDT price on Wallex) and cached.

    We read the USDT/Toman market price as a proxy for the free-market dollar.
    If the fetch fails we fall back to the configured value, so billing never
    blocks on the network.
    """

    def __init__(self, settings: Settings):
        self.url = settings.rate_api_url
        self.ttl = settings.rate_ttl_seconds
        self.fallback = settings.usd_to_toman_fallback
        self._value = settings.usd_to_toman_fallback
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def get_rate(self) -> float:
        if time.monotonic() - self._fetched_at < self.ttl:
            return self._value
        async with self._lock:
            if time.monotonic() - self._fetched_at < self.ttl:
                return self._value
            rate = await self._fetch()
            if rate and rate > 0:
                self._value = rate
                self._fetched_at = time.monotonic()
            else:
                # Keep serving the last good value; only log so we notice.
                logger.warning("rate fetch failed, using %.0f Toman/USD", self._value)
        return self._value

    async def _fetch(self) -> float | None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    data = await resp.json(content_type=None)
        except Exception:
            logger.exception("rate API request failed")
            return None

        try:
            # Wallex: {"result": {"symbols": {"USDTTMN": {"stats": {...}}}}}  (Toman)
            symbols = (data.get("result") or {}).get("symbols") or {}
            stats = (symbols.get("USDTTMN") or {}).get("stats") or {}
            price = float(stats.get("lastPrice") or stats.get("bidPrice") or 0)
            if price > 0:
                return price  # already Toman

            # Nobitex fallback: {"stats": {"usdt-rls": {"latest": "..."}}}  (Rial)
            for pair in (data.get("stats") or {}).values():
                latest = float(pair.get("latest") or pair.get("bestSell") or 0)
                if latest > 0:
                    return latest / 10.0  # Rial -> Toman
        except (AttributeError, TypeError, ValueError):
            logger.warning("unexpected rate API payload: %.200s", str(data))
        return None


def cost_to_toman(usd_cost: float, rate: float, markup: float) -> int:
    """Raw API cost (USD) -> what we charge the user (Toman), rounded up."""
    return math.ceil(usd_cost * rate * markup)


def toman_to_usd(amount_toman: float, rate: float) -> float:
    """Used when sending a top-up to a USD-priced crypto processor."""
    if rate <= 0:
        return 0.0
    return round(amount_toman / rate, 2)
