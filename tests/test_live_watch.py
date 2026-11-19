from __future__ import annotations

import app.services.live_watch as live_watch_module
from app.services.live_watch import LiveWatchStore


def test_ingest_is_idempotent_and_history_grows(settings):
    store = LiveWatchStore(settings)
    payload = {
        "captured_at": "2026-05-15T09:00:00Z",
        "watches": [],
        "summary": {"watch_count": 0},
    }

    first = store.ingest(payload)
    second = store.ingest(payload)

    assert first == second
    history = store.history(limit=10)
    assert history["has_history"] is True
    assert history["count"] == 2


def test_history_is_bounded(settings, monkeypatch):
    monkeypatch.setattr(live_watch_module, "HISTORY_LIMIT", 5)
    store = LiveWatchStore(settings)

    for index in range(8):
        store.ingest({"captured_at": f"2026-05-15T09:0{index}:00Z", "watches": [], "summary": {}})

    history = store.history(limit=100)
    assert history["count"] == 5
    assert history["entries"][0]["captured_at"] == "2026-05-15T09:07:00Z"
    assert history["entries"][-1]["captured_at"] == "2026-05-15T09:03:00Z"


def test_zero_calendar_dedupes_days_across_watches_of_same_route(settings):
    store = LiveWatchStore(settings)
    payload = {
        "captured_at": "2026-05-15T09:00:00Z",
        "watches": [
            {
                "id": "A|B|2026-05-23",
                "origin_label": "A",
                "destination_label": "B",
                "watch_date": "2026-05-23",
                "zero_days": [
                    {"date": "2026-05-23", "label": "Sam 23"},
                    {"date": "2026-05-24", "label": "Dim 24"},
                ],
                "last_checked_at": "2026-05-15T08:00:00Z",
            },
            {
                "id": "A|B|2026-05-30",
                "origin_label": "A",
                "destination_label": "B",
                "watch_date": "2026-05-30",
                "zero_days": [{"date": "2026-05-24", "label": "Dim 24"}, "2026-05-30"],
                "last_checked_at": "2026-05-15T09:00:00Z",
            },
        ],
    }

    normalized = store.ingest(payload)

    calendar = normalized["zero_calendar"]
    assert len(calendar) == 1
    assert calendar[0]["zero_day_count"] == 3
    assert [day["date"] for day in calendar[0]["zero_days"]] == ["2026-05-23", "2026-05-24", "2026-05-30"]
    assert calendar[0]["last_checked_at"] == "2026-05-15T09:00:00Z"
    assert normalized["summary"]["zero_day_count"] == 3
