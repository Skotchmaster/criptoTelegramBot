from telegram import Update
from telegram.ext import ContextTypes
from ..services.coins import get_top_100_id_symbol_name
from ..keyboards import paginate_coins

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    storage = context.application.bot_data.get("storage")
    if storage:
        storage.add_chat(update.effective_chat.id)

    async with context.application.bot_data["http"] as session:
        coins = await get_top_100_id_symbol_name(session)
    context.user_data["coins"] = coins
    context.user_data["page"] = 0
    await update.message.reply_html(
        "Привет! Я анализирую свечи топ-100 криптовалют.\n"
        "Алерты работают автоматически для 1h, 4h и 1d — ничего включать не нужно.\n\n"
        "Выберите монету:",
        reply_markup=paginate_coins(coins, 0)
    )
