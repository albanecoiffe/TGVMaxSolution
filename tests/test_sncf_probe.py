from __future__ import annotations

import json

from app.services.sncf_probe import (
    extract_zero_days,
    extract_zero_travel_ids,
    is_zero_price_label,
    redact_sensitive_data,
    summarize_probe_file,
)


PROBE_SAMPLE = [
    {
        "url": "https://www.sncf-connect.com/bff/api/v1/itineraries",
        "tabUrl": "https://www.sncf-connect.com/home/shop/results/outward",
        "requestHeaders": {
            "x-bff-key": "secret",
            "x-nav-current-path": "/home/shop/results/outward",
        },
        "requestBodyPreview": json.dumps(
            {
                "schedule": {"outward": {"date": "2026-05-16T04:00:00.000Z"}},
                "mainJourney": {
                    "origin": {"label": "Paris Montparnasse"},
                    "destination": {"label": "Bordeaux Saint-Jean"},
                },
                "passengers": [
                    {
                        "discountCards": [{"code": "TGV_MAX"}],
                    }
                ],
                "branch": "SHOP",
                "itineraryId": "itinerary-1",
            }
        ),
        "bodyPreview": json.dumps(
            {
                "longDistance": {
                    "proposals": {
                        "bestPrices": [
                            {
                                "label": "Sam 16",
                                "priceLabel": "0\u00a0€",
                                "bestPriceDateTime": "2026-05-16T06:23:00",
                            },
                            {
                                "label": "Dim 17",
                                "priceLabel": "60\u00a0€",
                                "bestPriceDateTime": "2026-05-17T21:38:00",
                            },
                        ],
                        "proposals": [
                            {
                                "id": "proposal-1",
                                "travelId": "travel-1",
                                "departure": {
                                    "originStationLabel": "PARIS - MONTPARNASSE",
                                    "timeLabel": "06:23",
                                },
                                "arrival": {
                                    "destinationStationLabel": "Bordeaux Saint-Jean",
                                    "timeLabel": "09:30",
                                },
                                "bestPriceLabel": "0\u00a0€",
                                "secondComfortClassOffers": {
                                    "offers": [
                                        {
                                            "priceLabel": "0\u00a0€",
                                            "header": {
                                                "title": "2de classe",
                                                "subtitle": "Tarif Max Jeune",
                                            },
                                            "travelersFares": [
                                                {
                                                    "segmentFares": [
                                                        {"fareName": "Tarif MAX JEUNE"}
                                                    ]
                                                }
                                            ],
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                }
            }
        ),
    }
]


def test_redact_sensitive_data_masks_known_fields():
    payload = {
        "accessToken": "secret-token",
        "requestHeaders": {
            "x-bff-key": "secret-key",
            "x-nav-current-path": "/home/shop/results/outward",
        },
    }

    redacted = redact_sensitive_data(payload)

    assert redacted["accessToken"] == "[redacted]"
    assert redacted["requestHeaders"]["x-bff-key"] == "[redacted]"
    assert redacted["requestHeaders"]["x-nav-current-path"] == "/home/shop/results/outward"


def test_summarize_probe_file_extracts_zero_max_offers(tmp_path):
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(PROBE_SAMPLE), encoding="utf-8")

    summary = summarize_probe_file(path)

    assert summary["event_count"] == 1
    assert summary["itinerary_event_count"] == 1
    itinerary = summary["itinerary_summaries"][0]
    assert itinerary["request"]["origin"] == "Paris Montparnasse"
    assert itinerary["request"]["destination"] == "Bordeaux Saint-Jean"
    assert itinerary["request"]["has_tgvmax_card"] is True
    assert itinerary["response"]["zero_best_price_days"] == 1
    assert itinerary["response"]["zero_offer_count"] == 1
    assert itinerary["response"]["fare_names"] == ["Tarif MAX JEUNE"]
    assert itinerary["response"]["zero_days"] == [
        {"date": "2026-05-16", "label": "Sam 16", "best_price_datetime": "2026-05-16T06:23:00"}
    ]
    assert itinerary["response"]["zero_travel_ids"] == ["travel-1"]
    assert itinerary["response"]["zero_offers"][0]["price_label"] == "0\u00a0€"


NBSP = chr(0xA0)
EURO = chr(0x20AC)


def test_is_zero_price_label_accepts_nbsp_variants():
    assert is_zero_price_label("0" + NBSP + EURO) is True
    assert is_zero_price_label("0 " + EURO) is True
    assert is_zero_price_label("0" + EURO) is True
    assert is_zero_price_label("0\\u00a0\\u20ac") is True
    assert is_zero_price_label("60" + NBSP + EURO) is False
    assert is_zero_price_label(None) is False


def test_extract_zero_days_merges_and_sorts_by_date():
    best_prices = [
        {"label": "Dim 17", "priceLabel": "60" + NBSP + EURO, "bestPriceDateTime": "2026-05-17T21:38:00"},
        {"label": "Sam 16", "price_label": "0" + NBSP + EURO, "best_price_datetime": "2026-05-16T06:23:00"},
        {"label": "Lun 18", "priceLabel": "0" + NBSP + EURO, "bestPriceDateTime": "2026-05-18T07:00:00"},
        {"label": "Lun 18 bis", "priceLabel": "0" + NBSP + EURO, "bestPriceDateTime": "2026-05-18T09:00:00"},
        {"label": "Sans date", "priceLabel": "0" + NBSP + EURO, "bestPriceDateTime": None},
    ]

    zero_days = extract_zero_days(best_prices)

    assert [day["date"] for day in zero_days] == ["2026-05-16", "2026-05-18"]
    assert zero_days[1]["label"] == "Lun 18"


def test_extract_zero_travel_ids_deduplicates():
    offers = [
        {"travelId": "travel-1"},
        {"travel_id": "travel-2"},
        {"travelId": "travel-1"},
        {"travelId": None},
        "not-a-dict",
    ]

    assert extract_zero_travel_ids(offers) == ["travel-1", "travel-2"]
