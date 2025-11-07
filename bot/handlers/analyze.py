from __future__ import annotations

import math
import html
import time
import logging
from typing import List

import pandas as pd
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

log = logging.getLogger("bot.handlers.analyze")

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


# ---------- UI: список пар ----------

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
        await safe_edit_text(update.callback_query, header, reply_markup=kb)
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


def _closed_klines(klines):
    """Оставляем только закрытые свечи (k[6] = closeTime в ms)."""
    now_ms = int(time.time() * 1000)
    return [k for k in (klines or []) if int(k[6]) <= now_ms]


def _need_limit_for(tf: str, need_closed: int) -> int:
    """
    Сколько запрашивать свечей у Binance, чтобы наверняка хватило после отбрасывания текущей.
    """
    base = {"1h": 200, "4h": 240, "1d": 500}.get(tf, 200)
    return max(base, need_closed + 10)


def _last_valid_float(s: pd.Series) -> float:
    """Возвращает последнее валидное float-значение серии (устойчиво к pd.NA/NaN/типам)."""
    v = pd.to_numeric(s, errors="coerce").dropna()
    if v.empty:
        raise ValueError("no valid values")
    return float(v.iloc[-1])


async def build_analysis_text(context: ContextTypes.DEFAULT_TYPE, symbol: str) -> str:
    """Собирает сводку по 1h/4h/1d: RSI(14), SMA20/50, кроссы, базовый паттерн (только по закрытым свечам)."""
    app_data = context.application.bot_data
    bn = app_data["bn"]
    scanner = app_data["scanner"]  # используем его конвертер klines_to_df

    tf_list = [("1h", "1ч"), ("4h", "4ч"), ("1d", "1д")]
    need_for_ind = 50  # минимум закрытых свечей для стабильных SMA20/50 и RSI(14)

    safe_symbol = html.escape(symbol)
    parts = [f"<b>{safe_symbol}</b>"]

    # тянем сырые klines один раз
    kl_1h = await bn.get_klines(symbol, "1h", limit=_need_limit_for("1h", need_for_ind))
    kl_4h = await bn.get_klines(symbol, "4h", limit=_need_limit_for("4h", need_for_ind))
    kl_1d = await bn.get_klines(symbol, "1d", limit=_need_limit_for("1d", need_for_ind))
    log.debug(
        "analyze %s: len_closed(1h/4h/1d)=%s/%s/%s",
        symbol,
        len(_closed_klines(kl_1h)) if kl_1h else None,
        len(_closed_klines(kl_4h)) if kl_4h else None,
        len(_closed_klines(kl_1d)) if kl_1d else None,
    )
    raw_by_tf = {"1h": kl_1h, "4h": kl_4h, "1d": kl_1d}

    for tf, tf_ru in tf_list:
        try:
            raw = raw_by_tf[tf]
            if not raw:
                log.warning("analyze %s %s: пустой ответ от Binance", symbol, tf)
                parts.append(f"\n[{tf_ru}] ошибка получения данных")
                continue

            # Только закрытые свечи
            closed = _closed_klines(raw)
            if len(closed) < need_for_ind:
                parts.append(f"\n[{tf_ru}] недостаточно закрытых свечей")
                continue

            # Преобразуем в DataFrame только закрытые свечи
            df = scanner.klines_to_df(closed)

            # Убираем любые «битые» бары и приводим типы к float64
            df = df.dropna(subset=["open", "high", "low", "close"]).copy()
            if len(df) < need_for_ind:
                parts.append(f"\n[{tf_ru}] недостаточно закрытых свечей")
                continue
            df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].astype("float64")

            # Индикаторы
            rsi = rsi_wilder(df["close"], 14).ffill()
            sma20 = df["close"].rolling(20, min_periods=20).mean()
            sma50 = df["close"].rolling(50, min_periods=50).mean()

            # Безопасно берём последние валидные значения
            rsi_v = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0
            s20 = _last_valid_float(sma20)
            s50 = _last_valid_float(sma50)

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
        except ValueError as e:
            log.debug("analyze %s %s: %s", symbol, tf, e)
            parts.append(f"\n[{tf_ru}] недостаточно данных для SMA/RSI")
        except Exception as e:
            log.warning("analyze %s %s: %r", symbol, tf, e)
            parts.append(f"\n[{tf_ru}] ошибка получения данных")

    parts.append("\n<i>Данные по Binance klines; учитываются только закрытые свечи; время UTC.</i>")
    return "\n".join(parts)


# ---------- Индикаторы / Паттерны ----------

def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    # Wilder's smoothing (EMA с alpha=1/period)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / (roll_down.replace(0, pd.NA))
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.astype("float64")
    return rsi.fillna(50.0)


def cross_state(sma_fast: pd.Series, sma_slow: pd.Series) -> str:
    """Возвращает пометку о пересечении на последних барах (без HTML). Устойчив к пропускам."""
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
    """Очень базовые паттерны по последней ЗАКРЫТОЙ свече."""
    if len(df) == 0:
        return ""
    row = df[["open", "high", "low", "close"]].iloc[-1]
    if row.isna().any():
        return ""
    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])

    body = abs(c - o)
    range_ = max(h - l, 1e-12)
    upper = h - max(c, o)
    lower = min(c, o) - l

    # Doji: маленькое тело
    if range_ > 0 and body / range_ < 0.1:
        return "Doji"

    # Hammer / Inverted Hammer
    if lower > 2 * body and upper < body:
        return "Hammer"
    if upper > 2 * body and lower < body:
        return "Inverted Hammer"

    # Engulfing (смотрим две последние)
    if len(df) >= 2:
        row2 = df[["open", "close"]].iloc[-2].dropna()
        if len(row2) == 2:
            o2 = float(row2["open"]); c2 = float(row2["close"])
            if (c > o) and (c2 < o2) and (c >= o2) and (o <= c2):
                return "Bullish Engulfing"
            if (c < o) and (c2 > o2) and (c <= o2) and (o >= c2):
                return "Bearish Engulfing"

    # По умолчанию — направление тела
    return "Bullish" if c > o else "Bearish"


# ---------- Сервис: безопасное редактирование текста ----------

async def safe_edit_text(query, text: str, *, parse_mode: str | None = None, reply_markup=None) -> None:
    """Редактирует сообщение, подавляя 'Message is not modified'."""
    try:
        await query.edit_message_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        raise
