import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    HTTP_TIMEOUT: int = int(os.getenv("HTTP_TIMEOUT", "15"))
    CACHE_SIZE: int = int(os.getenv("CACHE_SIZE", "256"))

config = Config()

if not config.BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Укажите его в .env")
