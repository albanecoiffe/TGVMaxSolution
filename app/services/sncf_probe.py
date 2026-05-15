from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


SENSITIVE_KEYS = {
    "accessToken",
    "refreshToken",
    "idToken",
    "x-bff-key",
    "x-con-ex",
    "x-con-id",
    "x-con-s",
    "x-con-v",
    "x-criteo-id",
    "x-email-hidden",
    "x-email-strong",
    "x-email-stronger",
}

BEST_PRICE_RE = re.compile(
    r'"label":"(?P<label>[^"]+)","priceLabel":"(?P<price>[^"]+)","bestPriceDateTime":"(?P<dt>[^"]+)"'
)
FARE_NAME_RE = re.compile(r'"fareName":"(?P<fare>[^"]+)"')
ZERO_PRICE_RE = re.compile(r'"priceLabel":"0\\u00a0€"|"priceLabel":"0 €"')
OFFER_TITLE_RE = re.compile(r'"header":\{"title":"(?P<title>[^"]+)","accessibilityTitle":"[^"]+","subtitle":"(?P<subtitle>[^"]+)"')


def load_probe_events(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Le fichier probe doit contenir une liste d'evenements")
    return [item for item in payload if isinstance(item, dict)]


def redact_value(value: object) -> object:
    if value in (None, ""):
        return value
    if isinstance(value, str):
        return "[redacted]"
    if isinstance(value, (int, float, bool)):
        return "[redacted]"
    return "[redacted]"


def redact_sensitive_data(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            if key in SENSITIVE_KEYS:
                redacted[key] = redact_value(item)
            else:
                redacted[key] = redact_sensitive_data(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    return value


def probe_event_urls(events: list[dict]) -> list[str]:
    urls = []
    for event in events:
        url = event.get("url")
        if isinstance(url, str):
            urls.append(url)
    return sorted(set(urls))


def itinerary_events(events: list[dict]) -> list[dict]:
    return [event for event in events if event.get("url") == "https://www.sncf-connect.com/bff/api/v1/itineraries"]


def parse_json_preview(value: object) -> dict | list | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, (dict, list)):
        return parsed
    return None


def fallback_best_prices(body_preview: object) -> list[dict]:
    if not isinstance(body_preview, str):
        return []
    results = []
    for match in BEST_PRICE_RE.finditer(body_preview):
        results.append(
            {
                "label": match.group("label"),
                "price_label": match.group("price"),
                "best_price_datetime": match.group("dt"),
            }
        )
    return results


def fallback_zero_offers(body_preview: object) -> tuple[list[dict], list[str]]:
    if not isinstance(body_preview, str):
        return [], []

    fare_names = []
    seen_fares = set()
    for match in FARE_NAME_RE.finditer(body_preview):
        fare_name = match.group("fare")
        if fare_name not in seen_fares:
            seen_fares.add(fare_name)
            fare_names.append(fare_name)

    zero_offer_count = len(ZERO_PRICE_RE.findall(body_preview))
    offer_matches = OFFER_TITLE_RE.findall(body_preview)
    zero_offers = []
    for index in range(min(zero_offer_count, len(offer_matches))):
        title, subtitle = offer_matches[index]
        zero_offers.append(
            {
                "proposal_id": None,
                "travel_id": None,
                "departure_time": None,
                "arrival_time": None,
                "origin": None,
                "destination": None,
                "best_price_label": None,
                "offer_title": title,
                "offer_subtitle": subtitle,
                "price_label": "0 €",
                "fare_names": fare_names,
            }
        )
    return zero_offers, fare_names


def summarize_itinerary_event(event: dict) -> dict:
    request = parse_json_preview(event.get("requestBodyPreview")) or {}
    response = parse_json_preview(event.get("bodyPreview")) or {}
    raw_body_preview = event.get("bodyPreview")

    long_distance = {}
    if isinstance(response, dict):
        long_distance = response.get("longDistance") or {}
    proposals_block = long_distance.get("proposals") or {}
    proposals = proposals_block.get("proposals") or []
    best_prices = proposals_block.get("bestPrices") or []

    zero_best_prices = [
        item
        for item in best_prices
        if isinstance(item, dict) and item.get("priceLabel") == "0\u00a0€"
    ]

    zero_offers: list[dict] = []
    fares_counter: Counter[str] = Counter()

    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        for offer_group_key in ("firstComfortClassOffers", "secondComfortClassOffers"):
            offer_group = proposal.get(offer_group_key) or {}
            for offer in offer_group.get("offers") or []:
                if not isinstance(offer, dict):
                    continue
                if offer.get("priceLabel") != "0\u00a0€":
                    continue
                travelers_fares = offer.get("travelersFares") or []
                fare_names = []
                for traveler_fare in travelers_fares:
                    for segment_fare in (traveler_fare or {}).get("segmentFares") or []:
                        fare_name = segment_fare.get("fareName")
                        if isinstance(fare_name, str) and fare_name:
                            fare_names.append(fare_name)
                            fares_counter[fare_name] += 1
                zero_offers.append(
                    {
                        "proposal_id": proposal.get("id"),
                        "travel_id": proposal.get("travelId"),
                        "departure_time": ((proposal.get("departure") or {}).get("timeLabel")),
                        "arrival_time": ((proposal.get("arrival") or {}).get("timeLabel")),
                        "origin": ((proposal.get("departure") or {}).get("originStationLabel")),
                        "destination": ((proposal.get("arrival") or {}).get("destinationStationLabel")),
                        "best_price_label": proposal.get("bestPriceLabel"),
                        "offer_title": ((offer.get("header") or {}).get("title")),
                        "offer_subtitle": ((offer.get("header") or {}).get("subtitle")),
                        "price_label": offer.get("priceLabel"),
                        "fare_names": fare_names,
                    }
                )

    if not best_prices:
        best_prices = fallback_best_prices(raw_body_preview)
        zero_best_prices = [
            item for item in best_prices if isinstance(item, dict) and item.get("price_label") == "0 €"
        ]

    if not zero_offers:
        zero_offers, fallback_fare_names = fallback_zero_offers(raw_body_preview)
        for fare_name in fallback_fare_names:
            fares_counter[fare_name] += 1

    outward = ((request.get("schedule") or {}).get("outward") or {})
    main_journey = request.get("mainJourney") or {}
    passengers = request.get("passengers") or []

    return {
        "tab_url": event.get("tabUrl"),
        "request": {
            "origin": ((main_journey.get("origin") or {}).get("label")),
            "destination": ((main_journey.get("destination") or {}).get("label")),
            "outward_date": outward.get("date"),
            "branch": request.get("branch"),
            "itinerary_id": request.get("itineraryId"),
            "passenger_count": len(passengers),
            "has_tgvmax_card": any(
                fare.get("code") == "TGV_MAX"
                for passenger in passengers
                if isinstance(passenger, dict)
                for fare in (passenger.get("discountCards") or [])
                if isinstance(fare, dict)
            ),
        },
        "response": {
            "best_price_labels": [
                {
                    "label": item.get("label"),
                    "price_label": item.get("priceLabel") or item.get("price_label"),
                    "best_price_datetime": item.get("bestPriceDateTime") or item.get("best_price_datetime"),
                }
                for item in best_prices
                if isinstance(item, dict)
            ],
            "zero_best_price_days": len(zero_best_prices),
            "zero_offer_count": len(zero_offers),
            "zero_offers": zero_offers,
            "fare_names": sorted(fares_counter),
        },
    }


def summarize_probe_file(path: Path) -> dict:
    events = load_probe_events(path)
    itinerary_summaries = [summarize_itinerary_event(event) for event in itinerary_events(events)]
    return {
        "path": str(path),
        "event_count": len(events),
        "urls": probe_event_urls(events),
        "itinerary_event_count": len(itinerary_summaries),
        "itinerary_summaries": itinerary_summaries,
        "redacted_events": redact_sensitive_data(events),
    }
