import time
import asyncio
from typing import Any, Dict, List, Optional, Tuple

BINANCE_EXCHANGE_INFO = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"

class Binance:
    def __init__(self, http, cache_ttl_exchange: int = 3600, semaphore_limit: int = 10):
        self.http = http
        self.cache_ttl_exchange = cache_ttl_exchange
        self._ex_cache: Tuple[float, Dict] | None = None  # (expires_at, data)
        self.sem = asyncio.Semaphore(semaphore_limit)

    async def exchange_info(self) -> Dict:
        now = time.time()
        if self._ex_cache and self._ex_cache[0] > now:
            return self._ex_cache[1]
        data = await self.http.get_json(BINANCE_EXCHANGE_INFO)
        self._ex_cache = (now + self.cache_ttl_exchange, data)
        return data

    async def available_usdt_symbols(self) -> set[str]:
        info = await self.exchange_info()
        symbols = set()
        for s in info.get("symbols", []):
            if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
                symbols.add(s.get("symbol"))
        return symbols

    async def get_klines(self, symbol: str, interval: str, limit: int = 10) -> Optional[List[List[Any]]]:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        async with self.sem:
            try:
                data = await self.http.get_json(BINANCE_KLINES, params=params)
                return data
            except Exception:
                return None
