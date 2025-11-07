from __future__ import annotations

import math
import html
import logging
from typing import List

import pandas as pd
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

log = logging.getLogger("bot.handlers.analyze")

PAGE_SIZE = 18
CB_ANALYZE = "analyze:"
CB_PAGE = "page:"

# Минимум закрытых баров для стабильных SMA20/50 и RSI(14)
NEED_CLOSED_MIN = 60
TF_LIST = [("1h", "1ч"), ("4h", "4ч"), ("1d", "1д")]

# ---------- Команды ----------

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /analyze <SYMBOL> — если SYMBOL не задан, показываем список пар.
    """
    if context.args:
        symbol = alias_to_symbol(context.args[0])
        text = await build_analysis_text(context, symbol)
        await update.message.reply_html(text)
        return
    await show_page(update, context, page=1)

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик кнопок: "analyze:<SYMBOL>", "page:<n>"
    """
    query = update.callback_query
    if not query or not query.data:
        return

    data: str = query.data
    if data.startswith(CB_ANALYZE):
        symbol = data[len(CB_ANALYZE):]
        text = await build_analysis_text(context, symbol)
        await safe_edit_text(query, text, parse_mode="HTML")
        return

    if data.startswith(CB_PAGE):
        page_s = data[len(CB_PAGE):]
        try:
            page = int(page_s)
        except ValueError:
            page = 1
        await show_page(update, context, page=page, edit=True)
        return

# ---------- UI списка пар ----------

async def show_page(update: Update, context: ContextTypes.DEFAULT_TYPE, *, page: int, edit: bool = False):
    scanner = context.application.bot_data["scanner"]
    pairs: List[str] = await scanner.scannable_pairs()
    pairs = sorted(set(pairs))
    total = len(pairs)
    if total == 0:
        msg = "Пар не найдено."
        if edit and update.callback_query:
            await safe_edit_text(update.callback_query, msg, reply_markup=None)
        else:
            await update.effective_message.reply_text(msg)
        return

    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, pages))
    start = (page - 1) * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    chunk = pairs[start:end]

    rows: List[List[InlineKeyboardButton]] = []
    for i in range(0, len(chunk), 3):
        row_syms = chunk[i:i+3]
        rows.append([InlineKeyboardButton(s, callback_data=f"{CB_ANALYZE}{s}") for s in row_syms])

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
        await safe_edit_text(update.callback_query, header, reply_markup=kb)
    else:
        await update.effective_message.reply_text(header, reply_markup=kb)

# ---------- Аналитика ----------

def alias_to_symbol(x: str) -> str:
    s = (x or "").strip().upper()
    if s.endswith("USDT"):
        return s
    if 3 <= len(s) <= 6 and s.isalpha():
        return s + "USDT"
    return s

def _fmt_num(v, digits=1) -> str:
    """Безопасное форматирование числа: корректно обрабатывает None/NaN/pd.NA/inf."""
    try:
        if v is None or pd.isna(v):
            return "н/д"
    except Exception:
        if v is None:
            return "н/д"
    try:
        fv = float(v)
    except Exception:
        return "н/д"
    if fv != fv or fv in (float("inf"), float("-inf")):
        return "н/д"
    return f"{fv:.{digits}f}"

def _last_valid_float(s: pd.Series) -> float | None:
    """Последнее валидное float-значение или None (устойчиво к pd.NA/NaN/типам)."""
    if s is None or not isinstance(s, pd.Series) or s.empty:
        return None
    v = pd.to_numeric(s, errors="coerce")
    v = v[v.notna()]
    if v.empty:
        return None
    try:
        out = float(v.iloc[-1])
    except Exception:
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out

async def _fetch_df(context: ContextTypes.DEFAULT_TYPE, symbol: str, tf: str) -> pd.DataFrame:
    """
    Берём уже очищенные свечи напрямую из Binance.get_klines_df:
    - только закрытые бары
    - dropna по ценам
    - float64 типы
    """
    bn = context.application.bot_data["bn"]
    df = await bn.get_klines_df(symbol, tf)
    if df is None:
        return pd.DataFrame()
    if not df.empty:
        df = df.dropna(subset=["open", "high", "low", "close"]).copy()
        for c in ["open", "high", "low", "close"]:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
        df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    return df

