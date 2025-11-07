import pandas as pd

def last_n_same_color(df: pd.DataFrame, n: int = 8) -> str | None:
    """
    Если последние n свечей одного цвета — вернёт 'Bullish' или 'Bearish', иначе None.
    Требуются колонки: open, close.
    """
    if df is None or df.empty or len(df) < n:
        return None
    chunk = df.tail(n)[["open", "close"]].copy()
    chunk["green"] = chunk["close"] > chunk["open"]
    chunk["red"] = chunk["close"] < chunk["open"]
    if chunk["green"].all():
        return "Bullish"
    if chunk["red"].all():
        return "Bearish"
    return None

def basic_pattern(df: pd.DataFrame) -> str | None:
    return last_n_same_color(df, 8)
