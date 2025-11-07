import json, os
from typing import Dict, Set, List

class JSONStorage:
    def __init__(self, path: str = "data/state.json"):
        self.path = path
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            self._write({"chats": [], "alerts_sent": {}})

    def _read(self) -> Dict:
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: Dict):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def add_chat(self, chat_id: int):
        data = self._read()
        chats: List[int] = data.get("chats", [])
        if int(chat_id) not in chats:
            chats.append(int(chat_id))
            data["chats"] = chats
            self._write(data)

    def all_chats(self) -> List[int]:
        return self._read().get("chats", [])

    def is_alert_sent(self, key: str) -> bool:
        return key in self._read().get("alerts_sent", {})

    def mark_alert_sent(self, key: str):
        data = self._read()
        data.setdefault("alerts_sent", {})[key] = True
        if len(data["alerts_sent"]) > 5000:
            data["alerts_sent"] = dict(list(data["alerts_sent"].items())[-2000:])
        self._write(data)
