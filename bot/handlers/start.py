from telegram import Update
from telegram.ext import ContextTypes


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    storage = context.application.bot_data["storage"]
    chat_id = update.effective_chat.id
    await storage.add_chat(chat_id)
    await update.message.reply_html(
        "Привет! Я буду присылать авто-алерты по рынку.\n"
        "Ты уже подписан на рассылку.\n"
        "Команда /help — помощь."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/analyze <SYMBOL> — ручная сводка (1h/4h/1d)\n"
        "/start — подписаться на авто-алерты\n"
        "/help — помощь"
    )
