from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler
from ..keyboards import paginate_coins, timeframe_keyboard
from ..services.market import get_ohlcv_for_ticker
from ..services.coins import get_top_100_id_symbol_name
from ..services.analysis import analyze
from ..services.formatter import format_analysis
from ..utils.errors import DataSourceError

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with context.application.bot_data["http"] as session:
        coins = await get_top_100_id_symbol_name(session)
    context.user_data["coins"] = coins
    context.user_data["page"] = 0
    await update.message.reply_html(
        "Выберите монету из топ-100:",
        reply_markup=paginate_coins(coins, 0)
    )

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if data.startswith("page:"):
        page = int(data.split(":")[1])
        coins = context.user_data.get("coins")
        if not coins:
            async with context.application.bot_data["http"] as session:
                coins = await get_top_100_id_symbol_name(session)
            context.user_data["coins"] = coins
        context.user_data["page"] = page
        await query.edit_message_reply_markup(reply_markup=paginate_coins(coins, page))
        return

    if data.startswith("coin:"):
        _, cid, sym, name = data.split(":", 3)
        await query.edit_message_text(
            f"Монета: <b>{sym}</b> — {name}\nВыберите таймфрейм:",
            parse_mode="HTML",
            reply_markup=timeframe_keyboard(cid, sym, name)
        )
        return

    if data.startswith("tf:"):
        _, cid, sym, name, tf = data.split(":", 4)
        await query.edit_message_text(f"⏳ Анализ {sym}/USDT • {tf} ...", parse_mode="HTML")
        async with context.application.bot_data["http"] as session:
            try:
                df = await get_ohlcv_for_ticker(session, sym, tf)
                if df is None or len(df) < 60:
                    await query.edit_message_text(
                        f"😕 Не нашёл достаточных данных для <b>{sym}/USDT</b> на Binance (tf {tf}).\n"
                        f"Попробуйте другую монету или таймфрейм.",
                        parse_mode="HTML"
                    )
                    return
                res = analyze(df)
                text = format_analysis(sym, name, tf, res)
                await query.edit_message_text(text, parse_mode="HTML")
            except DataSourceError as e:
                await query.edit_message_text(
                    "⚠️ Ошибка источника данных: <code>{}</code>".format(str(e)[:500]),
                    parse_mode="HTML"
                )
            except Exception as e:
                await query.edit_message_text(
                    "❌ Непредвиденная ошибка анализа. Попробуйте позже.\n<code>{}</code>".format(str(e)[:500]),
                    parse_mode="HTML"
                )
        return
