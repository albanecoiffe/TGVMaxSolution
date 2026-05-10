from __future__ import annotations

from app.services.live_availability import LiveAvailabilityVerifier


def test_live_verifier_detects_blocked_page(settings):
    verifier = LiveAvailabilityVerifier(settings, fetcher=lambda _: "<html>Please enable JS and disable any ad blocker<script src='https://ct.captcha-delivery.com/c.js'></script></html>")
    payload = verifier.verify_trips([{"id": "trip-1", "booking_url": "https://example.com"}], limit=1)

    assert payload["results"][0]["status"] == "blocked"
    assert payload["summary"]["blocked"] == 1


def test_live_verifier_detects_confirmed_zero(settings):
    verifier = LiveAvailabilityVerifier(settings, fetcher=lambda _: "<html><body>Prix a partir de 0 € pour ce trajet</body></html>")
    payload = verifier.verify_trips([{"id": "trip-1", "booking_url": "https://example.com"}], limit=1)

    assert payload["results"][0]["status"] == "confirmed_zero"
    assert payload["summary"]["confirmed_zero"] == 1


def test_live_verifier_detects_unavailable(settings):
    verifier = LiveAvailabilityVerifier(settings, fetcher=lambda _: "<html><body>Complet - aucun trajet disponible</body></html>")
    payload = verifier.verify_trips([{"id": "trip-1", "booking_url": "https://example.com"}], limit=1)

    assert payload["results"][0]["status"] == "unavailable"
    assert payload["summary"]["unavailable"] == 1
