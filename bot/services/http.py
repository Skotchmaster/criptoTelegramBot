import aiohttp
from typing import Any, Dict, Optional

class HttpClient:
    def __init__(self, timeout: float = 30.0, headers: Optional[Dict[str, str]] = None):
        # Таймаут по умолчанию для всех запросов
        self.default_timeout = float(timeout)
        self.default_headers = headers or {}
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        if self.session is None:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.default_timeout),
                headers=self.default_headers,
                trust_env=True,  # уважать HTTPS_PROXY/ALL_PROXY из окружения
            )

    async def close(self):
        if self.session is not None and not self.session.closed:
            await self.session.close()
        self.session = None

    async def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,   # ← per-request таймаут
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        assert self.session is not None, "HttpClient session is not started"

        kwargs: Dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout"] = aiohttp.ClientTimeout(total=float(timeout))
        if headers:
            kwargs["headers"] = headers

        async with self.session.get(url, params=params, **kwargs) as resp:
            resp.raise_for_status()
            # У Binance иногда «ломаный» content-type → парсим без проверки
            return await resp.json(content_type=None)
