from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.config import Settings


class ZeroWatch:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def latest_snapshot_file(self) -> Path:
        return self.settings.history_dir / "latest-zero-snapshot.json"

    @property
    def latest_diff_file(self) -> Path:
        return self.settings.history_dir / "latest-zero-diff.json"

    def record_snapshot(self, trips: pd.DataFrame, generated_at: datetime) -> dict:
        self.settings.history_dir.mkdir(parents=True, exist_ok=True)
        previous_snapshot = self._load_json(self.latest_snapshot_file)
        current_snapshot = self._build_snapshot(trips=trips, generated_at=generated_at)
        diff = self._build_diff(previous_snapshot=previous_snapshot, current_snapshot=current_snapshot)
        self.latest_snapshot_file.write_text(
            json.dumps(current_snapshot, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        self.latest_diff_file.write_text(
            json.dumps(diff, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        return diff

    def latest_diff(self) -> dict:
        diff = self._load_json(self.latest_diff_file)
        if diff is not None:
            return diff

        snapshot = self._load_json(self.latest_snapshot_file)
        if snapshot is None:
            return {
                "has_snapshot": False,
                "message": "aucun snapshot zero EUR n'a encore ete enregistre",
            }

        return {
            "has_snapshot": True,
            "initialized": True,
            "captured_at": snapshot["captured_at"],
            "generated_at": snapshot["generated_at"],
            "current_zero_count": snapshot["zero_trip_count"],
            "previous_zero_count": None,
            "new_zero_count": 0,
            "removed_zero_count": 0,
            "unchanged_zero_count": snapshot["zero_trip_count"],
            "sample_new_trips": [],
            "sample_removed_trips": [],
        }

    def _build_snapshot(self, trips: pd.DataFrame, generated_at: datetime) -> dict:
        zero_trips = trips[trips["is_zero"]].sort_values(
            ["date", "origin", "destination", "depart_time", "arrive_time", "train_no"]
        )
        entries = [self._snapshot_entry(row) for row in zero_trips.itertuples(index=False)]
        return {
            "captured_at": datetime.now().isoformat(),
            "generated_at": generated_at.isoformat(),
            "zero_trip_count": len(entries),
            "entries": entries,
        }

    def _build_diff(self, previous_snapshot: dict | None, current_snapshot: dict) -> dict:
        current_entries = {entry["key"]: entry for entry in current_snapshot["entries"]}
        previous_entries = {
            entry["key"]: entry for entry in (previous_snapshot or {}).get("entries", [])
        }

        new_keys = sorted(set(current_entries) - set(previous_entries))
        removed_keys = sorted(set(previous_entries) - set(current_entries))
        unchanged_keys = sorted(set(current_entries) & set(previous_entries))

        return {
            "has_snapshot": True,
            "initialized": previous_snapshot is None,
            "captured_at": current_snapshot["captured_at"],
            "generated_at": current_snapshot["generated_at"],
            "current_zero_count": current_snapshot["zero_trip_count"],
            "previous_zero_count": previous_snapshot["zero_trip_count"] if previous_snapshot else None,
            "new_zero_count": len(new_keys),
            "removed_zero_count": len(removed_keys),
            "unchanged_zero_count": len(unchanged_keys),
            "sample_new_trips": [current_entries[key] for key in new_keys[:10]],
            "sample_removed_trips": [previous_entries[key] for key in removed_keys[:10]],
        }

    def _snapshot_entry(self, row) -> dict:
        train_no = (getattr(row, "train_no", "") or "").strip()
        return {
            "key": "|".join(
                [
                    row.date,
                    row.origin,
                    row.destination,
                    row.depart_time,
                    row.arrive_time,
                    train_no,
                ]
            ),
            "date": row.date,
            "origin": row.origin,
            "destination": row.destination,
            "departure_time": row.depart_time,
            "arrival_time": row.arrive_time,
            "train_no": train_no or None,
        }

    def _load_json(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
