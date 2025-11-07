from __future__ import annotations

import math
import html
from typing import List

import pandas as pd
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes


PAGE_SIZE = 18  # сколько пар показывать на странице
CB_ANALYZE = "analyze:"    # callback_data для выбора символа
CB_PAGE = "page:"          # callback_data для пагинации


# ---------- Входные команды ----------

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /analyze <SYMBOL> — если SYMBOL не задан, показываем пагинацию доступных пар.
    """
    if context.args:
        symbol = alias_to_symbol(context.args[0])
        text = await build_analysis_text(context, symbol)
        await update.message.reply_html(text)
        return

    # Нет аргументов — рисуем каталог пар
    await show_page(update, context, page=1)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик кнопок из этого модуля. Ожидает callback_data:
      - "analyze:<SYMBOL>"
      - "page:<n>"
    """
    query = update.callback_query
    if not query or not query.data:
        return

    data: str = query.data
    if data.startswith(CB_ANALYZE):
        symbol = data[len(CB_ANALYZE):]
        text = await build_analysis_text(context, symbol)
        await query.edit_message_text(text=text, parse_mode="HTML")
        return

    if data.startswith(CB_PAGE):
        page_s = data[len(CB_PAGE):]
        try:
            page = int(page_s)
        except ValueError:
            page = 1
        await show_page(update, context, page=page, edit=True)
        return


# ---------- UI: список пар ----------

async def show_page(update: Update, context: ContextTypes.DEFAULT_TYPE, *, page: int, edit: bool = False):
    scanner = context.application.bot_data["scanner"]
    pairs: List[str] = await scanner.scannable_pairs()
    pairs = sorted(set(pairs))
    total = len(pairs)
    if total == 0:
        msg = "Пар не найдено."
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.effective_message.reply_text(msg)
        return

    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, pages))
    start = (page - 1) * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    chunk = pairs[start:end]

    # Кнопки с символами (по 3 в ряд)
    rows: List[List[InlineKeyboardButton]] = []
    for i in range(0, len(chunk), 3):
        row_syms = chunk[i:i+3]
        rows.append([InlineKeyboardButton(s, callback_data=f"{CB_ANALYZE}{s}") for s in row_syms])

    # Пагинация
    nav: List[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton("« Назад", callback_data=f"{CB_PAGE}{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="noop"))
    if page < pages:
        nav.append(InlineKeyboardButton("Вперёд »", callback_data=f"{CB_PAGE}{page+1}"))
    if nav:
        rows.append(nav)

    kb = InlineKeyboardMarkup(rows)
    header = f"Выбери пару для анализа ({total} всего):\nСтр. {page}/{pages}"

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(header, reply_markup=kb)
    else:
        await update.effective_message.reply_text(header, reply_markup=kb)


# ---------- Аналитика ----------

def alias_to_symbol(x: str) -> str:
    s = (x or "").strip().upper()
    if s.endswith("USDT"):
        return s
    # Если короткий алиас — мапим к USDT
    if 3 <= len(s) <= 6 and s.isalpha():
        return s + "USDT"
    return s


async def build_analysis_text(context: ContextTypes.DEFAULT_TYPE, symbol: str) -> str:
    """Собирает сводку по 1h/4h/1d: RSI(14), SMA20/50, кроссы, базовый паттерн."""
    app_data = context.application.bot_data
    bn = app_data["bn"]
    scanner = app_data["scanner"]  # используем его конвертер klines_to_df

    tf_list = [("1h", "1ч"), ("4h", "4ч"), ("1d", "1д")]

    safe_symbol = html.escape(symbol)
    parts = [f"<b>{safe_symbol}</b>"]
    for tf, tf_ru in tf_list:
        try:
            raw = await bn.get_klines(symbol, tf, limit=200)
            df = scanner.klines_to_df(raw)
            if df.empty or len(df) < 50:
                parts.append(f"\n[{tf_ru}] данных мало")
                continue

            rsi = rsi_wilder(df["close"], 14)
            sma20 = df["close"].rolling(20).mean()
            sma50 = df["close"].rolling(50).mean()

            rsi_v = float(rsi.iloc[-1])
            s20 = float(sma20.iloc[-1])
            s50 = float(sma50.iloc[-1])
            cross_txt = cross_state(sma20, sma50)  # уже без HTML-тегов
            pat = candle_pattern(df)

            cross_part = f"  → <b>{html.escape(cross_txt)}</b>" if cross_txt else ""

            parts.append(
                "\n"
                f"[{tf_ru}]\n"
                f"RSI(14): <b>{rsi_v:.1f}</b>\n"
                f"SMA20: <code>{s20:.6g}</code> • SMA50: <code>{s50:.6g}</code>{cross_part}\n"
                f"Pattern: <i>{html.escape(pat)}</i>"
            )
        except Exception:
            parts.append(f"\n[{tf_ru}] ошибка получения данных")

    parts.append("\n<i>Данные по Binance klines; время UTC.</i>")
    return "\n".join(parts)


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    # Wilder's smoothing (EMA с alpha=1/period)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / (roll_down.replace(0, pd.NA))
    rsi = 100 - (100 / (1 + rs))
    # Приводим к числовому типу до fillna, чтобы не было FutureWarning
    rsi = rsi.astype("float64")
    return rsi.fillna(50.0)


def cross_state(sma_fast: pd.Series, sma_slow: pd.Series) -> str:
    """Возвращает пометку о пересечении на последних барах (без HTML)."""
    if len(sma_fast) < 51 or len(sma_slow) < 51:
        return ""
    f2, f1 = sma_fast.iloc[-2], sma_fast.iloc[-1]
    s2, s1 = sma_slow.iloc[-2], sma_slow.iloc[-1]
    if pd.notna(f2) and pd.notna(s2) and pd.notna(f1) and pd.notna(s1):
        if f2 <= s2 and f1 > s1:
            return "Golden cross"
        if f2 >= s2 and f1 < s1:
            return "Death cross"
        if f1 > s1:
            return "SMA20 > SMA50 (быч.)"
        if f1 < s1:
            return "SMA20 < SMA50 (медв.)"
    return ""


def candle_pattern(df: pd.DataFrame) -> str:
    """Очень базовые паттерны по последней свече."""
    o = float(df["open"].iloc[-1])
    h = float(df["high"].iloc[-1])
    l = float(df["low"].iloc[-1])
    c = float(df["close"].iloc[-1])

    body = abs(c - o)
    range_ = max(h - l, 1e-12)
    upper = h - max(c, o)
    lower = min(c, o) - l

    # Doji: маленькое тело
    if body / range_ < 0.1:
        return "Doji"

    # Hammer / Inverted Hammer
    if lower > 2 * body and upper < body:
        return "Hammer"
    if upper > 2 * body and lower < body:
        return "Inverted Hammer"

    # Engulfing (смотрим две последние)
    if len(df) >= 2:
        o2 = float(df["open"].iloc[-2]); c2 = float(df["close"].iloc[-2])
        if (c > o) and (c2 < o2) and (c >= o2) and (o <= c2):
            return "Bullish Engulfing"
        if (c < o) and (c2 > o2) and (c <= o2) and (o >= c2):
            return "Bearish Engulfing"

    # По умолчанию — направление тела
    return "Bullish" if c > o else "Bearish"
