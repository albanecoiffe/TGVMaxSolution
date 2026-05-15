from __future__ import annotations

import json

from app.services.sncf_replay import (
    build_replay_template,
    summarize_replay_response,
    update_template_trip,
)


PROBE_SAMPLE = [
    {
        "url": "https://www.sncf-connect.com/bff/api/v1/itineraries",
        "requestHeaders": {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-bff-key": "secret",
            "x-nav-current-path": "/home/shop/results/outward",
            "x-extra-ignored": "ignored",
        },
        "requestBodyPreview": json.dumps(
            {
                "schedule": {"outward": {"date": "2026-05-16T04:00:00.000Z"}},
                "mainJourney": {
                    "origin": {"id": "RESARAIL_STA_1", "label": "Paris Montparnasse"},
                    "destination": {"id": "RESARAIL_STA_2", "label": "Bordeaux Saint-Jean"},
                },
                "passengers": [{"discountCards": [{"code": "TGV_MAX"}]}],
                "branch": "SHOP",
                "itineraryId": "itinerary-1",
            }
        ),
    }
]


def test_build_replay_template_keeps_expected_headers_and_body(tmp_path):
    probe_path = tmp_path / "probe.json"
    probe_path.write_text(json.dumps(PROBE_SAMPLE), encoding="utf-8")

    template = build_replay_template(probe_path)

    assert template.url.endswith("/bff/api/v1/itineraries")
    assert template.headers["x-bff-key"] == "secret"
    assert "x-extra-ignored" not in template.headers
    assert template.body["mainJourney"]["origin"]["label"] == "Paris Montparnasse"


def test_update_template_trip_overrides_trip_fields(tmp_path):
    probe_path = tmp_path / "probe.json"
    probe_path.write_text(json.dumps(PROBE_SAMPLE), encoding="utf-8")
    template = build_replay_template(probe_path)

    updated = update_template_trip(
        template,
        destination_label="Lyon Part Dieu",
        destination_id="RESARAIL_STA_3",
        outward_datetime_iso="2026-05-18T15:38:00.000Z",
    )

    assert updated.body["mainJourney"]["destination"]["label"] == "Lyon Part Dieu"
    assert updated.body["mainJourney"]["destination"]["id"] == "RESARAIL_STA_3"
    assert updated.body["schedule"]["outward"]["date"] == "2026-05-18T15:38:00.000Z"


def test_summarize_replay_response_extracts_zero_day():
    template = type(
        "Template",
        (),
        {
            "headers": {"x-nav-current-path": "/home/shop/results/outward"},
            "body": {
                "schedule": {"outward": {"date": "2026-05-18T15:38:00.000Z"}},
                "mainJourney": {
                    "origin": {"label": "Paris Montparnasse"},
                    "destination": {"label": "Bordeaux Saint-Jean"},
                },
                "passengers": [{"discountCards": [{"code": "TGV_MAX"}]}],
                "branch": "SHOP",
                "itineraryId": "itinerary-1",
            },
        },
    )()
    response_payload = {
        "longDistance": {
            "proposals": {
                "bestPrices": [
                    {
                        "label": "Lun 18",
                        "priceLabel": "0 €",
                        "bestPriceDateTime": "2026-05-18T17:38:00",
                    }
                ],
                "proposals": [],
            }
        }
    }

    summary = summarize_replay_response(template, response_payload)

    assert summary["request"]["branch"] == "SHOP"
    assert summary["response"]["zero_best_price_days"] == 1

