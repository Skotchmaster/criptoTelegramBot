from telegram import Update
from telegram.ext import ContextTypes

HELP_TEXT = (
    "Команды:\n"
    "/start — начать и выбрать монету\n"
    "/help — справка\n"
    "/analyze — заново открыть выбор монеты\n\n"
    "После выбора монеты выберите таймфрейм (1h/4h/1d) — я пришлю сводку по RSI, SMA и паттернам."
)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)
