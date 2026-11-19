from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.zero_release import ZeroReleaseStore


def _watch_payload() -> dict:
    return {
        "source": "sncf-probe-extension",
        "captured_at": "2026-05-05T06:00:00Z",
        "summary": {"watch_count": 4},
        "watches": [
            {
                "id": "Paris|Bordeaux|2026-05-22",
                "origin_label": "Paris Montparnasse",
                "destination_label": "Bordeaux Saint-Jean",
                "watch_date": "2026-05-22",
                "status": "ok",
                "zero_offers": [
                    {"travelId": "A", "departureTime": "18:03"},
                    {"travelId": "B", "departureTime": "19:40"},
                    {"travelId": "F", "departureTime": "06:00"},
                ],
                "history": [
                    {"type": "zero_added", "at": "2026-04-22T05:12:00Z", "count": 3, "travelIds": ["A", "B", "F"]},
                    {"type": "check_ok", "at": "2026-04-22T05:20:00Z", "zeroOfferCount": 3},
                ],
            },
            {
                "id": "Paris|Bordeaux|2026-05-15",
                "origin_label": "Paris Montparnasse",
                "destination_label": "Bordeaux Saint-Jean",
                "watch_date": "2026-05-15",
                "status": "ok",
                "zero_offers": [{"travelId": "C", "departureTime": "18:30"}],
                "history": [
                    {"type": "zero_added", "at": "2026-04-15T05:30:00Z", "count": 1, "travelIds": ["C"]},
                    {"type": "check_ok", "at": "2026-04-15T05:40:00Z", "zeroOfferCount": 1},
                ],
            },
            {
                "id": "Paris|Bordeaux|2026-05-29",
                "origin_label": "Paris Montparnasse",
                "destination_label": "Bordeaux Saint-Jean",
                "watch_date": "2026-05-29",
                "status": "ok",
                "zero_offers": [{"travelId": "D", "departureTime": "20:00"}],
                "history": [
                    {"type": "zero_added", "at": "2026-05-04T16:00:00Z", "count": 1, "travelIds": ["D"]},
                    {"type": "check_ok", "at": "2026-05-04T16:10:00Z", "zeroOfferCount": 1},
                ],
            },
            {
                "id": "Paris|Bordeaux|2026-05-23",
                "origin_label": "Paris Montparnasse",
                "destination_label": "Bordeaux Saint-Jean",
                "watch_date": "2026-05-23",
                "status": "ok",
                "zero_offers": [{"travelId": "E", "departureTime": "18:00"}],
                "history": [
                    {"type": "zero_added", "at": "2026-04-23T05:00:00Z", "count": 1, "travelIds": ["E"]},
                    {"type": "check_ok", "at": "2026-04-23T05:10:00Z", "zeroOfferCount": 1},
                ],
            },
        ],
    }


def test_record_live_watch_extracts_releases_and_observations(settings):
    store = ZeroReleaseStore(settings)
    result = store.record_live_watch(_watch_payload())
    assert result["recorded"] == 10

    events = store.events(limit=100)
    releases = [item for item in events if item["kind"] == "release"]
    observations = [item for item in events if item["kind"] == "observation"]
    assert len(releases) == 6
    assert len(observations) == 4
    by_departure = {item["departure_time"]: item for item in releases}
    assert set(by_departure) == {"18:03", "19:40", "06:00", "18:30", "20:00", "18:00"}
    assert by_departure["18:03"]["first_seen_at"] == "2026-04-22T05:12:00Z"
    assert by_departure["18:03"]["source"] == "live_watch"

    again = store.record_live_watch(_watch_payload())
    assert again["recorded"] == 0


def test_record_live_watch_keeps_earliest_first_seen(settings):
    store = ZeroReleaseStore(settings)
    store.record_live_watch(_watch_payload())
    later = _watch_payload()
    later["watches"][0]["history"] = [
        {"type": "zero_added", "at": "2026-04-25T05:12:00Z", "count": 1, "travelIds": ["A"]}
    ]
    result = store.record_live_watch(later)
    assert result["recorded"] == 0
    events = store.events(limit=100)
    offer_a = next(item for item in events if item["kind"] == "release" and item["departure_time"] == "18:03")
    assert offer_a["first_seen_at"] == "2026-04-22T05:12:00Z"


