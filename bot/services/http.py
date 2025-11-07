import aiohttp
from typing import Any, Dict, Optional

class HttpClient:
    def __init__(self, timeout: float):
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)

    async def close(self):
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        assert self.session is not None, "HttpClient session is not started"
        async with self.session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()
