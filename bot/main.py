import aiohttp
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from .config import config
from .utils.logging import setup_logging
from .handlers import start, help_cmd, analyze_cmd, on_callback

def main():
    setup_logging()

    app = Application.builder().token(config.BOT_TOKEN).build()

    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=config.HTTP_TIMEOUT))
    class SessionWrapper:
        def __init__(self, s): self._s = s
        async def __aenter__(self): return self._s
        async def __aexit__(self, exc_type, exc, tb): return False
    app.bot_data["http"] = SessionWrapper(session)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("analyze", analyze_cmd))

    app.add_handler(CallbackQueryHandler(on_callback))

    async def _shutdown(app_):
        await session.close()
    app.post_stop(_shutdown)

    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
