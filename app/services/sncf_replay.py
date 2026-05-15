from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.services.sncf_probe import (
    itinerary_events,
    load_probe_events,
    parse_json_preview,
    summarize_itinerary_event,
)


ITINERARIES_URL = "https://www.sncf-connect.com/bff/api/v1/itineraries"
FORWARDED_HEADER_NAMES = {
    "accept",
    "content-type",
    "virtual-env-name",
    "x-api-env",
    "x-app-version",
    "x-bff-key",
    "x-client-app-id",
    "x-client-channel",
    "x-con-ex",
    "x-con-id",
    "x-con-s",
    "x-con-v",
    "x-criteo-id",
    "x-device-class",
    "x-device-os-version",
    "x-email-hidden",
    "x-email-strong",
    "x-email-stronger",
    "x-market-locale",
    "x-nav-current-path",
    "x-nav-previous-page",
    "x-nav-session-id",
    "x-search-usage",
    "x-visitor-type",
}


@dataclass(slots=True)
class ReplayTemplate:
    source_path: Path
    event_index: int
    url: str
    headers: dict[str, str]
    body: dict


def build_replay_template(probe_path: Path, event_index: int = -1) -> ReplayTemplate:
    events = itinerary_events(load_probe_events(probe_path))
    if not events:
        raise ValueError("Aucun evenement itineraries dans ce probe")

    event = events[event_index]
    body = parse_json_preview(event.get("requestBodyPreview"))
    if not isinstance(body, dict):
        raise ValueError("Le body de requete itineraries n'est pas parseable")

    request_headers = event.get("requestHeaders") or {}
    headers = {
        key: value
        for key, value in request_headers.items()
        if key.lower() in FORWARDED_HEADER_NAMES and isinstance(value, str)
    }
    if "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    if "Accept" not in headers:
        headers["Accept"] = "application/json, text/plain, */*"

    return ReplayTemplate(
        source_path=probe_path,
        event_index=event_index,
        url=event.get("url") or ITINERARIES_URL,
        headers=headers,
        body=deepcopy(body),
    )


def update_template_trip(
    template: ReplayTemplate,
    *,
    origin_id: str | None = None,
    origin_label: str | None = None,
    destination_id: str | None = None,
    destination_label: str | None = None,
    outward_datetime_iso: str | None = None,
) -> ReplayTemplate:
    next_body = deepcopy(template.body)
    main_journey = next_body.setdefault("mainJourney", {})
    schedule = next_body.setdefault("schedule", {})
    outward = schedule.setdefault("outward", {})

    if origin_id is not None:
        main_journey.setdefault("origin", {})["id"] = origin_id
    if origin_label is not None:
        main_journey.setdefault("origin", {})["label"] = origin_label
    if destination_id is not None:
        main_journey.setdefault("destination", {})["id"] = destination_id
    if destination_label is not None:
        main_journey.setdefault("destination", {})["label"] = destination_label
    if outward_datetime_iso is not None:
        datetime.fromisoformat(outward_datetime_iso.replace("Z", "+00:00"))
        outward["date"] = outward_datetime_iso

    return ReplayTemplate(
        source_path=template.source_path,
        event_index=template.event_index,
        url=template.url,
        headers=deepcopy(template.headers),
        body=next_body,
    )


def replay_itineraries(template: ReplayTemplate, timeout: int = 40) -> dict:
    import requests

    response = requests.post(
        template.url,
        headers=template.headers,
        json=template.body,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def summarize_replay_response(template: ReplayTemplate, response_payload: dict) -> dict:
    synthetic_event = {
        "tabUrl": template.headers.get("x-nav-current-path"),
        "requestBodyPreview": json.dumps(template.body, ensure_ascii=False),
        "bodyPreview": json.dumps(response_payload, ensure_ascii=False),
    }
    return summarize_itinerary_event(synthetic_event)
