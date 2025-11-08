import logging
from telegram import Update
from telegram.ext import ContextTypes

log = logging.getLogger("bot.handlers.start")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подписка чата на авто-алерты."""
    storage = context.application.bot_data["storage"]
    chat = update.effective_chat

    await storage.add_chat(chat.id)
    log.info("/start by chat_id=%s username=%s title=%s",
             chat.id, getattr(chat, "username", None), getattr(chat, "title", None))

    await update.message.reply_html(
        "Привет! Я буду присылать авто-алерты по рынку.\n"
        "Ты уже подписан на рассылку.\n"
        "Команда /help — помощь. Команда /stop — отписка."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подсказка по командам."""
    await update.message.reply_text(
        "/start — подписаться на авто-алерты\n"
        "/stop — отписаться от авто-алертов\n"
        "/help — помощь"
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отписка чата от авто-алертов."""
    storage = context.application.bot_data["storage"]
    chat = update.effective_chat

    await storage.remove_chat(chat.id)
    log.info("/stop by chat_id=%s username=%s title=%s",
             chat.id, getattr(chat, "username", None), getattr(chat, "title", None))

    await update.message.reply_text("❌ Подписка на авто-алерты отключена.")
