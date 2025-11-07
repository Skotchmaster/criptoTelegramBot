from pathlib import Path
from datetime import timedelta

from telegram.ext import (
    ApplicationBuilder, Application, CommandHandler, CallbackQueryHandler
)

from bot.config import load_config
from bot.storage import JSONStorage
from bot.services.http import HttpClient
from bot.services.coingecko import CoinGecko
from bot.services.binance import Binance
from bot.services.scanner import Scanner
from bot.handlers.start import start, help_cmd
from bot.handlers.analyze import analyze_cmd, on_callback

DATA_PATH = Path("data/state.json")

async def on_startup(app: Application):
    http = app.bot_data["http"]
    await http.start()

async def on_shutdown(app: Application):
    http = app.bot_data.get("http")
    if http:
        await http.close()

def build_app() -> Application:
    cfg = load_config()

    storage = JSONStorage(DATA_PATH)
    http = HttpClient(timeout=cfg.HTTP_TIMEOUT)
    cg = CoinGecko(http, cache_ttl=cfg.CACHE_TTL_COINGECKO)
    bn = Binance(http, cache_ttl_exchange=cfg.CACHE_TTL_EXCHANGEINFO, semaphore_limit=cfg.SEMAPHORE_LIMIT)
    scanner = Scanner(cg, bn, storage, batch_sleep=cfg.BATCH_SLEEP)

    app = ApplicationBuilder().token(cfg.BOT_TOKEN).post_init(on_startup).post_shutdown(on_shutdown).build()
    app.bot_data.update({
        "config": cfg,
        "storage": storage,
        "http": http,
        "coingecko": cg,
        "binance": bn,
        "scanner": scanner,
    })

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("analyze", analyze_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))

    app.job_queue.run_repeating(lambda ctx: scanner.scan_once_and_alert(ctx.application),
                                interval=timedelta(minutes=cfg.SCAN_INTERVAL_MIN),
                                first=10)

    app.post_init = on_startup
    app.post_stop = on_shutdown
    return app

def main():
    app = build_app()
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
