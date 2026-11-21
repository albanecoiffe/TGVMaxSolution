from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.live_dataset_diff import STATUS_MISSING, parse_travel_id


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "demo_live_ingest.py"
SPEC = importlib.util.spec_from_file_location("demo_live_ingest", MODULE_PATH)
demo_live_ingest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo_live_ingest)


NOW = datetime(2026, 11, 19, 13, 0, 0, tzinfo=timezone.utc)


def test_build_demo_payload_structure():
    payload = demo_live_ingest.build_demo_payload(
        "Paris Montparnasse", "Bordeaux Saint-Jean", "2026-11-26", now=NOW
    )

    assert payload["source"] == "demo-live-ingest"
    assert payload["captured_at"] == NOW.isoformat()
    assert payload["summary"]["zero_offer_count"] == 2
    assert payload["summary"]["zero_day_count"] == 2

    watch = payload["watches"][0]
    assert watch["watch_date"] == "2026-11-26"
    assert [day["date"] for day in watch["zero_days"]] == ["2026-11-26", "2026-11-27"]
    assert len(watch["zero_offers"]) == 2
    for offer in watch["zero_offers"]:
        parsed = parse_travel_id(offer["travelId"])
        assert parsed is not None
        assert parsed["date"] == "2026-11-26"
    assert watch["history"][0]["type"] == "zero_day_added"


def test_build_demo_heartbeat():
    heartbeat = demo_live_ingest.build_demo_heartbeat(now=NOW, base_url="http://test")
    assert heartbeat["status"] == "ok"
    assert heartbeat["sncf_tab_ready"] is True
    assert heartbeat["backend_base_url"] == "http://test"


def test_demo_payload_flows_through_api(settings):
    client = TestClient(create_app(settings))
    payload = demo_live_ingest.build_demo_payload(
        "Paris", "Lyon Part Dieu", "2026-05-23", now=NOW
    )

    ingest = client.post("/api/live-watch/ingest", json=payload)
    assert ingest.status_code == 200
    assert ingest.json()["summary"]["zero_day_count"] == 2

    calendar = client.get("/api/live-watch/zero-calendar")
    assert calendar.status_code == 200
    assert calendar.json()["zero_calendar"][0]["zero_day_count"] == 2

    diff = client.get("/api/live-watch/zero-vs-dataset")
    assert diff.status_code == 200
    body = diff.json()
    assert body["summary"]["live_zero_offer_count"] == 2
    assert body["summary"][STATUS_MISSING] == 2
    assert body["routes"][0]["not_in_dataset_count"] == 2

    heartbeat = client.post("/api/live-worker/heartbeat", json=demo_live_ingest.build_demo_heartbeat(now=NOW))
    assert heartbeat.status_code == 200
    worker = client.get("/api/live-worker/latest")
    assert worker.json()["worker"]["status"] == "ok"

    page = client.get("/live-watch")
    assert page.status_code == 200
    assert "Surveillance live SNCF Connect" in page.text

    report = client.get("/api/live-watch/latest")
    assert report.json()["watches"][0]["zero_offers"][0]["travelId"] == "2026-05-23T06:23_999901"
