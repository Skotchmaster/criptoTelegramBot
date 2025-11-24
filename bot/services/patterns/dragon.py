from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal

import pandas as pd


@dataclass
class DragonPoint:
    time: pd.Timestamp
    price: float


@dataclass
class DragonPattern:
    symbol: str
    timeframe: str
    direction: Literal["bullish", "bearish"]
    head: DragonPoint
    left_paw: DragonPoint
    hump: DragonPoint
    right_paw: DragonPoint
    confirm_candle_time: pd.Timestamp


class DragonDetector:
    """
    Простое эвристическое распознавание Dragon (bullish/bearish) по свингам.
    Паттерн ищется по локальным экстремумам low/high с допусками на лапы и подтверждением хвоста.
    """

    def __init__(
        self,
        feet_tolerance: float = 0.1,
        min_retracement: float = 0.38,
        max_retracement: float = 0.62,
        swing_window: int = 3,
        trend_lookback: int = 20,
        min_trend_move: float = 0.03,
    ) -> None:
        self.feet_tolerance = feet_tolerance
        self.min_retracement = min_retracement
        self.max_retracement = max_retracement
        self.swing_window = swing_window
        self.trend_lookback = trend_lookback
        self.min_trend_move = min_trend_move

    def find_swings(self, df: pd.DataFrame) -> List[dict]:
        """
        По df с колонками high/low/close возвращает список свинг-точек:
        {"index": int, "time": Timestamp, "price": float, "type": "high" | "low"}
        """
        swings: List[dict] = []
        if df.empty or len(df) < self.swing_window * 2 + 1:
            return swings

        lows = df["low"].reset_index(drop=True)
        highs = df["high"].reset_index(drop=True)
        times = df["close_time"].reset_index(drop=True)

        for i in range(self.swing_window, len(df) - self.swing_window):
            lo = lows.iloc[i]
            hi = highs.iloc[i]
            window_lows = lows.iloc[i - self.swing_window : i + self.swing_window + 1]
            window_highs = highs.iloc[i - self.swing_window : i + self.swing_window + 1]

            if lo <= window_lows.min() and lo < highs.iloc[i]:
                swings.append({"index": i, "time": times.iloc[i], "price": float(lo), "type": "low"})
            elif hi >= window_highs.max() and hi > lows.iloc[i]:
                swings.append({"index": i, "time": times.iloc[i], "price": float(hi), "type": "high"})

        return swings

    def detect_all(self, symbol: str, timeframe: str, df: pd.DataFrame) -> List[DragonPattern]:
        patterns: List[DragonPattern] = []
        patterns.extend(self.detect_bullish(symbol, timeframe, df))
        patterns.extend(self.detect_bearish(symbol, timeframe, df))
        return patterns

    def detect_bullish(self, symbol: str, timeframe: str, df: pd.DataFrame) -> List[DragonPattern]:
        patterns: List[DragonPattern] = []
        swings = self.find_swings(df)
        if len(swings) < 3:
            return patterns

        closes = df["close"].reset_index(drop=True)
        highs = df["high"].reset_index(drop=True)
        head_candidates = [s for s in swings if s["type"] == "low"]

        for head in head_candidates:
            head_idx = head["index"]
            head_price = head["price"]

            if not self._is_downtrend_before(closes, head_idx, head_price):
                continue

            # найти hump (high) и правую лапу (low) после головы
            for hump in swings:
                if hump["type"] != "high" or hump["index"] <= head_idx:
                    continue
                hump_idx = hump["index"]
                hump_price = hump["price"]

                # рост от головы к горбу должен быть заметным
                if not self._is_valid_retracement(df, head_idx, head_price, hump_price):
                    continue

                # правая лапа — низ после горба, близкий к голове
                right_paw = None
                for rp in swings:
                    if rp["type"] != "low" or rp["index"] <= hump_idx:
                        continue
                    if self._feet_close(head_price, rp["price"]):
                        right_paw = rp
                        break

                if not right_paw:
                    continue

                confirm_ts = self._confirm_tail_up(df, right_paw["index"], hump_price)
                if confirm_ts is None:
                    continue

                left_paw = hump  # в упрощённой модели горб совпадает с левой лапой
                pattern = DragonPattern(
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="bullish",
                    head=DragonPoint(time=head["time"], price=head_price),
                    left_paw=DragonPoint(time=left_paw["time"], price=left_paw["price"]),
                    hump=DragonPoint(time=hump["time"], price=hump_price),
                    right_paw=DragonPoint(time=right_paw["time"], price=right_paw["price"]),
                    confirm_candle_time=confirm_ts,
                )
                patterns.append(pattern)

        return patterns

    def detect_bearish(self, symbol: str, timeframe: str, df: pd.DataFrame) -> List[DragonPattern]:
        patterns: List[DragonPattern] = []
        swings = self.find_swings(df)
        if len(swings) < 3:
            return patterns

        closes = df["close"].reset_index(drop=True)
        lows = df["low"].reset_index(drop=True)
        head_candidates = [s for s in swings if s["type"] == "high"]

        for head in head_candidates:
            head_idx = head["index"]
            head_price = head["price"]

            if not self._is_uptrend_before(closes, head_idx, head_price):
                continue

            for hump in swings:
                if hump["type"] != "low" or hump["index"] <= head_idx:
                    continue
                hump_idx = hump["index"]
                hump_price = hump["price"]

                if not self._is_valid_retracement(df, head_idx, head_price, hump_price, bearish=True):
                    continue

                right_paw = None
                for rp in swings:
                    if rp["type"] != "high" or rp["index"] <= hump_idx:
                        continue
                    if self._feet_close(head_price, rp["price"]):
                        right_paw = rp
                        break

                if not right_paw:
                    continue

                confirm_ts = self._confirm_tail_down(df, right_paw["index"], hump_price)
                if confirm_ts is None:
                    continue

                left_paw = hump
                pattern = DragonPattern(
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="bearish",
                    head=DragonPoint(time=head["time"], price=head_price),
                    left_paw=DragonPoint(time=left_paw["time"], price=left_paw["price"]),
                    hump=DragonPoint(time=hump["time"], price=hump_price),
                    right_paw=DragonPoint(time=right_paw["time"], price=right_paw["price"]),
                    confirm_candle_time=confirm_ts,
                )
                patterns.append(pattern)

        return patterns

    def _feet_close(self, price_a: float, price_b: float) -> bool:
        return abs(price_a - price_b) / price_a <= self.feet_tolerance

    def _is_downtrend_before(self, closes: pd.Series, idx: int, head_price: float) -> bool:
        if idx <= 0:
            return False
        start = max(0, idx - self.trend_lookback)
        prev_mean = closes.iloc[start:idx].mean()
        return prev_mean > 0 and (prev_mean - head_price) / prev_mean >= self.min_trend_move

    def _is_uptrend_before(self, closes: pd.Series, idx: int, head_price: float) -> bool:
        if idx <= 0:
            return False
        start = max(0, idx - self.trend_lookback)
        prev_mean = closes.iloc[start:idx].mean()
        return prev_mean > 0 and (head_price - prev_mean) / prev_mean >= self.min_trend_move

    def _is_valid_retracement(
        self,
        df: pd.DataFrame,
        head_idx: int,
        head_price: float,
        hump_price: float,
        bearish: bool = False,
    ) -> bool:
        if head_idx <= 0:
            return False

        # ищем экстремум до головы для оценки предыдущего движения
        prior_slice = df.iloc[max(0, head_idx - self.trend_lookback) : head_idx]
        if prior_slice.empty:
            return False

        if bearish:
            prior_low = float(prior_slice["low"].min())
            move = head_price - prior_low
            if move <= 0:
                return False
            retracement = (head_price - hump_price) / move
        else:
            prior_high = float(prior_slice["high"].max())
            move = prior_high - head_price
            if move <= 0:
                return False
            retracement = (hump_price - head_price) / move

        return self.min_retracement <= retracement <= self.max_retracement

    def _confirm_tail_up(self, df: pd.DataFrame, right_paw_idx: int, hump_price: float) -> pd.Timestamp | None:
        after = df.iloc[right_paw_idx + 1 :]
        for _, row in after.iterrows():
            if row["close"] > hump_price:
                return row["close_time"]
        return None

    def _confirm_tail_down(self, df: pd.DataFrame, right_paw_idx: int, hump_price: float) -> pd.Timestamp | None:
        after = df.iloc[right_paw_idx + 1 :]
        for _, row in after.iterrows():
            if row["close"] < hump_price:
                return row["close_time"]
        return None

