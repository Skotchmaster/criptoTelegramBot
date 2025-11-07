import re

# Map UI tf -> Binance interval
TIMEFRAMES = {
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}

def normalize_symbol(symbol: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]", "", symbol or "")
    return s.upper()
