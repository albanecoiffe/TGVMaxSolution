from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_direct_endpoint_returns_results(settings):
    client = TestClient(create_app(settings))
    response = client.get("/api/direct", params={"origin": "Paris", "date": "2026-05-23"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["trip_count"] == 3
    assert any(item["destination"] == "LYON PART DIEU" for item in payload["trips"])
    assert "return_options" in payload["trips"][0]


def test_hybrid_endpoint_without_token_is_disabled(settings):
    client = TestClient(create_app(settings))
    response = client.get(
        "/api/routes/hybrid",
        params={
            "origin": "Paris",
            "date": "2026-05-23",
            "destination": "Chamonix-Mont-Blanc",
        },
    )
    assert response.status_code == 412
    assert response.json()["enabled"] is False


def test_section_pages_render(settings):
    client = TestClient(create_app(settings))
    routes = [
        ("/", "Trains a 0 EUR du jour"),
        ("/aller-retour-journee", "Aller-retour journee"),
        ("/correspondances-max", "Correspondances MAX"),
        ("/max-ter", "MAX + TER"),
    ]

    for path, title in routes:
        response = client.get(path)
        assert response.status_code == 200
        assert title in response.text
