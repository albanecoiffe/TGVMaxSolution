from __future__ import annotations

import json
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.main import create_app
from app.config import Settings
from tests.conftest import TGVMAX_SAMPLE


def test_direct_endpoint_returns_results(settings):
    client = TestClient(create_app(settings))
    response = client.get("/api/direct", params={"origin": "Paris", "date": "2026-05-23"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["trip_count"] == 4
    assert any(item["destination"] == "LYON PART DIEU" for item in payload["trips"])
    assert "return_options" in payload["trips"][0]


def test_direct_endpoint_keeps_requested_return_date(settings):
    client = TestClient(create_app(settings))
    response = client.get(
        "/api/direct",
        params={"origin": "Paris", "date": "2026-05-23", "return_date": "2026-05-24"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["return_date"] == "2026-05-24"
    lille_trip = next(item for item in payload["trips"] if item["destination"] == "LILLE EUROPE")
    assert lille_trip["return_options"]["requested_return_date"] == "2026-05-24"
    assert lille_trip["return_options"]["available_dates"][0]["date"] == "2026-05-24"


def test_hybrid_endpoint_can_use_open_gtfs_without_token(settings):
    client = TestClient(create_app(settings))
    response = client.get(
        "/api/routes/hybrid",
        params={"origin": "Paris", "date": "2026-05-23"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    result = next(item for item in payload["results"] if item["destination"] == "CHAMONIX MONT BLANC")
    assert result["via_max_station"] == "LYON PART DIEU"


def test_routes_max_endpoint_keeps_requested_return_date(settings):
    client = TestClient(create_app(settings))
    response = client.get(
        "/api/routes/max",
        params={"origin": "Paris", "date": "2026-05-23", "return_date": "2026-05-24"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["return_date"] == "2026-05-24"
    annecy = next(item for item in payload["results"] if item["destination"] == "ANNECY")
    assert annecy["itineraries"][0]["return_options"]["requested_return_date"] == "2026-05-24"


def test_hybrid_endpoint_accepts_max_connection_minutes(settings):
    client = TestClient(create_app(settings))
    response = client.get(
        "/api/routes/hybrid",
        params={"origin": "Paris", "date": "2026-05-23", "max_connection_minutes": "20"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["results"] == []


def test_hybrid_endpoint_is_disabled_without_token_or_open_gtfs(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = data_dir / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "tgvmax.csv").write_text(
        "date,origine,destination,heure_depart,heure_arrivee,od_happy_card\n",
        encoding="utf-8",
    )
    (cache_dir / "gares-de-voyageurs.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": []}),
        encoding="utf-8",
    )
    with ZipFile(cache_dir / "sncf-gtfs.zip", "w"):
        pass
    (data_dir / "mountains.json").write_text("[]", encoding="utf-8")
    settings = Settings(
        data_dir=data_dir,
        refresh_hours=9999,
        tgvmax_url="https://example.com/tgvmax.csv",
        stations_url="https://example.com/stations.geojson",
        sncf_gtfs_url="https://example.com/sncf-gtfs.zip",
    )
    client = TestClient(create_app(settings))
    response = client.get(
        "/api/routes/hybrid",
        params={"origin": "Paris", "date": "2026-05-23"},
    )
    assert response.status_code == 412
    assert response.json()["enabled"] is False


class FakeLiveVerifier:
    def verify_trips(self, trips, limit=None):
        return {
            "verified_count": len(trips),
            "limit": limit or len(trips),
            "cache_minutes": 10,
            "results": [
                {
                    "trip_id": trip["id"],
                    "booking_url": trip["booking_url"],
                    "checked_at": "2026-05-10T07:00:00",
                    "status": "blocked",
                    "label": "Bloque par le site",
                    "reason": "anti-bot",
                    "source": "sncf_connect_html",
                }
                for trip in trips
            ],
            "summary": {
                "confirmed_zero": 0,
                "unavailable": 0,
                "blocked": len(trips),
                "unknown": 0,
                "error": 0,
            },
        }


def test_direct_live_endpoint_returns_live_statuses(settings):
    client = TestClient(create_app(settings, live_verifier=FakeLiveVerifier()))
    response = client.post(
        "/api/direct/live",
        json={
            "limit": 2,
            "trips": [
                {
                    "id": "trip-1",
                    "booking_url": "https://www.sncf-connect.com/home/search?userInput=test",
                }
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["verified_count"] == 1
    assert payload["results"][0]["status"] == "blocked"


def test_section_pages_render(settings):
    client = TestClient(create_app(settings))
    routes = [
        ("/", "Dataset SNCF puis verification live"),
        ("/aller-retour-journee", "Aller-retour journee"),
        ("/correspondances-max", "Correspondances MAX"),
        ("/max-ter", "MAX + TER"),
    ]

    for path, title in routes:
        response = client.get(path)
        assert response.status_code == 200
        assert title in response.text


def test_connection_max_field_only_renders_on_connection_pages(settings):
    client = TestClient(create_app(settings))

    direct_response = client.get("/")
    assert "Correspondance max" not in direct_response.text

    routes_response = client.get("/correspondances-max")
    assert "Correspondance max" in routes_response.text

    hybrid_response = client.get("/max-ter")
    assert "Correspondance max" in hybrid_response.text


def test_refresh_endpoint_returns_zero_watch_diff_and_latest_watch(settings):
    client = TestClient(create_app(settings))

    first_refresh = client.post("/api/refresh")
    assert first_refresh.status_code == 200
    first_payload = first_refresh.json()
    assert first_payload["zero_watch"]["initialized"] is True
    assert first_payload["zero_watch"]["current_zero_count"] == 14

    updated_sample = TGVMAX_SAMPLE.replace(
        "2026-05-23,6615,PARSTR,EST,FPEST,FRSXB,PARIS EST,STRASBOURG,06:45,08:40,OUI\n",
        "",
    ) + "2026-05-25,6653,PARBDX,ATL,FPAZ,FBSJ,PARIS MONTPARNASSE,BORDEAUX ST JEAN,10:15,12:20,OUI\n"
    settings.tgvmax_cache_file.write_text(updated_sample, encoding="utf-8")

    second_refresh = client.post("/api/refresh")
    assert second_refresh.status_code == 200
    second_payload = second_refresh.json()
    assert second_payload["zero_watch"]["new_zero_count"] == 1
    assert second_payload["zero_watch"]["removed_zero_count"] == 1

    latest_watch = client.get("/api/watch/latest")
    assert latest_watch.status_code == 200
    latest_payload = latest_watch.json()
    assert latest_payload["new_zero_count"] == 1
    assert latest_payload["removed_zero_count"] == 1
