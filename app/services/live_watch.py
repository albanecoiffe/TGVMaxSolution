from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings


class LiveWatchStore:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def latest_file(self) -> Path:
        return self.settings.history_dir / "latest-live-watch.json"

    def latest(self) -> dict:
        payload = self._load_json(self.latest_file)
        if payload is not None:
            return payload
        return {
            "has_live_watch": False,
            "message": "aucune surveillance navigateur n'a encore ete synchronisee",
        }

    def ingest(self, payload: dict) -> dict:
        self.settings.history_dir.mkdir(parents=True, exist_ok=True)
        normalized = self._normalize_payload(payload)
        self.latest_file.write_text(
            json.dumps(normalized, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        return normalized

    def _normalize_payload(self, payload: dict) -> dict:
        watches = payload.get("watches") or []
        summary = payload.get("summary") or {}
        recent_activity = []
        for watch in watches:
            for entry in (watch.get("history") or [])[:3]:
                recent_activity.append(
                    {
                        "route": f'{watch.get("origin_label") or ""} → {watch.get("destination_label") or ""}',
                        "watch_date": watch.get("watch_date"),
                        "type": entry.get("type"),
                        "at": entry.get("at"),
                        "details": {
                            key: value
                            for key, value in entry.items()
                            if key not in {"type", "at"}
                        },
                    }
                )

        recent_activity.sort(key=lambda item: item.get("at") or "", reverse=True)

        return {
            "has_live_watch": True,
            "captured_at": payload.get("captured_at"),
            "source": payload.get("source") or "sncf-probe-extension",
            "summary": {
                "watch_count": summary.get("watch_count", len(watches)),
                "ok_count": summary.get("ok_count", 0),
                "error_count": summary.get("error_count", 0),
                "waiting_count": summary.get("waiting_count", 0),
                "zero_watch_count": summary.get("zero_watch_count", 0),
                "zero_offer_count": summary.get("zero_offer_count", 0),
            },
            "watches": watches,
            "recent_activity": recent_activity[:20],
        }

    def _load_json(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