async def build_analysis_text(context: ContextTypes.DEFAULT_TYPE, symbol: str) -> str:
    """Сводка по 1h/4h/1d: RSI(14), SMA20/50, кроссы, базовый паттерн (только закрытые свечи)."""
    safe_symbol = html.escape(symbol)
    parts = [f"<b>{safe_symbol}</b>"]

    for tf, tf_ru in TF_LIST:
        try:
            df = await _fetch_df(context, symbol, tf)
            if df is None or df.empty or len(df) < NEED_CLOSED_MIN:
                parts.append(f"\n[{tf_ru}] недостаточно закрытых свечей")
                continue

            close = df["close"]
            rsi_s = rsi_wilder(close, 14).ffill()
            sma20 = close.rolling(20, min_periods=20).mean()
            sma50 = close.rolling(50, min_periods=50).mean()

            rsi_v = _last_valid_float(rsi_s) or 50.0
            s20 = _last_valid_float(sma20)
            s50 = _last_valid_float(sma50)

            cross_txt = cross_state(sma20, sma50)
            pat = candle_pattern(df)

            cross_part = f"  → <b>{html.escape(cross_txt)}</b>" if cross_txt else ""

            parts.append(
                "\n"
                f"[{tf_ru}]\n"
                f"RSI(14): <b>{_fmt_num(rsi_v, 1)}</b>\n"
                f"SMA20: <code>{_fmt_num(s20, 6)}</code> • SMA50: <code>{_fmt_num(s50, 6)}</code>{cross_part}\n"
                f"Pattern: <i>{html.escape(pat) if pat else 'н/д'}</i>"
            )
        except Exception as e:
            log.warning("analyze %s %s: %r", symbol, tf, e)
            parts.append(f"\n[{tf_ru}] ошибка получения данных")

    parts.append("\n<i>Данные по Binance klines; учитываются только закрытые свечи; время UTC.</i>")
    return "\n".join(parts)

# ---------- Индикаторы / Паттерны ----------

def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce").astype("float64")
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    # Wilder's smoothing (EMA с alpha=1/period)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return rsi.astype("float64").fillna(50.0)

def cross_state(sma_fast: pd.Series, sma_slow: pd.Series) -> str:
    """Пересечение на последних барах. Устойчив к пропускам."""
    f = pd.to_numeric(sma_fast, errors="coerce").dropna()
    s = pd.to_numeric(sma_slow, errors="coerce").dropna()
    if len(f) < 2 or len(s) < 2:
        return ""
    f2, f1 = f.iloc[-2], f.iloc[-1]
    s2, s1 = s.iloc[-2], s.iloc[-1]
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
    """Базовые паттерны по последней ЗАКРЫТОЙ свече."""
    if df is None or df.empty:
        return ""
    row = df[["open", "high", "low", "close"]].iloc[-1]
    if row.isna().any():
        return ""
    try:
        o = float(row["open"]); h = float(row["high"]); l = float(row["low"]); c = float(row["close"])
    except Exception:
        return ""
    body = abs(c - o)
    range_ = max(h - l, 1e-12)
    upper = h - max(c, o)
    lower = min(c, o) - l

    # Doji
    if range_ > 0 and body / range_ < 0.1:
        return "Doji"

    # Hammer / Inverted Hammer
    if lower > 2 * body and upper < body:
        return "Hammer"
    if upper > 2 * body and lower < body:
        return "Inverted Hammer"

    # Engulfing (две последние свечи)
    if len(df) >= 2:
        row2 = df[["open", "close"]].iloc[-2]
        if not row2.isna().any():
            o2 = float(row2["open"]); c2 = float(row2["close"])
            if (c > o) and (c2 < o2) and (c >= o2) and (o <= c2):
                return "Bullish Engulfing"
            if (c < o) and (c2 > o2) and (c <= o2) and (o >= c2):
                return "Bearish Engulfing"

    return "Bullish" if c > o else "Bearish"

# ---------- Сервис ----------

async def safe_edit_text(query, text: str, *, parse_mode: str | None = None, reply_markup=None) -> None:
    """Редактирует сообщение, подавляя 'Message is not modified'."""
    try:
        await query.edit_message_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        raise
