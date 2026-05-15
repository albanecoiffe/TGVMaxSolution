from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings


class LiveWorkerStore:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def latest_file(self) -> Path:
        return self.settings.history_dir / "latest-live-worker.json"

    def latest(self) -> dict:
        payload = self._load_json(self.latest_file)
        if payload is not None:
            return payload
        return {
            "has_worker": False,
            "message": "aucun worker navigateur n'a encore envoye de heartbeat",
        }

    def ingest(self, payload: dict) -> dict:
        self.settings.history_dir.mkdir(parents=True, exist_ok=True)
        normalized = {
            "has_worker": True,
            "captured_at": payload.get("captured_at"),
            "backend_base_url": payload.get("backend_base_url"),
            "worker": {
                "status": payload.get("status") or "unknown",
                "watch_tab_url": payload.get("watch_tab_url"),
                "watch_tab_id": payload.get("watch_tab_id"),
                "watch_count": payload.get("watch_count", 0),
                "browser_open": bool(payload.get("browser_open", True)),
                "sncf_tab_ready": bool(payload.get("sncf_tab_ready", False)),
                "last_error": payload.get("last_error"),
                "session_hint": payload.get("session_hint"),
            },
        }
        self.latest_file.write_text(
            json.dumps(normalized, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        return normalized

    def _load_json(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
