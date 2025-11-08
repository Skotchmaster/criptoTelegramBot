from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Iterable, List, Sequence

import pandas as pd


class Scanner:
    """
    Сканер «N одинаковых свечей подряд» для таймфреймов 1h/4h/1d.

    Требования к зависимостям:
      - binance.get_klines(symbol, interval, limit=...)
      - storage.get_chats() -> Iterable[int]
    """

    TF_LIMITS = {"1h": 200, "4h": 240, "1d": 500}

    def __init__(
        self,
        coingecko: Any,
        binance: Any,
        storage: Any,
        *,
        batch_sleep: float = 0.02,
        required_streak: int = 8,
        timeframes: Sequence[str] = ("1h", "4h", "1d"),
        klines_limit: int = 120,
    ) -> None:
        self.cg = coingecko
        self.bn = binance
        self.storage = storage
        self.batch_sleep = batch_sleep
        self.required_streak = required_streak
        self.timeframes = list(timeframes)
        self.klines_limit = klines_limit
        self.log = logging.getLogger(__name__)

    async def scannable_pairs(self) -> List[str]:
        """Список доступных торговых пар (до 100 шт.). Используется в /analyze."""
        return await self._resolve_pairs()

    async def scan_once_and_alert(self, application) -> None:
        """Один проход сканера: собираем пары, проверяем все ТФ, шлём алерты (только закрытые свечи)."""
        pairs = await self._resolve_pairs()
        if not pairs:
            self.log.warning("Нет доступных торговых пар для сканирования")
            return

        jobs: List[tuple[str, str]] = [(pair, tf) for pair in pairs for tf in self.timeframes]
        window = 20

        for i in range(0, len(jobs), window):
            chunk = jobs[i: i + window]
            await asyncio.gather(*(self._process_pair_tf(application, pair, tf) for pair, tf in chunk))
            if self.batch_sleep:
                await asyncio.sleep(self.batch_sleep)

    async def _process_pair_tf(self, application, symbol: str, tf: str) -> None:
        """Обработка одной пары на одном таймфрейме: тянем klines, проверяем серию и шлём алерт (без дублей)."""
        try:
            # берём побольше, чтобы точно хватило на фильтры/хвост
            limit = max(200, self.required_streak + 50)
            klines = await self.bn.get_klines(symbol, tf, limit=limit)  # <-- self.bn
        except Exception:
            self.log.exception("binance.get_klines(%s, %s) failed", symbol, tf)
            return

        if not klines:
            return

        # Берём только ЗАКРЫТЫЕ свечи, текущую (незакрытую) отбрасываем
        closed = self._closed_only(klines)
        if not closed:
            return

        # Превращаем в DataFrame нашей формы
        try:
            df = self.klines_to_df(closed)  # <-- klines_to_df
        except Exception:
            self.log.exception("to_df failed for %s %s", symbol, tf)
            return

        if df.empty or len(df) < self.required_streak:
            return

        color = self._streak_color(df, self.required_streak)
        if color is None:
            return

        # Дедупликация: не дублируем алерты для одной и той же закрытой свечи
        last_row = df.iloc[-1]
        try:
            close_ts = int(last_row["close_time"].timestamp())
        except Exception:
            # на случай, если это pandas.Timestamp/str
            close_ts = int(pd.to_datetime(last_row["close_time"]).timestamp())

        dedup_key = f"{symbol}:{tf}:streak{self.required_streak}:{'green' if color=='green' else 'red'}:close{close_ts}"
        try:
            if await self.storage.is_alert_sent(dedup_key):
                return  # уже слали по этой закрытой свече — выходим
        except Exception:
            self.log.exception("storage.is_alert_sent failed")

        # Формируем текст и рассылаем
        last = last_row
        direction_ru = "зелёные" if color == "green" else "красные"
        price = f"{last['close']:.6g}"
        open_t = last["open_time"].strftime("%Y-%m-%d %H:%M UTC")
        close_t = last["close_time"].strftime("%Y-%m-%d %H:%M UTC")

        text = (
            f"⚡️ <b>{symbol}</b> • <code>{tf}</code>\n"
            f"Последние <b>{self.required_streak}</b> свечей — все <b>{direction_ru}</b>.\n"
            f"Цена закрытия: <code>{price}</code>\n"
            f"Открытие: <code>{open_t}</code>\n"
            f"Закрытие: <code>{close_t}</code>"
        )

        try:
            chats: Iterable[int] = await self.storage.get_chats()
        except Exception:
            self.log.exception("get_chats() failed")
            return

        tasks = [
            application.bot.send_message(
                chat_id=chat_id, text=text, parse_mode="HTML", disable_notification=True
            )
            for chat_id in set(chats)
        ]
        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
                # помечаем как отправленное только после успешной рассылки
                try:
                    await self.storage.mark_alert_sent(dedup_key)
                except Exception:
                    self.log.exception("storage.mark_alert_sent failed")
            except Exception:
                self.log.exception("send_message failed for %s %s", symbol, tf)

    @staticmethod
    def _closed_only(klines: Sequence[Sequence]) -> List[Sequence]:
        """Отбрасываем текущую незакрытую свечу (k[6] = closeTime в ms, он должен быть <= now)."""
        if not klines:
            return []
        now_ms = int(time.time() * 1000)
        return [k for k in klines if int(k[6]) <= now_ms]

    def klines_to_df(self, klines: List[List[Any]]) -> pd.DataFrame:
        """
        Преобразование klines в DataFrame с корректными типами.
        Используются ТОЛЬКО закрытые свечи.
        """
        rows = self._closed_only(klines)
        if not rows:
            return pd.DataFrame()

        cols = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ]
        df = pd.DataFrame(rows, columns=cols)

        # типы
        num_cols = ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base", "taker_buy_quote"]
        df[num_cols] = df[num_cols].astype(float, errors="ignore")

        # времена
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

        return df

    def _streak_color(self, df: pd.DataFrame, n: int) -> str | None:
        """Возвращает 'green'/'red' если ПОСЛЕДНИЕ n СЗАКРЫТЫХ свечей одного цвета, иначе None."""
        if len(df) < n:
            return None
        tail = df.tail(n)
        up = (tail["close"] > tail["open"]).all()
        down = (tail["close"] < tail["open"]).all()
        if up and not down:
            return "green"
        if down and not up:
            return "red"
        return None

    async def _resolve_pairs(self) -> List[str]:
        """Пытается получить топ USDT-пар из Binance/CoinGecko, иначе фолбэк."""
        for meth in ("get_top_usdt_pairs", "list_top_usdt_pairs", "top_pairs"):
            if hasattr(self.bn, meth):
                try:
                    pairs = await getattr(self.bn, meth)(limit=100)
                    pairs = [p for p in pairs if isinstance(p, str)]
                    if pairs:
                        return pairs[:100]
                except Exception as e:
                    self.log.debug("%s() failed: %s", meth, e)

        for meth in ("get_exchange_info", "exchange_info"):
            if hasattr(self.bn, meth):
                try:
                    info = await getattr(self.bn, meth)()
                    symbols = info.get("symbols") or []
                    pairs = [
                        s["symbol"]
                        for s in symbols
                        if s.get("status") == "TRADING"
                        and s.get("quoteAsset") == "USDT"
                        and s.get("isSpotTradingAllowed", True)
                    ]
                    if pairs:
                        return pairs[:100]
                except Exception as e:
                    self.log.debug("%s() failed: %s", meth, e)

        for meth in ("top_coins", "get_top_coins", "markets_top"):
            if hasattr(self.cg, meth):
                try:
                    items = await getattr(self.cg, meth)(limit=120)
                    syms = []
                    for it in items or []:
                        sym = (it.get("symbol") or it.get("ticker") or "").upper()
                        if sym and sym.isalpha() and 3 <= len(sym) <= 6:
                            syms.append(sym + "USDT")
                    if syms:
                        return syms[:100]
                except Exception as e:
                    self.log.debug("coingecko.%s() failed: %s", meth, e)

        return [
            "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","TONUSDT","TRXUSDT","DOTUSDT",
            "MATICUSDT","AVAXUSDT","LINKUSDT","APTUSDT","NEARUSDT","ATOMUSDT","LTCUSDT","UNIUSDT","FILUSDT","AAVEUSDT",
        ]
