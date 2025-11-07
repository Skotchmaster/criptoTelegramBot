import aiohttp
import pandas as pd
from typing import Literal, Optional, List
from ..config import config
from ..utils.errors import DataSourceError

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
BINANCE_EXCHANGE_INFO = "https://api.binance.com/api/v3/exchangeInfo"

Interval = Literal["1h", "4h", "1d"]
_INTERVAL_MAP = {"1h": "1h", "4h": "4h", "1d": "1d"}

async def _binance_symbol_exists(session: aiohttp.ClientSession, symbol: str) -> bool:
    params = {"symbol": symbol}
    async with session.get(BINANCE_EXCHANGE_INFO, params=params, timeout=config.HTTP_TIMEOUT) as resp:
        if resp.status == 200:
            data = await resp.json()
            return any(s["symbol"] == symbol and s.get("status") == "TRADING" for s in data.get("symbols", []))
        return False

async def fetch_klines_binance(session: aiohttp.ClientSession, symbol: str, interval: Interval, limit: int = 200) -> pd.DataFrame:
    """
    symbol: например 'BTCUSDT'
    interval: '1h'|'4h'|'1d'
    """
    params = {"symbol": symbol, "interval": _INTERVAL_MAP[interval], "limit": min(max(limit, 50), 1000)}
    async with session.get(BINANCE_KLINES, params=params, timeout=config.HTTP_TIMEOUT) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise DataSourceError(f"Binance error {resp.status}: {text}")
        raw = await resp.json()
    cols = ["open_time","open","high","low","close","volume","close_time","qav","trades","taker_base","taker_quote","ignore"]
    df = pd.DataFrame(raw, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    for c in ["open","high","low","close","volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna().reset_index(drop=True)
    return df

async def get_ohlcv_for_ticker(session: aiohttp.ClientSession, ticker: str, interval: Interval, limit: int = 400) -> Optional[pd.DataFrame]:
    """
    Пытаемся взять {TICKER}USDT с Binance.
    Возвращает DataFrame или None, если символа нет.
    """
    symbol = f"{ticker.upper()}USDT"
    exists = await _binance_symbol_exists(session, symbol)
    if not exists:
        return None
    return await fetch_klines_binance(session, symbol, interval, limit=limit)
