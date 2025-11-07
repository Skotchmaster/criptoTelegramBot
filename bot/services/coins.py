import aiohttp
import asyncio
from typing import List, Dict, Tuple

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"

async def fetch_top_100_coins(session: aiohttp.ClientSession) -> List[Dict]:
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": 100,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "24h",
    }
    async with session.get(COINGECKO_URL, params=params) as resp:
        resp.raise_for_status()
        return await resp.json()

async def get_top_100_id_symbol_name(session: aiohttp.ClientSession) -> List[Tuple[str, str, str]]:
    """Возвращает список (id, SYMBOL, Name). SYMBOL в верхнем регистре."""
    data = await fetch_top_100_coins(session)
    out = []
    for c in data:
        cid = c.get("id")
        sym = (c.get("symbol") or "").upper()
        name = c.get("name") or cid
        if cid and sym:
            out.append((cid, sym, name))
    return out
