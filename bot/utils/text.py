import os
from zoneinfo import ZoneInfo

def _to_local_str(ts, fmt="%Y-%m-%d %H:%M %Z"):
    """Конвертирует UTC-время свечи в локаль из .env TZ и форматирует строку."""
    tz_name = os.getenv("TZ", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    try:
        if hasattr(ts, "tz_convert"):
            ts_local = ts.tz_convert(tz)
        else:
            ts_local = ts.astimezone(tz)
    except Exception:
        ts_local = ts
    return ts_local.strftime(fmt)

def format_alert(pair: str, tf: str, direction: str, close_time) -> str:
    arrow = "🟢 8 зелёных" if direction == "green" else "🔴 8 красных"
    ts = _to_local_str(close_time)
    return f"<b>{pair}</b> • {tf}\n{arrow} свечей подряд\nЗакрытие последней: <code>{ts}</code>"

def fmt_bool(b: bool) -> str:
    return "✅" if b else "—"

def format_summary(pair: str, tf: str, last_row, rsi14: float, sma20: float, sma50: float, trend: str, cross: str, patterns):
    ts = _to_local_str(last_row['close_time'])
    trend_txt = "📈 20>50 (bull)" if trend == "bull" else "📉 20<50 (bear)"
    cross_map = {"golden": "✨ Golden cross", "death": "☠️ Death cross", "none": "—"}
    lines = [
        f"<b>{pair}</b> • {tf}",
        f"Close: <code>{last_row['close']:.6f}</code>  |  Time: <code>{ts}</code>",
        f"RSI(14): <b>{rsi14:.2f}</b>  {'(oversold)' if rsi14<=30 else '(overbought)' if rsi14>=70 else ''}",
        f"SMA20: <code>{sma20:.6f}</code>  •  SMA50: <code>{sma50:.6f}</code>",
        trend_txt + f"  |  Cross: {cross_map[cross]}",
        "— Паттерны (последняя свеча) —",
    ]
    for k, v in patterns.items():
        lines.append(f"{k}: {fmt_bool(v)}")
    return "\n".join(lines)
