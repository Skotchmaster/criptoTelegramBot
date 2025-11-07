import asyncio
import json
from pathlib import Path
from typing import Dict, List

class JSONStorage:
    def __init__(self, path: Path):
        self.path = path
        self.lock = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_sync({"chats": [], "alerts_sent": {}})

    def _read_sync(self) -> Dict:
        if not self.path.exists():
            return {"chats": [], "alerts_sent": {}}
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_sync(self, data: Dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)

    async def add_chat(self, chat_id: int) -> None:
        async with self.lock:
            data = self._read_sync()
            if chat_id not in data["chats"]:
                data["chats"].append(chat_id)
                self._write_sync(data)

    async def list_chats(self) -> List[int]:
        async with self.lock:
            return list(self._read_sync().get("chats", []))

    async def has_alert(self, key: str) -> bool:
        async with self.lock:
            return key in self._read_sync().get("alerts_sent", {})

    async def mark_alert(self, key: str) -> None:
        async with self.lock:
            data = self._read_sync()
            data.setdefault("alerts_sent", {})[key] = True
            self._write_sync(data)
