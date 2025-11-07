from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, Application


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(f"Ваш chat_id: {update.effective_chat.id}")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("pong")

def register(app: Application) -> None:
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("ping", ping))
