from __future__ import annotations

from datetime import date


def test_direct_trips_find_all_zero_euro_trains(planner):
    payload = planner.direct_trips("Paris", date(2026, 5, 23))
    assert payload["trip_count"] == 3
    assert {item["destination"] for item in payload["trips"]} == {
        "LYON PART DIEU",
        "LILLE EUROPE",
        "STRASBOURG",
    }
    lyon_trip = next(item for item in payload["trips"] if item["destination"] == "LYON PART DIEU")
    assert lyon_trip["booking_url"] == "https://www.sncf-connect.com/train/horaires/paris/lyon"
    assert lyon_trip["return_options"]["has_any"] is True
    assert lyon_trip["return_options"]["available_dates"][0]["date"] == "2026-05-23"


def test_direct_trips_can_filter_return_options_by_return_date(planner):
    payload = planner.direct_trips("Paris", date(2026, 5, 23), return_date=date(2026, 5, 24))
    lille_trip = next(item for item in payload["trips"] if item["destination"] == "LILLE EUROPE")
    assert lille_trip["return_options"]["requested_return_date"] == "2026-05-24"
    assert lille_trip["return_options"]["available_dates"][0]["date"] == "2026-05-24"
    assert lille_trip["return_options"]["available_dates"][0]["times"][0]["departure_time"] == "17:45"


def test_day_trip_destinations_build_round_trip(planner):
    payload = planner.day_trip_destinations("Paris", date(2026, 5, 23), min_stay_minutes=120)
    destinations = {item["destination"] for item in payload["results"]}
    assert "LYON PART DIEU" in destinations
    lyon = next(item for item in payload["results"] if item["destination"] == "LYON PART DIEU")
    assert lyon["stay_minutes"] >= 540


def test_day_trip_destinations_support_later_return_date(planner):
    payload = planner.day_trip_destinations(
        "Paris",
        date(2026, 5, 23),
        return_date=date(2026, 5, 24),
        latest_return_time="23:30",
    )
    assert payload["return_date"] == "2026-05-24"
    destinations = {item["destination"] for item in payload["results"]}
    assert "LILLE EUROPE" in destinations


def test_max_itineraries_find_connection_to_annecy(planner):
    payload = planner.max_itineraries("Paris", date(2026, 5, 23), max_connections=2, min_connections=1)
    annecy = next(item for item in payload["results"] if item["destination"] == "ANNECY")
    itinerary = annecy["itineraries"][0]
    assert itinerary["connections"] == 1
    assert itinerary["segments"][0]["destination"] == "LYON PART DIEU"
    assert itinerary["segments"][1]["destination"] == "ANNECY"


def test_max_itineraries_can_exclude_direct_trips(planner):
    payload = planner.max_itineraries("Paris", date(2026, 5, 23), max_connections=2, min_connections=1)
    destinations = {item["destination"] for item in payload["results"]}
    assert "LILLE EUROPE" not in destinations
    assert "STRASBOURG" not in destinations
