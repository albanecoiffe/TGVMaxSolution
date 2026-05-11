from __future__ import annotations

from datetime import date, datetime


def test_direct_trips_find_all_zero_euro_trains(planner):
    payload = planner.direct_trips("Paris", date(2026, 5, 23))
    assert payload["trip_count"] == 4
    assert {item["destination"] for item in payload["trips"]} == {
        "LYON PART DIEU",
        "LILLE EUROPE",
        "STRASBOURG",
    }
    lyon_trip = next(item for item in payload["trips"] if item["destination"] == "LYON PART DIEU")
    assert (
        lyon_trip["booking_url"]
        == "https://www.sncf-connect.com/home/search?userInput=Paris%20-%20Lyon%20Part%20Dieu%2C%20aller-simple%2C%20Le%2023%20mai%2C%201%20voyageur"
    )
    assert lyon_trip["return_options"]["has_any"] is True
    assert lyon_trip["return_options"]["available_dates"][0]["date"] == "2026-05-23"
    lyon_destination = next(item for item in payload["destinations"] if item["destination"] == "LYON PART DIEU")
    assert lyon_destination["trip_count"] == 2


def test_direct_trips_can_filter_return_options_by_return_date(planner):
    payload = planner.direct_trips("Paris", date(2026, 5, 23), return_date=date(2026, 5, 24))
    lille_trip = next(item for item in payload["trips"] if item["destination"] == "LILLE EUROPE")
    assert lille_trip["return_options"]["requested_return_date"] == "2026-05-24"
    assert lille_trip["return_options"]["available_dates"][0]["date"] == "2026-05-24"
    assert lille_trip["return_options"]["available_dates"][0]["times"][0]["departure_time"] == "17:45"


def test_direct_trips_can_show_multiple_closest_return_dates(planner):
    payload = planner.direct_trips("Paris", date(2026, 5, 23), return_date=date(2026, 5, 24))
    lyon_trip = next(item for item in payload["trips"] if item["destination"] == "LYON PART DIEU")
    assert [group["date"] for group in lyon_trip["return_options"]["available_dates"][:2]] == [
        "2026-05-24",
        "2026-05-25",
    ]
    assert [slot["departure_time"] for slot in lyon_trip["return_options"]["available_dates"][0]["times"]] == [
        "18:00",
    ]


def test_direct_trips_hide_departures_already_passed_today(planner, monkeypatch):
    monkeypatch.setattr(planner, "_current_local_datetime", lambda: datetime(2026, 5, 23, 6, 30))
    payload = planner.direct_trips("Paris", date(2026, 5, 23))

    assert payload["trip_count"] == 3
    assert {item["destination"] for item in payload["trips"]} == {
        "LYON PART DIEU",
        "LILLE EUROPE",
        "STRASBOURG",
    }


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


def test_station_coordinates_can_fallback_to_commune_centroid(planner):
    bundle = planner.repository.get_bundle()
    paris_intramuros = planner._station_coordinates(bundle, "PARIS (intramuros)")
    lille_intramuros = planner._station_coordinates(bundle, "LILLE (intramuros)")

    assert paris_intramuros is not None
    assert round(paris_intramuros["latitude"], 4) == 48.8673
    assert round(paris_intramuros["longitude"], 4) == 2.3625
    assert lille_intramuros is not None
    assert round(lille_intramuros["latitude"], 4) == 50.6397
    assert round(lille_intramuros["longitude"], 4) == 3.0750

    for station in bundle.stations.values():
        station.commune = None

    paris_intramuros_by_name = planner._station_coordinates(bundle, "PARIS (intramuros)")
    lille_intramuros_by_name = planner._station_coordinates(bundle, "LILLE (intramuros)")
    assert paris_intramuros_by_name is not None
    assert lille_intramuros_by_name is not None


def test_station_coordinates_match_st_abbreviation(planner):
    bundle = planner.repository.get_bundle()

    bordeaux = planner._station_coordinates(bundle, "BORDEAUX ST JEAN")

    assert bordeaux is not None
    assert round(bordeaux["latitude"], 4) == 44.8253
    assert round(bordeaux["longitude"], 4) == -0.5562


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


def test_max_itineraries_can_limit_connection_wait_time(planner):
    payload = planner.max_itineraries(
        "Paris",
        date(2026, 5, 23),
        max_connections=2,
        min_connections=1,
        max_connection_minutes=30,
    )
    destinations = {item["destination"] for item in payload["results"]}
    assert "ANNECY" not in destinations
    assert "GRENOBLE" not in destinations


def test_max_itineraries_include_return_options(planner):
    payload = planner.max_itineraries(
        "Paris",
        date(2026, 5, 23),
        max_connections=2,
        min_connections=1,
    )
    annecy = next(item for item in payload["results"] if item["destination"] == "ANNECY")
    itinerary = annecy["itineraries"][0]
    assert itinerary["return_options"]["requested_return_date"] is None
    assert itinerary["return_options"]["has_any"] is True
    assert itinerary["return_options"]["available_dates"][0]["date"] == "2026-05-23"
    assert itinerary["return_options"]["available_dates"][0]["times"][0]["destination"] == "PARIS GARE DE LYON"


def test_hybrid_itineraries_can_use_open_gtfs_without_token(planner):
    payload = planner.hybrid_itineraries("Paris", date(2026, 5, 23))
    assert payload["enabled"] is True
    assert payload["results"]
    result = next(item for item in payload["results"] if item["destination"] == "CHAMONIX MONT BLANC")
    assert result["via_max_station"] == "LYON PART DIEU"
    assert result["ter_extension"]["departure_time"] == "08:30"
    assert result["ter_extension"]["arrival_time"] == "12:00"
    assert result["ter_extension"]["sections"][-1]["to"] == "CHAMONIX MONT BLANC"


def test_hybrid_itineraries_can_mark_destination_also_available_in_direct_max(planner):
    payload = planner.hybrid_itineraries("Lyon", date(2026, 5, 23))
    annecy = next(item for item in payload["results"] if item["destination"] == "ANNECY")
    assert annecy["direct_max_available"] is True
    assert annecy["direct_max_trip"]["origin"] == "LYON PART DIEU"
    assert annecy["direct_max_trip"]["destination"] == "ANNECY"


def test_hybrid_itineraries_can_limit_connection_wait_time(planner):
    payload = planner.hybrid_itineraries(
        "Paris",
        date(2026, 5, 23),
        max_connection_minutes=20,
    )
    assert payload["enabled"] is True
    assert payload["results"] == []
