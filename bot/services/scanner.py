from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Iterable, List, Sequence

import pandas as pd
from telegram.error import Forbidden, BadRequest  # PTB exceptions

from bot.services.analysis import analyze
from bot.utils.indicators import rsi_ewma
from bot.services.patterns.dragon import DragonDetector, DragonPattern, DragonPoint

log = logging.getLogger("bot.scanner")


class Scanner:
    """
    Сканер «N одинаковых свечей подряд» для таймфреймов 1h/4h/1d.

    Требования к зависимостям:
      - binance.get_klines(symbol, interval, limit=...)
      - storage.get_chats() -> Iterable[int]
      - storage.is_alert_sent(chat_id, key)
      - storage.mark_alert_sent(chat_id, key, ttl_days: int | None = None)
    """

    TF_LIMITS = {"1h": 200, "4h": 240, "1d": 500}
    RSI_TIMEFRAMES = ("1h", "4h", "1d")
    DRAGON_TIMEFRAMES = ("1h", "4h", "1d")

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
        self.dragon_detector = DragonDetector()

    async def scannable_pairs(self) -> List[str]:
        """Список доступных торговых пар (до 100 шт.). Используется в /analyze."""
        return await self._resolve_pairs()

    async def scan_once_and_alert(self, application) -> None:
        """Один проход сканера: собираем пары, проверяем все ТФ, шлём алерты (только закрытые свечи)."""
        pairs = await self._resolve_pairs()
        if not pairs:
            log.warning("Нет доступных торговых пар для сканирования")
            return

        jobs: List[tuple[str, str]] = [(pair, tf) for pair in pairs for tf in self.timeframes]
        window = 20

        for i in range(0, len(jobs), window):
            chunk = jobs[i : i + window]
            await asyncio.gather(*(self._process_pair_tf(application, pair, tf) for pair, tf in chunk))
            if self.batch_sleep:
                await asyncio.sleep(self.batch_sleep)

        await self.scan_rsi_multi_tf_and_alert(application, pairs=pairs)
        await self.scan_dragon_and_alert(application, pairs=pairs)

    async def _process_pair_tf(self, application, symbol: str, tf: str) -> None:
        """Обработка одной пары на одном таймфрейме: тянем klines, проверяем серию и шлём алерт (per-chat дедуп)."""
        try:
            # берём побольше, чтобы точно хватило на фильтры/хвост
            limit = max(200, self.required_streak + 50)
            klines = await self.bn.get_klines(symbol, tf, limit=limit)
        except Exception:
            log.exception("binance.get_klines(%s, %s) failed", symbol, tf)
            return

        if not klines:
            return

        # Берём только ЗАКРЫТЫЕ свечи, текущую (незакрытую) отбрасываем
        closed = self._closed_only(klines)
        if not closed:
            return

        # Превращаем в DataFrame нашей формы
        try:
            df = self.klines_to_df(closed)
        except Exception:
            log.exception("to_df failed for %s %s", symbol, tf)
            return

        if df.empty or len(df) < self.required_streak:
            return

        color = self._streak_color(df, self.required_streak)
        if color is None:
            return

        # Дедуп-ключ для конкретной закрытой свечи
        last_row = df.iloc[-1]
        try:
            close_ts = int(last_row["close_time"].timestamp())
        except Exception:
            # на случай, если это pandas.Timestamp/str
            close_ts = int(pd.to_datetime(last_row["close_time"]).timestamp())

        dedup_key = f"{symbol}:{tf}:streak{self.required_streak}:{'green' if color=='green' else 'red'}:close{close_ts}"
        log.info(
            "ALERT detected: %s %s streak=%d color=%s close_ts=%s",
            symbol,
            tf,
            self.required_streak,
            color,
            close_ts,
        )
        log.info("Dedup key -> %s", dedup_key)

        # Формируем текст
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

        # Рассылка всем подписчикам с per-chat дедупом
        try:
            chats: Iterable[int] = await self.storage.get_chats()
        except Exception:
            log.exception("get_chats() failed")
            return

        chats = list(set(chats))
        log.info("Broadcasting alert to %d chats", len(chats))

        sent_any = False
        for chat_id in chats:
            try:
                # per-chat проверка дубля
                try:
                    if await self.storage.is_alert_sent(chat_id, dedup_key):
                        log.info("Skip alert for chat=%s (already sent): %s", chat_id, dedup_key)
                        continue
                except Exception:
                    log.exception("storage.is_alert_sent(chat) failed")
                    # не роняем рассылку, пробуем отправить

                await application.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    disable_notification=True,
                    disable_web_page_preview=True,
                )
                log.debug("Sent to chat=%s", chat_id)
                sent_any = True

                # помечаем per-chat только после успешной доставки
                try:
                    await self.storage.mark_alert_sent(chat_id, dedup_key)
                except Exception:
                    log.exception("storage.mark_alert_sent(chat) failed")

            except Forbidden:
                # пользователь заблокировал бота или никогда не нажимал Start
                log.warning("Forbidden chat=%s (blocked or never /start). Removing.", chat_id)
                try:
                    await self.storage.remove_chat(chat_id)
                except Exception:
                    log.exception("remove_chat failed for %s", chat_id)
            except BadRequest as e:
                # неверный chat_id / бот не в группе / нет прав в канале
                log.warning("BadRequest chat=%s: %s. Removing.", chat_id, e)
                try:
                    await self.storage.remove_chat(chat_id)
                except Exception:
                    log.exception("remove_chat failed for %s", chat_id)
            except Exception as e:
                # логируем и продолжаем, чтобы не сломать рассылку остальным
                log.exception("Send failed chat=%s: %s (skip, continue)", chat_id, e)

        # Глобальных меток больше нет — отмечаем только per-chat.
        if not sent_any:
            log.warning("Alert NOT marked sent (no successful deliveries): %s", dedup_key)

    async def scan_rsi_multi_tf_and_alert(self, application, pairs: Sequence[str] | None = None) -> None:
        pairs = list(pairs) if pairs is not None else await self._resolve_pairs()
        if not pairs:
            log.warning("RSI scan: no pairs to process")
            return

        try:
            chats: Iterable[int] = await self.storage.get_chats()
        except Exception:
            log.exception("get_chats() failed (RSI)")
            return

        chats = list(set(chats))
        if not chats:
            log.info("RSI scan: no subscribed chats, skip")
            return

        for symbol in pairs:
            results = await asyncio.gather(*(self._last_rsi(symbol, tf) for tf in self.RSI_TIMEFRAMES))
            rsi_values: dict[str, float] = {}
            close_ts_by_tf: dict[str, int] = {}
            for tf, (val, close_ts) in zip(self.RSI_TIMEFRAMES, results):
                if val is not None:
                    rsi_values[tf] = val
                if close_ts is not None:
                    close_ts_by_tf[tf] = close_ts

            if len(rsi_values) < 2:
                continue

            await self._maybe_send_rsi_alerts(application, symbol, rsi_values, close_ts_by_tf, chats)

    async def _maybe_send_rsi_alerts(
        self,
        application,
        symbol: str,
        rsi_values: dict[str, float],
        close_ts_by_tf: dict[str, int],
        chats: List[int],
    ) -> None:
        checks = (
            ("overbought", lambda v: v >= 75, ">= 75"),
            ("oversold", lambda v: v <= 25, "<= 25"),
        )

        for direction, predicate, condition_text in checks:
            tfs_hit = [tf for tf, val in rsi_values.items() if predicate(val)]
            if len(tfs_hit) < 2:
                continue

            ts_candidates = [close_ts_by_tf.get(tf) for tf in tfs_hit if close_ts_by_tf.get(tf) is not None]
            if not ts_candidates:
                continue
            close_ts = max(ts_candidates)

            sorted_tfs_key = ",".join(sorted(tfs_hit))
            dedup_key = f"{symbol}:rsi-multi:{direction}:{sorted_tfs_key}:close{close_ts}"
            log.info(
                "RSI ALERT detected: %s direction=%s tfs=%s close_ts=%s values=%s",
                symbol,
                direction,
                tfs_hit,
                close_ts,
                {tf: round(val, 2) for tf, val in rsi_values.items()},
            )
            log.info("Dedup key -> %s", dedup_key)

            strong = len(tfs_hit) == len(self.RSI_TIMEFRAMES)
            prefix = "⭐️ " if strong else ""
            count_str = f"{len(tfs_hit)}/{len(self.RSI_TIMEFRAMES)}"
            zone_label = f"{'сильный ' if strong else ''}{direction}"
            rsi_line = ", ".join(
                f"{tf} = {rsi_values[tf]:.1f}" if tf in rsi_values else f"{tf} = n/a"
                for tf in self.RSI_TIMEFRAMES
            )
            text = (
                f"{prefix}⚠️ <b>{symbol}</b> • многотаймфреймовый RSI\n"
                f"RSI(14): {rsi_line}\n"
                f"Зона: {zone_label} ({condition_text}) на {count_str} таймфреймах"
            )

            await self._broadcast_rsi_alert(application, chats, dedup_key, text)

    async def _broadcast_rsi_alert(self, application, chats: List[int], dedup_key: str, text: str) -> None:
        sent_any = False
        for chat_id in chats:
            try:
                try:
                    if await self.storage.is_alert_sent(chat_id, dedup_key):
                        log.info("Skip RSI alert for chat=%s (already sent): %s", chat_id, dedup_key)
                        continue
                except Exception:
                    log.exception("storage.is_alert_sent(chat) failed (RSI)")

                await application.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    disable_notification=True,
                    disable_web_page_preview=True,
                )
                log.debug("Sent RSI alert to chat=%s", chat_id)
                sent_any = True

                try:
                    await self.storage.mark_alert_sent(chat_id, dedup_key)
                except Exception:
                    log.exception("storage.mark_alert_sent(chat) failed (RSI)")

            except Forbidden:
                log.warning("Forbidden chat=%s (blocked or never /start). Removing.", chat_id)
                try:
                    await self.storage.remove_chat(chat_id)
                except Exception:
                    log.exception("remove_chat failed for %s", chat_id)
            except BadRequest as e:
                log.warning("BadRequest chat=%s: %s. Removing.", chat_id, e)
                try:
                    await self.storage.remove_chat(chat_id)
                except Exception:
                    log.exception("remove_chat failed for %s", chat_id)
            except Exception as e:
                log.exception("Send failed chat=%s: %s (skip, continue)", chat_id, e)

        if not sent_any:
            log.warning("RSI alert NOT marked sent (no successful deliveries): %s", dedup_key)

    async def scan_dragon_and_alert(self, application, pairs: Sequence[str] | None = None) -> None:
        pairs = list(pairs) if pairs is not None else await self._resolve_pairs()
        if not pairs:
            log.warning("Dragon scan: no pairs to process")
            return

        try:
            chats: Iterable[int] = await self.storage.get_chats()
        except Exception:
            log.exception("get_chats() failed (Dragon)")
            return

        chats = list(set(chats))
        if not chats:
            log.info("Dragon scan: no subscribed chats, skip")
            return

        for symbol in pairs:
            for tf in self.DRAGON_TIMEFRAMES:
                limit = max(self.TF_LIMITS.get(tf, self.klines_limit), 300)
                try:
                    klines = await self.bn.get_klines(symbol, tf, limit=limit)
                except Exception:
                    log.exception("binance.get_klines(%s, %s) failed (Dragon)", symbol, tf)
                    continue

                closed = self._closed_only(klines)
                if len(closed) < 30:
                    continue

                try:
                    df = self.klines_to_df(closed)
                except Exception:
                    log.exception("to_df failed for %s %s (Dragon)", symbol, tf)
                    continue

                if df.empty or len(df) < 30:
                    continue

                try:
                    analysis = analyze(df)
                    rsi_val = float(analysis.get("rsi14", 50))
                    rsi_state = analysis.get("rsi_state", "neutral")
                except Exception:
                    log.exception("analyze() failed for %s %s (Dragon)", symbol, tf)
                    continue

                last_close_time = df["close_time"].iloc[-1]
                patterns = self.dragon_detector.detect_all(symbol, tf, df)
                if not patterns:
                    continue

                for pattern in patterns:
                    if not self._is_dragon_confirmed_on_last(pattern, last_close_time):
                        continue
                    if not self._dragon_rsi_passed(pattern.direction, rsi_val, rsi_state):
                        continue
                    await self._broadcast_dragon_alert(application, pattern, chats, rsi_val, rsi_state)

    async def _broadcast_dragon_alert(
        self,
        application,
        pattern: DragonPattern,
        chats: List[int],
        rsi_val: float,
        rsi_state: str,
    ) -> None:
        direction_short = "bull" if pattern.direction == "bullish" else "bear"
        try:
            tail_ts = int(pattern.confirm_candle_time.timestamp())
        except Exception:
            tail_ts = int(pd.to_datetime(pattern.confirm_candle_time).timestamp())

        dedup_key = f"{pattern.symbol}:dragon:{direction_short}:{pattern.timeframe}:tail{tail_ts}"
        log.info(
            "DRAGON pattern detected: %s %s direction=%s confirm_ts=%s",
            pattern.symbol,
            pattern.timeframe,
            pattern.direction,
            pattern.confirm_candle_time,
        )
        log.info("Dragon Dedup key -> %s", dedup_key)

        dir_label = "Bullish" if pattern.direction == "bullish" else "Bearish"
        tail_comment = "Tail: пробой вверх после правой лапы" if pattern.direction == "bullish" else "Tail: пробой вниз после правой лапы"

        def fmt_point(pt: DragonPoint) -> str:
            try:
                t = pt.time.strftime("%Y-%m-%d %H:%M UTC")
            except Exception:
                t = str(pt.time)
            return f"{pt.price:.4f} ({t})"

        text = (
            f"🐉 <b>{pattern.symbol}</b> • {dir_label} Dragon pattern на {pattern.timeframe}\n"
            f"Head: {fmt_point(pattern.head)}\n"
            f"Left paw: {fmt_point(pattern.left_paw)}\n"
            f"Hump: {fmt_point(pattern.hump)}\n"
            f"Right paw: {fmt_point(pattern.right_paw)}\n"
            f"{tail_comment}\n"
            f"RSI(14)={rsi_val:.2f} ({rsi_state}) — условия подтверждения выполнены\n"
            f"Комментарий: {'W' if pattern.direction == 'bullish' else 'M'}-образный разворот, сигнал сформирован"
        )

        sent_any = False
        for chat_id in chats:
            try:
                try:
                    if await self.storage.is_alert_sent(chat_id, dedup_key):
                        log.info("Skip Dragon alert for chat=%s (already sent): %s", chat_id, dedup_key)
                        continue
                except Exception:
                    log.exception("storage.is_alert_sent(chat) failed (Dragon)")

                await application.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    disable_notification=True,
                    disable_web_page_preview=True,
                )
                log.debug("Sent Dragon alert to chat=%s", chat_id)
                sent_any = True

                try:
                    await self.storage.mark_alert_sent(chat_id, dedup_key)
                except Exception:
                    log.exception("storage.mark_alert_sent(chat) failed (Dragon)")

            except Forbidden:
                log.warning("Forbidden chat=%s (blocked or never /start). Removing.", chat_id)
                try:
                    await self.storage.remove_chat(chat_id)
                except Exception:
                    log.exception("remove_chat failed for %s", chat_id)
            except BadRequest as e:
                log.warning("BadRequest chat=%s: %s. Removing.", chat_id, e)
                try:
                    await self.storage.remove_chat(chat_id)
                except Exception:
                    log.exception("remove_chat failed for %s", chat_id)
            except Exception as e:
                log.exception("Send failed chat=%s: %s (skip, continue)", chat_id, e)

        if not sent_any:
            log.warning("Dragon alert NOT marked sent (no successful deliveries): %s", dedup_key)

    async def _last_rsi(self, symbol: str, tf: str, period: int = 14) -> tuple[float | None, int | None]:
        limit = max(self.TF_LIMITS.get(tf, self.klines_limit), period + 5)
        try:
            klines = await self.bn.get_klines(symbol, tf, limit=limit)
        except Exception:
            log.exception("binance.get_klines(%s, %s) failed (RSI)", symbol, tf)
            return None, None

        closed = self._closed_only(klines)
        if len(closed) < period + 1:
            return None, None

        try:
            df = self.klines_to_df(closed)
        except Exception:
            log.exception("to_df failed for %s %s (RSI)", symbol, tf)
            return None, None

        if df.empty or len(df) < period + 1:
            return None, None

        rsi_series = rsi_ewma(df["close"], period=period).dropna()
        if rsi_series.empty:
            return None, None

        rsi_value = float(rsi_series.iloc[-1])
        try:
            close_ts = int(df.iloc[-1]["close_time"].timestamp())
        except Exception:
            close_ts = int(pd.to_datetime(df.iloc[-1]["close_time"]).timestamp())

        return rsi_value, close_ts

    # ---------- ВСПОМОГАТЕЛЬНОЕ ----------

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
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trades",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore",
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
        """Возвращает 'green'/'red' если ПОСЛЕДНИЕ n закрытых свечей одного цвета, иначе None."""
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

    def _is_dragon_confirmed_on_last(self, pattern: DragonPattern, last_close_time: pd.Timestamp) -> bool:
        try:
            return pd.to_datetime(pattern.confirm_candle_time) == pd.to_datetime(last_close_time)
        except Exception:
            return False

    def _dragon_rsi_passed(self, direction: str, rsi_val: float, rsi_state: str) -> bool:
        if direction == "bullish":
            return rsi_val <= 30 or rsi_state == "oversold"
        if direction == "bearish":
            return rsi_val >= 70 or rsi_state == "overbought"
        return False

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
                    log.debug("%s() failed: %s", meth, e)

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
                    log.debug("%s() failed: %s", meth, e)

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
                    log.debug("coingecko.%s() failed: %s", meth, e)

        return [
            "BTCUSDT",
            "ETHUSDT",
            "BNBUSDT",
            "SOLUSDT",
            "XRPUSDT",
            "ADAUSDT",
            "DOGEUSDT",
            "TONUSDT",
            "TRXUSDT",
            "DOTUSDT",
            "MATICUSDT",
            "AVAXUSDT",
            "LINKUSDT",
            "APTUSDT",
            "NEARUSDT",
            "ATOMUSDT",
            "LTCUSDT",
            "UNIUSDT",
            "FILUSDT",
            "AAVEUSDT",
        ]
