from __future__ import annotations

import json
import asyncio
import time
import logging
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger("bot.storage")


class JSONStorage:

    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()

    # ---------- НИЗКОУРОВНЕВКА ----------

    async def _ensure_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            init_data = {"chats": [], "alerts_by_chat": {}}
            await self._write(init_data)
            log.warning("Storage file not found, created new: %s", self.path)

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
        log.debug(
            "Storage saved: chats=%d alerts_by_chat_chats=%d",
            len(data.get("chats") or []),
            len((data.get("alerts_by_chat") or {}).keys()),
        )

    # ---------- ЧАТЫ ----------

    async def get_chats(self) -> List[int]:
        """Вернуть уникальные chat_id, отсортированные по возрастанию."""
        async with self._lock:
            data = await self._read()
            chats = sorted({int(c) for c in (data.get("chats") or [])})
            log.debug("get_chats -> %d chats: %s", len(chats), chats)
            return chats

    async def add_chat(self, chat_id: int) -> None:
        """Добавить чат в подписчики (идемпотентно)."""
        async with self._lock:
            data = await self._read()
            chats = set(int(c) for c in (data.get("chats") or []))
            if int(chat_id) in chats:
                log.debug("add_chat: chat %s already subscribed", chat_id)
            else:
                chats.add(int(chat_id))
                data["chats"] = sorted(chats)
                await self._write(data)
                log.info("Subscribed chat %s (total=%d)", chat_id, len(chats))

    async def remove_chat(self, chat_id: int) -> None:
        """Удалить чат из подписчиков (если был)."""
        async with self._lock:
            data = await self._read()
            chats = set(int(c) for c in (data.get("chats") or []))
            if int(chat_id) in chats:
                chats.remove(int(chat_id))
                data["chats"] = sorted(chats)
                # Дополнительно чистим его бакет дедупа
                abd = data.get("alerts_by_chat") or {}
                abd.pop(str(int(chat_id)), None)
                data["alerts_by_chat"] = abd
                await self._write(data)
                log.info("Unsubscribed chat %s (total=%d)", chat_id, len(chats))
            else:
                log.debug("remove_chat: chat %s not in subscribers", chat_id)

    # ---------- ДЕДУПЛИКАЦИЯ АЛЕРТОВ (per-chat) ----------

    def _bucket(self, data: Dict[str, Any], chat_id: int) -> Dict[str, int]:
        abd: Dict[str, Dict[str, int]] = data.setdefault("alerts_by_chat", {})
        return abd.setdefault(str(int(chat_id)), {})

    async def is_alert_sent(self, chat_id: int, key: str) -> bool:
        """True, если по этому ключу уже отправляли в ЭТОТ чат."""
        async with self._lock:
            data = await self._read()
            sent = key in self._bucket(data, chat_id)
            log.debug("Dedup check chat=%s [%s] -> %s", chat_id, key, sent)
            return sent

    async def mark_alert_sent(self, chat_id: int, key: str, ttl_days: int | None = None) -> None:
        """
        Пометить алерт как отправленный для конкретного чата.
        Храним время отправки (unix_ts).
        Подчищаем карту:
          - по TTL (если задан ttl_days),
          - по лимиту размера (оставляем ~2000 последних при росте > 5000).
        """
        async with self._lock:
            data = await self._read()
            bucket = self._bucket(data, chat_id)

            bucket[key] = int(time.time())
            before = len(bucket)

            if ttl_days:
                cutoff = int(time.time()) - ttl_days * 86400
                keys_to_del = [k for k, v in bucket.items() if v < cutoff]
                for k in keys_to_del:
                    del bucket[k]

            if len(bucket) > 5000:
                # оставим ~2000 последних (по порядку вставки для CPython 3.7+)
                for k in list(bucket.keys())[:-2000]:
                    del bucket[k]

            after = len(bucket)
            if after != before:
                log.info("Alerts cleanup chat=%s: %d -> %d (ttl_days=%s)", chat_id, before, after, ttl_days)

            await self._write(data)
            log.info("Marked alert sent chat=%s: %s", chat_id, key)

    # ---------- УТИЛИТЫ ----------

    async def clear_alerts(self) -> None:
        """Полностью очистить карту дедупа (не трогая подписчиков). Удобно для тестов."""
        async with self._lock:
            data = await self._read()
            abd = data.get("alerts_by_chat") or {}
            before = sum(len(v or {}) for v in abd.values())
            data["alerts_by_chat"] = {}
            await self._write(data)
            log.warning("Alerts cleared (all chats): %d -> 0", before)

    async def migrate_legacy(self) -> None:
        """
        Миграция со старого формата:
          старое поле 'alerts': { key: ts } переносим в alerts_by_chat.__legacy__
        """
        async with self._lock:
            data = await self._read()
            legacy = data.pop("alerts", None)
            if isinstance(legacy, dict) and legacy:
                abd = data.setdefault("alerts_by_chat", {})
                bucket = abd.setdefault("__legacy__", {})
                bucket.update(legacy)
                await self._write(data)
                log.warning("Migrated legacy 'alerts' -> 'alerts_by_chat.__legacy__' (%d keys)", len(legacy))
