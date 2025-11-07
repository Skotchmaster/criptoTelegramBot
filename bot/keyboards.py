from typing import List, Tuple
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def paginate_coins(coins: List[Tuple[str, str, str]], page: int, per_page: int = 10):
    start = page * per_page
    chunk = coins[start:start+per_page]
    rows = []
    for cid, sym, name in chunk:
        rows.append([InlineKeyboardButton(f"{sym} • {name}", callback_data=f"coin:{cid}:{sym}:{name}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"page:{page-1}"))
    if start + per_page < len(coins):
        nav.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f"page:{page+1}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(rows)

def timeframe_keyboard(cid: str, sym: str, name: str):
    rows = [
        [
            InlineKeyboardButton("1h", callback_data=f"tf:{cid}:{sym}:{name}:1h"),
            InlineKeyboardButton("4h", callback_data=f"tf:{cid}:{sym}:{name}:4h"),
            InlineKeyboardButton("1d", callback_data=f"tf:{cid}:{sym}:{name}:1d"),
        ],
        [InlineKeyboardButton("🔙 К списку", callback_data="page:0")]
    ]
    return InlineKeyboardMarkup(rows)
