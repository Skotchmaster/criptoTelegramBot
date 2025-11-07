from pathlib import Path
from datetime import timedelta
import os
import logging

from telegram.ext import (
    ApplicationBuilder,
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from bot.config import load_config
from bot.storage import JSONStorage
    # ваш класс хранилища
from bot.services.http import HttpClient
    # общий aiohttp клиент
from bot.services.coingecko import CoinGecko
from bot.services.binance import Binance
from bot.services.scanner import Scanner
from bot.handlers.start import start, help_cmd
from bot.handlers.analyze import analyze_cmd, on_callback
from bot.utils.logging import setup_logging


# Единый логгер модуля
log = logging.getLogger("bot.main")


async def on_startup(app: Application):
    """Хук после инициализации Application, но до начала приема апдейтов."""
    http: HttpClient = app.bot_data["http"]
    await http.start()

    admin = os.getenv("ADMIN_CHAT_ID", "").strip()
    if admin:
        try:
            storage: JSONStorage = app.bot_data["storage"]
            await storage.add_chat(int(admin))
            log.info("ADMIN_CHAT_ID=%s подписан на авто-алерты", admin)
        except Exception as e:
            log.warning("ADMIN_CHAT_ID не добавлен: %s", e)


async def on_shutdown(app: Application):
    """Хук при остановке приложения."""
    http: HttpClient = app.bot_data["http"]
    try:
        await http.close()
    except Exception as e:
        log.warning("HTTP session close error: %s", e)


def build_app() -> Application:
    setup_logging()
    cfg = load_config()
    log.info("Config loaded. TZ=%s, SCAN_INTERVAL_MIN=%s", os.getenv("TZ"), cfg.SCAN_INTERVAL_MIN)

    builder = (
        ApplicationBuilder()
        .token(cfg.BOT_TOKEN)
        .post_init(on_startup)   # навешиваем хуки через builder
        .post_stop(on_shutdown)
    )
    app = builder.build()

    # Сервисы/хранилище
    storage = JSONStorage(Path("data/state.json"))
    http = HttpClient(timeout=cfg.HTTP_TIMEOUT)
    cg = CoinGecko(http, cache_ttl=cfg.CACHE_TTL_COINGECKO)
    bn = Binance(
        http,
        cache_ttl_exchange=cfg.CACHE_TTL_EXCHANGEINFO,
        semaphore_limit=cfg.SEMAPHORE_LIMIT,
    )
    scanner = Scanner(cg, bn, storage, batch_sleep=cfg.BATCH_SLEEP)

    app.bot_data.update(
        {
            "cfg": cfg,
            "http": http,
            "storage": storage,
            "cg": cg,
            "bn": bn,
            "scanner": scanner,
        }
    )

    # Хендлеры команд/кнопок
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("analyze", analyze_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))

    # Планировщик
    if app.job_queue is None:
        raise RuntimeError(
            "JobQueue не доступен. Установите: python -m pip install 'python-telegram-bot[job-queue]'"
        )

    async def scanner_job(ctx: ContextTypes.DEFAULT_TYPE):
        try:
            await scanner.scan_once_and_alert(ctx.application)
        except Exception:
            logging.getLogger("bot.scanner").exception("scanner job error")

    app.job_queue.run_repeating(
        scanner_job,
        interval=timedelta(minutes=cfg.SCAN_INTERVAL_MIN),
        first=10,
        name="scanner",
    )

    # Глобальный обработчик ошибок (без обращения к app.logger)
    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
        logging.getLogger("bot.app").exception("Unhandled error", exc_info=context.error)

    app.add_error_handler(on_error)

    return app


def main():
    app = build_app()
    # drop_pending_updates=True удалит старые очереди от Webhook
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
