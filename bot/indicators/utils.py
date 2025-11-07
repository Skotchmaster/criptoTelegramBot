import math
import pandas as pd
from typing import Optional

def safe_last(series: pd.Series) -> Optional[float]:
    """Вернёт последний не-NaN элемент как float либо None, если его нет."""
    if series is None or not isinstance(series, pd.Series) or series.empty:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        non_na = series.dropna()
        if non_na.empty:
            return None
        val = non_na.iloc[-1]
    try:
        return float(val)
    except Exception:
        return None

def fmt_num(v, digits=1) -> str:
    if v is None or (isinstance(v, float) and (pd.isna(v) or math.isinf(v))):
        return "н/д"
    try:
        return f"{float(v):.{digits}f}"
    except Exception:
        return "н/д"
