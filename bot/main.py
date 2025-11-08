from pathlib import Path
from datetime import timedelta, datetime, timezone
import os
import logging

from telegram.ext import (
    ApplicationBuilder,
    Application,
    CommandHandler,
    ContextTypes,
)
from telegram.request import HTTPXRequest
from telegram.error import TimedOut, NetworkError

from bot.config import load_config
from bot.services.storage import JSONStorage
from bot.services.http import HttpClient
from bot.services.coingecko import CoinGecko
from bot.services.binance import Binance
from bot.services.scanner import Scanner
from bot.handlers.start import start, help_cmd
from bot.utils.logging import setup_logging

log = logging.getLogger("bot.main")


async def on_startup(app: Application):
    """
    Хук после инициализации Application, но до начала приёма апдейтов.
    Тут стартуем общий HTTP-клиент и при необходимости автоподписываем админа.
    Плюс — полезные логи по окружению и подписчикам.
    """
    http: HttpClient = app.bot_data["http"]
    await http.start()

    storage: JSONStorage = app.bot_data["storage"]

    tz = os.getenv("TZ", "UTC")
    log.info("Startup at %s TZ=%s", datetime.now(timezone.utc).isoformat(), tz)

    chats = await storage.get_chats()
    log.info("Subscribers on start: %d -> %s", len(chats), chats)

    admin = os.getenv("ADMIN_CHAT_ID", "").strip()
    if admin:
        try:
            admin_id = int(admin)
            await storage.add_chat(admin_id)
            log.info("ADMIN_CHAT_ID=%s автоподписан на авто-алерты", admin)
        except Exception as e:
            log.warning("ADMIN_CHAT_ID не добавлен: %s", e)


async def on_shutdown(app: Application):
    """Хук при остановке приложения."""
    http: HttpClient = app.bot_data.get("http")
    if not http:
        return
    try:
        await http.close()
        log.info("HTTP session closed")
    except Exception as e:
        log.warning("HTTP session close error: %s", e)


def _build_httpx_request() -> HTTPXRequest:
    """
    Кастомный клиент для Telegram API:
    - больше пул соединений,
    - адекватные таймауты,
    - поддержка прокси через env.
    """
    proxy = os.getenv("TELEGRAM_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("ALL_PROXY") or None
    return HTTPXRequest(
        connection_pool_size=20,
        pool_timeout=None,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        proxy=proxy,
    )


def build_app() -> Application:
    setup_logging()

    cfg = load_config()
    log.info("Config loaded. TZ=%s, SCAN_INTERVAL_MIN=%s, HTTP_TIMEOUT=%s",
             os.getenv("TZ", "UTC"), cfg.SCAN_INTERVAL_MIN, cfg.HTTP_TIMEOUT)

    builder = (
        ApplicationBuilder()
        .token(cfg.BOT_TOKEN)
        .request(_build_httpx_request())
        .post_init(on_startup)
        .post_stop(on_shutdown)
    )
    app = builder.build()

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

    # Хендлеры
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    # Планировщик
    if app.job_queue is None:
        log.error("No JobQueue set up! Установите: pip install 'python-telegram-bot[job-queue]'")
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
    log.info('JobQueue: добавлена задача "scanner" каждые %s минут (first=10s)', cfg.SCAN_INTERVAL_MIN)

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
        err = context.error
        text = str(err)
        retryable_markers = ("ConnectTimeout", "ReadTimeout", "Timed out", "ConnectError")
        if isinstance(err, (TimedOut, NetworkError)) or any(m in text for m in retryable_markers):
            logging.getLogger("bot.app").warning("Telegram API timeout/network issue: %s", text)
            return
        logging.getLogger("bot.app").exception("Unhandled error", exc_info=err)

    app.add_error_handler(on_error)

    return app


def main():
    app = build_app()
    log.info("Running polling (drop_pending_updates=True)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
