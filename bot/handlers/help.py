from telegram import Update
from telegram.ext import ContextTypes

HELP_TEXT = (
    "Я присылаю авто-уведомления, когда по паре формируется серия из 8 закрытых свечей одного цвета "
    "(на таймфреймах 1h, 4h, 1d).\n"
    "/start — подписаться на уведомления\n"
    "/help — эта справка"
)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)
