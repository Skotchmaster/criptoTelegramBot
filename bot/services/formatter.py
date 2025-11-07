from typing import Dict, List

def fmt_patterns(patterns: List[str]) -> str:
    if not patterns:
        return "—"
    return ", ".join(patterns)

def format_analysis(ticker: str, name: str, interval: str, a: Dict) -> str:
    lines = [
        f"📊 <b>{ticker}/USDT</b> — {name}",
        f"⏱ Таймфрейм: <b>{interval}</b>",
        f"🕒 Последняя свеча закрылась: <code>{a.get('last_close_time','')}</code>",
        "",
        f"Цена закрытия: <b>{a['close']:.6g}</b> USDT",
        f"RSI(14): <b>{a['rsi14']}</b> ({a['rsi_state']})",
        f"SMA20 / SMA50: <b>{a['sma20']:.6g}</b> / <b>{a['sma50']:.6g}</b> ({a['trend']})",
        f"Кроссы SMA: <b>{a['sma_cross'] or '—'}</b>",
        f"Свечные паттерны (последняя свеча): <b>{fmt_patterns(a['patterns'])}</b>",
        "",
        "ℹ️ Это не финансовый совет. Проверьте ликвидность и риск."
    ]
    return "\n".join(lines)
