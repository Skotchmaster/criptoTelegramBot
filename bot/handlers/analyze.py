from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards.common import coins_keyboard, tf_keyboard

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_page(update, context, page=1)

async def show_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    scanner = context.application.bot_data["scanner"]
    pairs = await scanner.scannable_pairs()
    kb = coins_keyboard(pairs, page=page, per_page=10)
    text = "Выберите монету (пара к USDT):"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cq = update.callback_query
    if not cq or not cq.data:
        return
    parts = cq.data.split("|")
    if parts[0] == "an":
        if len(parts) >= 2 and parts[1] == "page":
            page = int(parts[2]) if len(parts) >= 3 else 1
            await show_page(update, context, page=page)
            return
        if len(parts) >= 2 and parts[1] == "coin":
            pair = parts[2]
            await cq.edit_message_text(f"Монета: <b>{pair}</b>\nВыберите таймфрейм:", parse_mode="HTML", reply_markup=tf_keyboard(pair))
            return
        if len(parts) >= 2 and parts[1] == "tf":
            pair = parts[2]
            tf = parts[3]
            scanner = context.application.bot_data["scanner"]
            msg = await scanner.manual_summary(pair, tf)
            if not msg:
                msg = "Недостаточно данных для сводки или монета недоступна."
            await cq.edit_message_text(msg, parse_mode="HTML")
            return
        if len(parts) >= 2 and parts[1] == "noop":
            await cq.answer("Страница")
            return
    elif parts[0] == "help":
        await cq.edit_message_text(
            "• Авто‑алерты: 1h/4h/1d, 8 последних свечей подряд.\n"
            "• /analyze — список монет → таймфрейм → сводка."
        )
