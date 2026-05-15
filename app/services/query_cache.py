from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic


@dataclass(slots=True)
class CacheEntry:
    expires_at: float
    payload: object


class QueryCache:
    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, CacheEntry] = {}
        self._lock = Lock()

    def get(self, key: str) -> object | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            if entry.expires_at <= monotonic():
                self._items.pop(key, None)
                return None
            return entry.payload

    def set(self, key: str, payload: object) -> object:
        with self._lock:
            self._items[key] = CacheEntry(
                expires_at=monotonic() + max(1, self.ttl_seconds),
                payload=payload,
            )
        return payload

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
