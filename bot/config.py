from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    BOT_TOKEN: str
    HTTP_TIMEOUT: float = float(os.getenv("HTTP_TIMEOUT", "15"))
    SCAN_INTERVAL_MIN: int = int(os.getenv("SCAN_INTERVAL_MIN", "15"))
    SEMAPHORE_LIMIT: int = int(os.getenv("SEMAPHORE_LIMIT", "10"))
    BATCH_SLEEP: float = float(os.getenv("BATCH_SLEEP", "0.02"))
    CACHE_TTL_COINGECKO: int = 15 * 60
    CACHE_TTL_EXCHANGEINFO: int = 60 * 60
    TZ: str = os.getenv("TZ", "UTC")

def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required. Put it into .env or environment.")
    return Config(BOT_TOKEN=token)
