import asyncio
from datetime import datetime, timezone
from typing import List, Tuple, Optional
import pandas as pd

from bot.utils.timeframes import TIMEFRAMES, normalize_symbol
from bot.utils.indicators import rsi_ewma, sma
from bot.utils.patterns import detect_patterns_last
from bot.utils.text import format_summary, format_alert
from bot.storage import JSONStorage

class Scanner:
    def __init__(self, coingecko, binance, storage: JSONStorage, batch_sleep: float = 0.02):
        self.cg = coingecko
        self.bn = binance
        self.storage = storage
        self.batch_sleep = batch_sleep

    async def scannable_pairs(self) -> List[Tuple[str, str]]:
        top = await self.cg.top100()
        usdt = await self.bn.available_usdt_symbols()
        pairs: List[Tuple[str, str]] = []
        for c in top:
            sym = normalize_symbol(c.get("symbol", ""))
            pair = f"{sym}USDT"
            if pair in usdt:
                pairs.append((pair, c.get("name", sym)))
        return pairs

    @staticmethod
    def klines_to_df(klines) -> Optional[pd.DataFrame]:
        if not klines or len(klines) < 9:
            return None
        cols = ["open_time","open","high","low","close","volume","close_time","qav","trades","taker_base","taker_quote","ignore"]
        df = pd.DataFrame(klines, columns=cols)
        for col in ["open","high","low","close","volume"]:
            df[col] = df[col].astype(float)
        import pandas as pd
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        now = pd.Timestamp(datetime.now(timezone.utc))
        df = df[df["close_time"] <= now]
        return df

    @staticmethod
    def eight_in_a_row(df: pd.DataFrame) -> Optional[str]:
        last8 = df.tail(8)
        up = (last8["close"] > last8["open"]).all()
        down = (last8["close"] < last8["open"]).all()
        if up:
            return "green"
        if down:
            return "red"
        return None

    async def scan_once_and_alert(self, application, timeframes: List[str] = None):
        if timeframes is None:
            timeframes = list(TIMEFRAMES.keys())
        pairs = await self.scannable_pairs()
        chats = await self.storage.list_chats()

        tasks = []
        for pair, _ in pairs:
            for tf in timeframes:
                tasks.append((pair, tf))

        CHUNK = 20
        for i in range(0, len(tasks), CHUNK):
            chunk = tasks[i:i+CHUNK]
            await asyncio.gather(*(self._process_pair_tf(application, pair, tf) for pair, tf in chunk))
            await asyncio.sleep(self.batch_sleep)

    async def _process_pair_tf(self, application, pair: str, tf: str):
        raw = await self.bn.get_klines(pair, TIMEFRAMES[tf], limit=10)
        if not raw:
            return
        df = self.klines_to_df(raw)
        if df is None:
            return
        direction = self.eight_in_a_row(df)
        if direction:
            last_close_iso = df.iloc[-1]["close_time"].isoformat()
            key = f"{tf}|{pair}|{last_close_iso}"
            if await self.storage.has_alert(key):
                return
            msg = format_alert(pair, tf, direction, df.iloc[-1]["close_time"])
            for chat_id in await self.storage.list_chats():
                try:
                    await application.bot.send_message(chat_id=chat_id, text=msg, disable_web_page_preview=True, parse_mode="HTML")
                except Exception:
                    pass
            await self.storage.mark_alert(key)

    async def manual_summary(self, pair: str, tf: str) -> Optional[str]:
        raw = await self.bn.get_klines(pair, TIMEFRAMES[tf], limit=100)
        if not raw:
            return None
        df = self.klines_to_df(raw)
        if df is None or len(df) < 50:
            return None

        df["sma20"] = sma(df["close"], 20)
        df["sma50"] = sma(df["close"], 50)
        df["rsi14"] = rsi_ewma(df["close"], 14)

        trend = "bull" if df["sma20"].iloc[-1] > df["sma50"].iloc[-1] else "bear"
        prev_rel = df["sma20"].iloc[-2] - df["sma50"].iloc[-2]
        curr_rel = df["sma20"].iloc[-1] - df["sma50"].iloc[-1]
        cross = "golden" if prev_rel <= 0 and curr_rel > 0 else ("death" if prev_rel >= 0 and curr_rel < 0 else "none")

        patterns = detect_patterns_last(df)

        return format_summary(pair, tf, df.iloc[-1], df["rsi14"].iloc[-1], df["sma20"].iloc[-1], df["sma50"].iloc[-1], trend, cross, patterns)
