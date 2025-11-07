import pandas as pd

def sma(close: pd.Series, window: int) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce").astype("float64")
    # min_periods=window — чтобы «ранние» значения были NaN и не мешали
    return close.rolling(window=window, min_periods=window).mean().astype("float64")
