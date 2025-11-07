from __future__ import annotations

import logging
import re

_TOKEN_RE = re.compile(r"(/bot(\d{6,12}):[A-Za-z0-9_-]{10,}/)")

class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        s = super().format(record)
        return _TOKEN_RE.sub(r"/bot\2:<REDACTED>/", s)


def setup_logging() -> None:
    """
    Единая настройка логов:
      - формат: 'YYYY-mm-dd HH:MM:SS,ms | LEVEL | logger | message'
      - замена токена Telegram на <REDACTED>
      - приглушаем шумные логгеры (httpx и т.п.)
    """
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter(fmt))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx._client").setLevel(logging.WARNING)

    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("telegram").setLevel(logging.INFO)
    logging.getLogger("telegram.ext").setLevel(logging.INFO)

