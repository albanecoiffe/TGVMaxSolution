from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings


HISTORY_LIMIT = 1000


class LiveWatchStore:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def latest_file(self) -> Path:
        return self.settings.history_dir / "latest-live-watch.json"

    @property
    def history_file(self) -> Path:
        return self.settings.history_dir / "live-watch-history.jsonl"

    def latest(self) -> dict:
        payload = self._load_json(self.latest_file)
        if payload is not None:
            return payload
        return {
            "has_live_watch": False,
            "message": "aucune surveillance navigateur n'a encore ete synchronisee",
        }

    def history(self, limit: int = 50) -> dict:
        if not self.history_file.exists():
            return {"has_history": False, "count": 0, "entries": []}
        entries = []
        for line in self.history_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        selected = entries[-limit:][::-1]
        return {"has_history": True, "count": len(selected), "entries": selected}

    def ingest(self, payload: dict) -> dict:
        self.settings.history_dir.mkdir(parents=True, exist_ok=True)
        normalized = self._normalize_payload(payload)
        self.latest_file.write_text(
            json.dumps(normalized, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        self._append_history(normalized)
        return normalized

    def _normalize_payload(self, payload: dict) -> dict:
        watches = payload.get("watches") or []
        summary = payload.get("summary") or {}
        normalized_watches = [self._normalize_watch(watch) for watch in watches]
        recent_activity = []
        for watch in normalized_watches:
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
                "zero_day_count": summary.get(
                    "zero_day_count",
                    sum(watch["zero_day_count"] for watch in normalized_watches),
                ),
            },
            "watches": normalized_watches,
            "zero_calendar": self._build_zero_calendar(normalized_watches),
            "recent_activity": recent_activity[:20],
        }

    def _normalize_watch(self, watch: dict) -> dict:
        normalized = dict(watch)
        zero_days = self._normalize_zero_days(watch.get("zero_days"))
        if not zero_days and watch.get("zero_offer_count"):
            watch_date = watch.get("watch_date")
            if watch_date:
                zero_days = [{"date": str(watch_date)[:10], "label": None, "best_price_datetime": None}]
        normalized["zero_days"] = zero_days
        normalized["zero_day_count"] = len(zero_days)
        return normalized

    def _normalize_zero_days(self, zero_days: object) -> list[dict]:
        normalized: dict[str, dict] = {}
        for item in zero_days or []:
            if isinstance(item, str):
                candidate = {"date": item[:10], "label": None, "best_price_datetime": None}
            elif isinstance(item, dict):
                raw_date = item.get("date") or item.get("best_price_datetime") or item.get("bestPriceDateTime") or ""
                candidate = {
                    "date": str(raw_date)[:10],
                    "label": item.get("label"),
                    "best_price_datetime": item.get("best_price_datetime") or item.get("bestPriceDateTime"),
                }
            else:
                continue
            if len(candidate["date"]) == 10 and candidate["date"] not in normalized:
                normalized[candidate["date"]] = candidate
        return [normalized[key] for key in sorted(normalized)]

    def _build_zero_calendar(self, watches: list[dict]) -> list[dict]:
        calendar: dict[str, dict] = {}
        for watch in watches:
            route = f'{watch.get("origin_label") or ""} → {watch.get("destination_label") or ""}'
            entry = calendar.setdefault(
                route,
                {
                    "route": route,
                    "origin_label": watch.get("origin_label"),
                    "destination_label": watch.get("destination_label"),
                    "days": {},
                    "last_checked_at": None,
                },
            )
            for day in watch.get("zero_days") or []:
                if isinstance(day, dict) and day.get("date"):
                    entry["days"].setdefault(day["date"], day)
            last_checked_at = watch.get("last_checked_at")
            if last_checked_at and (entry["last_checked_at"] is None or last_checked_at > entry["last_checked_at"]):
                entry["last_checked_at"] = last_checked_at

        result = []
        for entry in calendar.values():
            days = [entry["days"][key] for key in sorted(entry["days"])]
            result.append(
                {
                    "route": entry["route"],
                    "origin_label": entry["origin_label"],
                    "destination_label": entry["destination_label"],
                    "zero_day_count": len(days),
                    "zero_days": days,
                    "last_checked_at": entry["last_checked_at"],
                }
            )
        result.sort(key=lambda item: item["route"])
        return result

    def _append_history(self, payload: dict) -> None:
        entry = {
            "captured_at": payload.get("captured_at"),
            "source": payload.get("source"),
            "summary": payload.get("summary"),
        }
        lines = []
        if self.history_file.exists():
            lines = self.history_file.read_text(encoding="utf-8").splitlines()
        lines.append(json.dumps(entry, ensure_ascii=True))
        if len(lines) > HISTORY_LIMIT:
            lines = lines[-HISTORY_LIMIT:]
        self.history_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _load_json(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
