from typing import Dict
import pandas as pd

def body(o, c): return abs(c - o)
def upper_shadow(h, o, c): return h - max(o, c)
def lower_shadow(l, o, c): return min(o, c) - l

def is_doji(o, c, h, l) -> bool:
    rng = h - l
    b = body(o, c)
    return rng > 0 and b / rng < 0.1

def is_hammer(o, c, h, l) -> bool:
    b = body(o, c)
    ls = lower_shadow(l, o, c)
    us = upper_shadow(h, o, c)
    return ls >= 2 * b and us <= b

def is_shooting_star(o, c, h, l) -> bool:
    b = body(o, c)
    ls = lower_shadow(l, o, c)
    us = upper_shadow(h, o, c)
    return us >= 2 * b and ls <= b

def is_bull_engulf(prev_o, prev_c, o, c) -> bool:
    return (prev_c < prev_o) and (c > o) and (o <= prev_c) and (c >= prev_o) and (abs(c-o) > abs(prev_c - prev_o))

def is_bear_engulf(prev_o, prev_c, o, c) -> bool:
    return (prev_c > prev_o) and (c < o) and (o >= prev_c) and (c <= prev_o) and (abs(o-c) > abs(prev_o - prev_c))

def detect_patterns_last(df: pd.DataFrame) -> Dict[str, bool]:
    row = df.iloc[-1]
    o, c, h, l = row["open"], row["close"], row["high"], row["low"]
    out = {
        "Doji": is_doji(o, c, h, l),
        "Hammer": is_hammer(o, c, h, l),
        "Shooting Star": is_shooting_star(o, c, h, l),
        "Bullish Engulfing": False,
        "Bearish Engulfing": False,
    }
    if len(df) >= 2:
        prev = df.iloc[-2]
        out["Bullish Engulfing"] = is_bull_engulf(prev["open"], prev["close"], o, c)
        out["Bearish Engulfing"] = is_bear_engulf(prev["open"], prev["close"], o, c)
    return out
