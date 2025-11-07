from typing import List, Tuple
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

def coins_keyboard(pairs: List[Tuple[str, str]], page: int, per_page: int = 10):
    total = len(pairs)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    chunk = pairs[start:start+per_page]

    rows = []
    for pair, name in chunk:
        rows.append([InlineKeyboardButton(text=f"{pair}", callback_data=f"an|coin|{pair}")])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("« Prev", callback_data=f"an|page|{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="an|noop"))
    if page < pages:
        nav.append(InlineKeyboardButton("Next »", callback_data=f"an|page|{page+1}"))
    rows.append(nav)
    return InlineKeyboardMarkup(rows)

def tf_keyboard(pair: str):
    rows = [
        [InlineKeyboardButton("1h", callback_data=f"an|tf|{pair}|1h"),
         InlineKeyboardButton("4h", callback_data=f"an|tf|{pair}|4h"),
         InlineKeyboardButton("1d", callback_data=f"an|tf|{pair}|1d")],
        [InlineKeyboardButton("« К списку", callback_data="an|page|1")]
    ]
    return InlineKeyboardMarkup(rows)
