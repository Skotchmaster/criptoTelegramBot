import time
from typing import Any, Dict, List, Tuple

COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"

class CoinGecko:
    def __init__(self, http, cache_ttl: int = 900):
        self.http = http
        self.cache_ttl = cache_ttl
        self._cache: Tuple[float, List[Dict]] | None = None  # (expires_at, data)

    async def top100(self) -> List[Dict]:
        now = time.time()
        if self._cache and self._cache[0] > now:
            return self._cache[1]
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 100,
            "page": 1,
        }
        data = await self.http.get_json(COINGECKO_MARKETS, params=params)
        expires_at = now + self.cache_ttl
        self._cache = (expires_at, data)
        return data
