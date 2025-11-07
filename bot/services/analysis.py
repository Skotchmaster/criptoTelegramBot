import numpy as np
import pandas as pd
from typing import Dict

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0.0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    r = 100 - (100 / (1 + rs))
    return r.fillna(50)

def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=1).mean()

def is_doji(o, h, l, c, thresh=0.0015) -> bool:
    body = abs(c - o)
    rng = h - l
    if rng == 0:
        return False
    return (body / rng) < 0.1 and (body / ((h + l)/2)) < thresh

def is_hammer(o, h, l, c) -> bool:
    body = abs(c - o)
    lower_shadow = min(o, c) - l
    upper_shadow = h - max(o, c)
    return (lower_shadow > body*2) and (upper_shadow < body) and (c > o)

def is_shooting_star(o, h, l, c) -> bool:
    body = abs(c - o)
    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l
    return (upper_shadow > body*2) and (lower_shadow < body) and (c < o)

def is_bullish_engulf(prev_o, prev_c, o, c) -> bool:
    return (prev_c < prev_o) and (c > o) and (c >= prev_o) and (o <= prev_c)

def is_bearish_engulf(prev_o, prev_c, o, c) -> bool:
    return (prev_c > prev_o) and (c < o) and (c <= prev_o) and (o >= prev_c)

def analyze(df: pd.DataFrame) -> Dict:
    """
    df: OHLCV с колонками open, high, low, close и индексом по времени (не обязательно)
    Возвращает словарь с сигналами по последней свече.
    """
    close = df["close"]
    df = df.copy()
    df["RSI14"] = rsi(close, 14)
    df["SMA20"] = sma(close, 20)
    df["SMA50"] = sma(close, 50)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    o, h, l, c = last["open"], last["high"], last["low"], last["close"]
    po, pc = prev["open"], prev["close"]

    patterns = []
    if is_doji(o, h, l, c): patterns.append("Doji")
    if is_hammer(o, h, l, c): patterns.append("Hammer (bullish)")
    if is_shooting_star(o, h, l, c): patterns.append("Shooting Star (bearish)")
    if is_bullish_engulf(po, pc, o, c): patterns.append("Bullish Engulfing")
    if is_bearish_engulf(po, pc, o, c): patterns.append("Bearish Engulfing")

    sma_cross = None
    if df["SMA20"].iloc[-2] < df["SMA50"].iloc[-2] and df["SMA20"].iloc[-1] > df["SMA50"].iloc[-1]:
        sma_cross = "Golden cross (SMA20 ↑ SMA50)"
    elif df["SMA20"].iloc[-2] > df["SMA50"].iloc[-2] and df["SMA20"].iloc[-1] < df["SMA50"].iloc[-1]:
        sma_cross = "Death cross (SMA20 ↓ SMA50)"

    rsi_val = float(last["RSI14"])
    rsi_state = "neutral"
    if rsi_val >= 70: rsi_state = "overbought"
    elif rsi_val <= 30: rsi_state = "oversold"

    trend = "↑ uptrend" if last["SMA20"] > last["SMA50"] else "↓ downtrend"

    return {
        "close": float(c),
        "rsi14": round(rsi_val, 2),
        "rsi_state": rsi_state,
        "sma20": float(last["SMA20"]),
        "sma50": float(last["SMA50"]),
        "sma_cross": sma_cross,
        "trend": trend,
        "patterns": patterns,
        "last_open_time": str(df["open_time"].iloc[-1]) if "open_time" in df else "",
        "last_close_time": str(df["close_time"].iloc[-1]) if "close_time" in df else "",
    }
