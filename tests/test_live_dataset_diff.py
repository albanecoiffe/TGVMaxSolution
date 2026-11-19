from __future__ import annotations

from app.services.live_dataset_diff import (
    STATUS_MISSING,
    STATUS_PRESENT_NOT_ZERO,
    STATUS_ZERO,
    diff_live_against_dataset,
    load_tgvmax_csv,
    parse_travel_id,
)


def test_parse_travel_id_extracts_date_time_train():
    assert parse_travel_id("2026-05-23T06:00_6611") == {
        "date": "2026-05-23",
        "time": "06:00",
        "train_no": "6611",
    }
    assert parse_travel_id("2026-12-01T06:20:00.000Z_6641") == {
        "date": "2026-12-01",
        "time": "06:20",
        "train_no": "6641",
    }
    assert parse_travel_id("not-a-travel-id") is None
    assert parse_travel_id(None) is None
    assert parse_travel_id(123) is None


def _live_payload() -> dict:
    return {
        "has_live_watch": True,
        "captured_at": "2026-05-15T09:00:00Z",
        "watches": [
            {
                "id": "Paris|Lyon|2026-05-23",
                "origin_label": "Paris",
                "destination_label": "Lyon Part Dieu",
                "watch_date": "2026-05-23",
                "zero_offers": [
                    {
                        "travelId": "2026-05-23T06:00_6611",
                        "departureTime": "06:00",
                        "arrivalTime": "08:00",
                        "origin": "PARIS GARE DE LYON",
                        "destination": "LYON PART DIEU",
                        "fareNames": ["Tarif MAX JEUNE"],
                    },
                    {
                        "travelId": "2026-05-24T06:00_6641",
                        "departureTime": "06:00",
                        "arrivalTime": "08:00",
                        "origin": "PARIS GARE DE LYON",
                        "destination": "LYON PART DIEU",
                        "fareNames": ["Tarif MAX JEUNE"],
                    },
                    {
                        "travelId": "2026-05-23T10:15_6699",
                        "departureTime": "10:15",
                        "arrivalTime": "12:15",
                        "origin": "PARIS GARE DE LYON",
                        "destination": "LYON PART DIEU",
                        "fareNames": ["Tarif MAX JEUNE"],
                    },
                    {
                        "travelId": None,
                        "departureTime": "06:00",
                        "arrivalTime": "08:00",
                        "origin": "Paris Gare de Lyon",
                        "destination": "Lyon Part Dieu",
                        "fareNames": [],
                    },
                ],
            }
        ],
    }


def test_diff_classifies_offers_against_dataset(planner):
    trips = planner.repository.get_bundle().trips
    result = diff_live_against_dataset(_live_payload(), trips)

    assert result["has_live_watch"] is True
    assert result["summary"]["live_zero_offer_count"] == 4
    assert result["summary"][STATUS_ZERO] == 2
    assert result["summary"][STATUS_PRESENT_NOT_ZERO] == 1
    assert result["summary"][STATUS_MISSING] == 1

    route = result["routes"][0]
    assert route["zero_offer_count"] == 4
    assert route["not_in_dataset_count"] == 1
    assert route["not_in_dataset"][0]["travel_id"] == "2026-05-23T10:15_6699"

    statuses = {item["travel_id"]: item["dataset_status"] for item in route["offers"]}
    assert statuses["2026-05-23T06:00_6611"] == STATUS_ZERO
    assert statuses["2026-05-24T06:00_6641"] == STATUS_PRESENT_NOT_ZERO
    assert statuses["2026-05-23T10:15_6699"] == STATUS_MISSING
    assert statuses[None] == STATUS_ZERO
    assert route["offers"][0]["matched_dataset_row"]["train_no"] == "6611"


def test_diff_without_live_watch(planner):
    trips = planner.repository.get_bundle().trips
    result = diff_live_against_dataset({"has_live_watch": False, "message": "rien"}, trips)
    assert result["has_live_watch"] is False
    assert result["routes"] == []
    assert result["summary"][STATUS_MISSING] == 0


def test_load_tgvmax_csv_handles_semicolon_export(tmp_path):
    csv_path = tmp_path / "tgvmax.csv"
    csv_path.write_text(
        "date;train_no;origine;destination;heure_depart;heure_arrivee;od_happy_card\n"
        "2026-11-19;8072;LAVAL;PARIS (intramuros);06:16;07:45;OUI\n"
        "2026-11-19;9774;BOURG EN BRESSE;PARIS (intramuros);15:52;17:42;NON\n",
        encoding="utf-8",
    )

    trips = load_tgvmax_csv(csv_path)

    assert len(trips) == 2
    assert trips["is_zero"].tolist() == [True, False]
    assert trips["origin"].tolist() == ["LAVAL", "BOURG EN BRESSE"]

    result = diff_live_against_dataset(
        {
            "has_live_watch": True,
            "captured_at": "2026-11-19T12:00:00Z",
            "watches": [
                {
                    "origin_label": "Laval",
                    "destination_label": "Paris",
                    "watch_date": "2026-11-19",
                    "zero_offers": [
                        {"travelId": "2026-11-19T06:16_8072", "departureTime": "06:16"},
                        {"travelId": "2026-11-19T18:30_8800", "departureTime": "18:30"},
                    ],
                }
            ],
        },
        trips,
    )

    assert result["summary"][STATUS_ZERO] == 1
    assert result["summary"][STATUS_MISSING] == 1
    assert result["routes"][0]["not_in_dataset"][0]["travel_id"] == "2026-11-19T18:30_8800"
