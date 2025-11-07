from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

START_TEXT = (
    "Привет! Я авто‑сканер. Каждые 15 минут проверяю топ‑100 монет на таймфреймах 1h/4h/1d "
    "и присылаю алерты, если подряд 8 свечей одного цвета.\n\n"
    "Также я умею делать ручную сводку по выбранной монете."
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    storage = context.application.bot_data["storage"]
    await storage.add_chat(update.effective_chat.id)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Анализ монеты", callback_data="an|page|1")],
        [InlineKeyboardButton("ℹ️ Справка", callback_data="help")]
    ])
    await update.message.reply_text(START_TEXT, reply_markup=kb)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "• Автоматические алерты: проверка 1h/4h/1d, 8 последних свечей подряд зелёные/красные.\n"
        "• /analyze — выбери монету из топ‑100 (доступные на Binance USDT), затем таймфрейм и получи сводку "
        "RSI(14), SMA20/50, тренд, кроссы и базовые свечные паттерны."
    )
    await update.effective_message.reply_text(text)
