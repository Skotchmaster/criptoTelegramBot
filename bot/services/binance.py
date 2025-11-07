import asyncio
import time
import logging
from typing import Any, Dict, List, Optional, Tuple
from yarl import URL
import aiohttp
import pandas as pd

log = logging.getLogger("bot.services.binance")

# Основной и резервные домены спотового API
_BINANCE_BASES = [
    "https://api.binance.com",
    "https://api-gcp.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
]

_VALID_INTERVALS = {"1h", "4h", "1d"}

# Хватит истории для SMA50/RSI и паттернов (особенно на 4h/1d)
_INTERVAL_LIMITS = {
    "1h": 500,
    "4h": 500,
    "1d": 500,
}

class Binance:
    def __init__(
        self,
        http,
        cache_ttl_exchange: int = 3600,
        semaphore_limit: int = 8,
        request_timeout: float = 30.0,
        max_retries: int = 3,
    ):
        """
        http: твой общий HttpClient с aiohttp.ClientSession
        """
        self.http = http
        self.cache_ttl_exchange = cache_ttl_exchange
        self._ex_cache: Tuple[float, Dict] | None = None  # (expires_at, data)
        self.sem = asyncio.Semaphore(semaphore_limit)
        self._bases = list(_BINANCE_BASES)
        self._base_idx = 0
        self.request_timeout = request_timeout
        self.max_retries = max_retries

    # ------------ Внутренние утилиты ------------

    def _base(self) -> str:
        return self._bases[self._base_idx % len(self._bases)]

    def _switch_base(self):
        self._base_idx = (self._base_idx + 1) % len(self._bases)
        log.warning("Binance: переключаюсь на запасной домен: %s", self._base())

    async def _get_json_retry(self, url: str, *, params: Optional[Dict] = None) -> Any:
        """
        Универсальный геттер с ретраями, фолбэком на домены и подробными логами.
        """
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                log.debug("GET %s params=%s (attempt %d/%d)", url, params, attempt, self.max_retries)
                data = await self.http.get_json(url, params=params, timeout=self.request_timeout)
                return data
            except aiohttp.ClientResponseError as e:
                text = ""
                try:
                    if e.response is not None:
                        text = await e.response.text()
                except Exception:
                    pass
                if e.status in (418, 429):
                    wait = min(2 ** attempt, 15)
                    log.warning("Binance HTTP %s (rate limit). %s — retry через %ss",
                                e.status, url, wait)
                    await asyncio.sleep(wait)
                    continue
                log.error("Binance HTTP %s: %s params=%s body=%s",
                          e.status, url, params, text[:300])
                if e.status >= 500 and attempt < self.max_retries:
                    self._switch_base()
                    continue
                last_err = e
                break
            except (aiohttp.ClientConnectorError,
                    aiohttp.ClientOSError,
                    aiohttp.ServerDisconnectedError,
                    aiohttp.TooManyRedirects,
                    asyncio.TimeoutError) as e:
                wait = min(2 ** attempt, 10)
                log.warning("Binance network error: %r on %s (retry in %ss)", e, url, wait)
                self._switch_base()
                await asyncio.sleep(wait)
                last_err = e
                continue
            except Exception as e:
                log.exception("Binance unknown error on %s params=%s", url, params)
                last_err = e
                break
        if last_err:
            raise last_err
        raise RuntimeError("Unknown Binance error without exception")

    # ------------ Публичные методы ------------

    async def exchange_info(self) -> Dict:
        now = time.time()
        if self._ex_cache and self._ex_cache[0] > now:
            return self._ex_cache[1]
        url = str(URL(self._base()) / "api" / "v3" / "exchangeInfo")
        data = await self._get_json_retry(url)
        if not isinstance(data, dict):
            log.error("exchangeInfo: unexpected payload type: %r", type(data))
            data = {}
        self._ex_cache = (now + self.cache_ttl_exchange, data)
        return data

    async def available_usdt_symbols(self) -> set[str]:
        info = await self.exchange_info()
        symbols = set()
        for s in info.get("symbols", []) or []:
            try:
                if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
                    sym = s.get("symbol")
                    if sym:
                        symbols.add(sym)
            except Exception:
                continue
        if not symbols:
            log.warning("available_usdt_symbols: пустой список — возможно, проблема сети/блокировок")
        return symbols

    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> Optional[List[List[Any]]]:
        """
        Возвращает «сырые» свечи Binance (list[list[Any]]) или None при фатальной ошибке.
        """
        symbol = (symbol or "").upper().strip()
        if interval not in _VALID_INTERVALS:
            log.error("get_klines: invalid interval=%r (allowed: %s)", interval, sorted(_VALID_INTERVALS))
            return None
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        url = str(URL(self._base()) / "api" / "v3" / "klines")

        async with self.sem:
            try:
                data = await self._get_json_retry(url, params=params)
            except Exception as e:
                log.error("get_klines failed for %s %s: %r", symbol, interval, e)
                return None

        if not isinstance(data, list):
            log.error("get_klines: non-list response for %s %s: %r", symbol, interval, data)
            return None

        if len(data) == 0:
            log.warning("get_klines: empty response for %s %s", symbol, interval)
            return []

        try:
            c = data[-1][4]
            log.debug("get_klines OK: %s %s len=%s last_close=%s", symbol, interval, len(data), c)
        except Exception:
            pass

        return data

    # ------------ Удобно для анализа: DataFrame ------------

    @staticmethod
    def _klines_to_df(data: List[List[Any]]) -> pd.DataFrame:
        """
        Превращает список kline-строк в DataFrame с нужными колонками и типами.
        """
        if not data:
            return pd.DataFrame()

        cols = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base", "taker_buy_quote", "ignore"
        ]
        df = pd.DataFrame(data, columns=cols)

        # Числа -> float
        for c in ["open", "high", "low", "close", "volume",
                  "quote_asset_volume", "taker_buy_base", "taker_buy_quote"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")

        # Время -> datetime UTC
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

        # Дропнем битые строки (например, без close)
        df = df.dropna(subset=["close"])

        return df.reset_index(drop=True)

    async def get_klines_df(self, symbol: str, interval: str, limit: Optional[int] = None) -> pd.DataFrame:
        """
        Возвращает ЧИСТЫЙ DataFrame со свечами:
        - только закрытые бары,
        - выбрасывает потенциально «битую» последнюю свечу,
        - dropna и float64 для цен.
        """
        if interval not in _VALID_INTERVALS:
            raise ValueError(f"Unsupported interval: {interval}")

        limit = int(limit or _INTERVAL_LIMITS.get(interval, 500))

        raw = await self.get_klines(symbol, interval, limit=limit)
        if raw is None or not raw:
            return pd.DataFrame()

        df = self._klines_to_df(raw)
        if df.empty:
            return df

        now_utc = pd.Timestamp.utcnow()
        # убрать формирующуюся последнюю свечу, если вдруг попала
        if not df.empty and df["close_time"].iloc[-1] > now_utc:
            df = df.iloc[:-1]

        # защита от последней «битой» свечи
        if not df.empty:
            last_close = df["close"].iloc[-1]
            last_vol = df["volume"].iloc[-1]
            if pd.isna(last_close) or (isinstance(last_vol, (int, float)) and last_vol == 0):
                df = df.iloc[:-1]

        # финальная чистка
        df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
        for c in ["open", "high", "low", "close"]:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
        df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)

        return df