def test_record_snapshot_releases(settings):
    store = ZeroReleaseStore(settings)
    diff = {
        "captured_at": "2026-05-05T04:30:00+02:00",
        "new_trips": [
            {
                "date": "2026-05-29",
                "origin": "PARIS GARE DE LYON",
                "destination": "LYON PART DIEU",
                "departure_time": "18:00",
                "arrival_time": "20:00",
                "train_no": "6627",
            }
        ],
    }
    result = store.record_snapshot_releases(diff)
    assert result["recorded"] == 1
    events = store.events(limit=10)
    assert events[0]["kind"] == "release"
    assert events[0]["source"] == "snapshot"
    assert events[0]["train_no"] == "6627"


def test_estimate_computes_distribution_and_recent_events(settings):
    store = ZeroReleaseStore(settings)
    store.record_live_watch(_watch_payload())

    payload = store.estimate(
        travel_date=date(2026, 5, 29),
        slot_start="18:00",
        slot_end="21:00",
    )
    assert payload["has_data"] is True
    assert payload["travel_weekday_label"] == "vendredi"
    assert payload["sample_size"] == 4

    weekday_hour = {item["label"]: item for item in payload["distribution_by_weekday_hour"]}
    assert weekday_hour["mercredi 7h"]["count"] == 3
    assert weekday_hour["mercredi 7h"]["percent"] == 75.0
    assert weekday_hour["lundi 18h"]["percent"] == 25.0

    by_delay = {item["label"]: item for item in payload["distribution_by_delay"]}
    assert by_delay["J-30"]["count"] == 3
    assert by_delay["J-25"]["count"] == 1

    most_probable = payload["most_probable_release"]
    assert most_probable["label"] == "J-30, mercredi vers 7h"
    assert most_probable["percent"] == 75.0
    assert most_probable["expected_release_at"].startswith("2026-04-29T07:00:00")

    availability = payload["availability"]
    assert availability["observed_dates"] == 3
    assert availability["dates_with_release"] == 3
    assert availability["rate_percent"] == 100.0

    recent = payload["recent_events"]
    assert len(recent) == 4
    assert all(item["release_weekday_label"] for item in recent)


def test_estimate_filters_slot_and_weekday(settings):
    store = ZeroReleaseStore(settings)
    store.record_live_watch(_watch_payload())

    narrow = store.estimate(
        travel_date=date(2026, 5, 29),
        slot_start="19:00",
        slot_end="21:00",
    )
    assert narrow["sample_size"] == 2

    all_weekdays = store.estimate(
        travel_date=date(2026, 5, 29),
        slot_start="18:00",
        slot_end="21:00",
        weekday_only=False,
    )
    assert all_weekdays["sample_size"] == 5

    by_route = store.estimate(
        travel_date=date(2026, 5, 29),
        slot_start="18:00",
        slot_end="21:00",
        destination="Bordeaux",
    )
    assert by_route["sample_size"] == 4
    other_route = store.estimate(
        travel_date=date(2026, 5, 29),
        slot_start="18:00",
        slot_end="21:00",
        destination="Lyon",
    )
    assert other_route["has_data"] is False


def test_zero_release_estimate_endpoint_and_page(settings):
    client = TestClient(create_app(settings))

    page_response = client.get("/estimation-train-0")
    assert page_response.status_code == 200
    assert "Estimation train 0" in page_response.text
    assert 'id="slot-start-input"' in page_response.text
    assert 'id="destination-input"' in page_response.text

    ingest_response = client.post("/api/live-watch/ingest", json=_watch_payload())
    assert ingest_response.status_code == 200
    assert ingest_response.json()["zero_release"]["recorded"] == 10

    estimate_response = client.get(
        "/api/zero-release/estimate",
        params={"date": "2026-05-29", "slot_start": "18:00", "slot_end": "21:00"},
    )
    assert estimate_response.status_code == 200
    payload = estimate_response.json()
    assert payload["has_data"] is True
    assert payload["sample_size"] == 4
    assert payload["most_probable_release"]["percent"] == 75.0

    events_response = client.get("/api/zero-release/events", params={"limit": 5})
    assert events_response.status_code == 200
    assert len(events_response.json()["events"]) == 5


def test_refresh_records_snapshot_releases(settings):
    client = TestClient(create_app(settings))
    response = client.post("/api/refresh")
    assert response.status_code == 200
    payload = response.json()
    assert payload["zero_release"]["recorded"] == 14

    estimate_response = client.get(
        "/api/zero-release/estimate",
        params={"date": "2026-05-23", "slot_start": "00:00", "slot_end": "23:59", "weekday_only": "false"},
    )
    assert estimate_response.status_code == 200
    estimate = estimate_response.json()
    assert estimate["has_data"] is True
    assert estimate["sample_size"] == 14
    assert estimate["source_counts"]["snapshot"] == 14
