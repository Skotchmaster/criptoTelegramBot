from __future__ import annotations

import json
import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List


class JSONStorage:
    """
    Простое файловое хранилище в JSON.
    Структура файла:
    {
      "chats": [<chat_id:int>, ...],
      "alerts": { "<dedup_key>": <unix_ts:int>, ... }
    }
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()

    async def _ensure_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            await self._write({"chats": [], "alerts": {}})

    async def _read(self) -> Dict[str, Any]:
        await self._ensure_file()

        def _sync_read():
            with self.path.open("r", encoding="utf-8") as f:
                return json.load(f)

        return await asyncio.to_thread(_sync_read)

    async def _write(self, data: Dict[str, Any]) -> None:
        def _sync_write():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

        await asyncio.to_thread(_sync_write)

    # ---------- ЧАТЫ ----------
    async def get_chats(self) -> List[int]:
        """Вернуть уникальные chat_id, отсортированные по возрастанию."""
        async with self._lock:
            data = await self._read()
            chats = data.get("chats") or []
            return sorted({int(c) for c in chats})

    async def add_chat(self, chat_id: int) -> None:
        """Добавить чат в подписчики (идемпотентно)."""
        async with self._lock:
            data = await self._read()
            chats = set(int(c) for c in data.get("chats") or [])
            chats.add(int(chat_id))
            data["chats"] = sorted(chats)
            await self._write(data)

    async def remove_chat(self, chat_id: int) -> None:
        """Удалить чат из подписчиков (если был)."""
        async with self._lock:
            data = await self._read()
            chats = set(int(c) for c in data.get("chats") or [])
            chats.discard(int(chat_id))
            data["chats"] = sorted(chats)
            await self._write(data)

    # ---------- ДЕДУПЛИКАЦИЯ АЛЕРТОВ ----------
    async def is_alert_sent(self, key: str) -> bool:
        """True, если по этому ключу уже отправляли уведомление."""
        async with self._lock:
            data = await self._read()
            alerts: Dict[str, int] = data.get("alerts") or {}
            return key in alerts

    async def mark_alert_sent(self, key: str) -> None:
        """
        Пометить алерт как отправленный.
        Храним время отправки (unix_ts). Периодически подчищаем до ~2000 последних ключей.
        """
        async with self._lock:
            data = await self._read()
            alerts: Dict[str, int] = data.get("alerts") or {}
            alerts[key] = int(time.time())

            # Подчистка, если сильно разрослись
            if len(alerts) > 5000:
                # оставляем ~2000 последних по порядку добавления
                alerts = dict(list(alerts.items())[-2000:])

            data["alerts"] = alerts
            await self._write(data)
