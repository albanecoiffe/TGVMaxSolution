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
    assert result["ter_extension"]["price"] is None
    assert result["ter_extension"]["price_status"] == "unavailable"
    assert result["ter_extension"]["booking_url"].startswith("https://www.sncf-connect.com/home/search?userInput=")
    assert result["ter_extension"]["sections"][0]["booking_url"].startswith(
        "https://www.sncf-connect.com/home/search?userInput="
    )


def test_hybrid_endpoint_returns_ter_price_when_navitia_is_enabled(settings, monkeypatch):
    settings.sncf_api_token = "test-token"
    monkeypatch.setattr(
        "app.services.navitia.NavitiaClient.plan_from_station",
        lambda *args, **kwargs: {
            "price": {
                "amount": "19.50",
                "currency": "EUR",
                "label": "19,50 EUR",
            }
        },
    )
    client = TestClient(create_app(settings))

    response = client.get(
        "/api/routes/hybrid",
        params={"origin": "Paris", "date": "2026-05-23"},
    )

    assert response.status_code == 200
    payload = response.json()
    result = next(item for item in payload["results"] if item["destination"] == "CHAMONIX MONT BLANC")
    assert result["ter_extension"]["price"]["label"] == "19,50 EUR"
    assert result["ter_extension"]["price_label"] == "19,50 EUR"
    assert result["ter_extension"]["price_status"] == "available"


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


def test_section_pages_render(settings):
    client = TestClient(create_app(settings))
    routes = [
        ("/", "Dataset SNCF tgvmax"),
        ("/aller-retour-journee", "Aller-retour journee"),
        ("/correspondances-max", "Correspondances MAX"),
        ("/max-ter", "MAX + TER"),
        ("/live-watch", "Surveillance live SNCF Connect"),
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


def test_live_watch_ingest_and_latest(settings):
    client = TestClient(create_app(settings))

    empty_response = client.get("/api/live-watch/latest")
    assert empty_response.status_code == 200
    assert empty_response.json()["has_live_watch"] is False

    payload = {
        "source": "sncf-probe-extension",
        "captured_at": "2026-05-15T08:50:00Z",
        "summary": {
            "watch_count": 2,
            "ok_count": 1,
            "error_count": 1,
            "waiting_count": 0,
            "zero_watch_count": 1,
            "zero_offer_count": 2,
        },
        "watches": [
            {
                "id": "Paris|Bordeaux|2026-05-23",
                "origin_label": "Paris Montparnasse",
                "destination_label": "Bordeaux Saint-Jean",
                "watch_date": "2026-05-23",
                "status": "ok",
                "zero_offer_count": 2,
                "check_count": 4,
                "success_count": 4,
                "last_checked_at": "2026-05-15T08:49:00Z",
                "last_success_at": "2026-05-15T08:49:00Z",
                "last_alert_at": "2026-05-15T08:40:00Z",
                "last_error": None,
                "zero_offers": [
                    {"travelId": "A"},
                    {"travelId": "B"},
                ],
                "history": [
                    {"type": "zero_added", "at": "2026-05-15T08:40:00Z", "count": 2},
                    {"type": "check_ok", "at": "2026-05-15T08:49:00Z", "zeroOfferCount": 2},
                ],
            },
            {
                "id": "Paris|Bordeaux|2026-05-30",
                "origin_label": "Paris Montparnasse",
                "destination_label": "Bordeaux Saint-Jean",
                "watch_date": "2026-05-30",
                "status": "error",
                "zero_offer_count": 0,
                "check_count": 2,
                "success_count": 1,
                "last_checked_at": "2026-05-15T08:49:00Z",
                "last_success_at": "2026-05-15T08:20:00Z",
                "last_alert_at": None,
                "last_error": "Replay impossible",
                "zero_offers": [],
                "history": [
                    {"type": "check_error", "at": "2026-05-15T08:49:00Z", "error": "Replay impossible"},
                ],
            },
        ],
    }

    ingest_response = client.post("/api/live-watch/ingest", json=payload)
    assert ingest_response.status_code == 200
    ingest_payload = ingest_response.json()
    assert ingest_payload["has_live_watch"] is True
    assert ingest_payload["summary"]["watch_count"] == 2
    assert len(ingest_payload["recent_activity"]) == 3

    latest_response = client.get("/api/live-watch/latest")
    assert latest_response.status_code == 200
    latest_payload = latest_response.json()
    assert latest_payload["has_live_watch"] is True
    assert latest_payload["summary"]["zero_offer_count"] == 2
    assert latest_payload["recent_activity"][0]["type"] == "check_ok"


def test_live_watch_default_weekend_plan_and_clear(settings):
    client = TestClient(create_app(settings))

    empty_plan = client.get("/api/live-watch/plan")
    assert empty_plan.status_code == 200
    assert empty_plan.json()["has_plan"] is False

    create_plan = client.post("/api/live-watch/plan/default-weekend-bordeaux-paris")
    assert create_plan.status_code == 200
    plan_payload = create_plan.json()
    assert plan_payload["has_plan"] is True
    assert plan_payload["watch_count"] > 0
    assert any(item["destination_label"] == "Bordeaux Saint-Jean" for item in plan_payload["watches"])
    assert any(item["destination_label"] == "Paris Montparnasse" for item in plan_payload["watches"])

    latest_plan = client.get("/api/live-watch/plan")
    assert latest_plan.status_code == 200
    assert latest_plan.json()["has_plan"] is True

    clear_plan = client.post("/api/live-watch/plan/clear")
    assert clear_plan.status_code == 200
    assert clear_plan.json()["has_plan"] is False


def test_live_worker_heartbeat_and_latest(settings):
    client = TestClient(create_app(settings))

    empty_worker = client.get("/api/live-worker/latest")
    assert empty_worker.status_code == 200
    assert empty_worker.json()["has_worker"] is False

    heartbeat = {
        "captured_at": "2026-05-15T09:30:00Z",
        "backend_base_url": "https://max-explorer.onrender.com",
        "status": "ok",
        "watch_tab_url": "https://www.sncf-connect.com/home/search",
        "watch_tab_id": 123,
        "watch_count": 19,
        "browser_open": True,
        "sncf_tab_ready": True,
        "last_error": None,
        "session_hint": "session_sncf_active",
    }

    heartbeat_response = client.post("/api/live-worker/heartbeat", json=heartbeat)
    assert heartbeat_response.status_code == 200
    payload = heartbeat_response.json()
    assert payload["has_worker"] is True
    assert payload["worker"]["status"] == "ok"
    assert payload["backend_base_url"] == "https://max-explorer.onrender.com"

    latest_worker = client.get("/api/live-worker/latest")
    assert latest_worker.status_code == 200
    latest_payload = latest_worker.json()
    assert latest_payload["worker"]["watch_count"] == 19


def test_direct_endpoint_is_cached_until_refresh(settings, monkeypatch):
    app = create_app(settings)
    client = TestClient(app)
    planner = app.state.planner

    original = planner.direct_trips
    call_count = {"value": 0}

    def counted_direct_trips(*args, **kwargs):
        call_count["value"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(planner, "direct_trips", counted_direct_trips)

    params = {"origin": "Paris", "date": "2026-05-23"}
    first = client.get("/api/direct", params=params)
    second = client.get("/api/direct", params=params)

    assert first.status_code == 200
    assert second.status_code == 200
    assert call_count["value"] == 1

    refresh = client.post("/api/refresh")
    assert refresh.status_code == 200

    third = client.get("/api/direct", params=params)
    assert third.status_code == 200
    assert call_count["value"] == 2
