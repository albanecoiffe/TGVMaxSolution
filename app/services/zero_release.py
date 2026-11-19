from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, time, timedelta
from hashlib import sha1
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import Settings
from app.utils import normalize_text, parse_hhmm


PARIS_TZ = ZoneInfo("Europe/Paris")

WEEKDAY_LABELS = [
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
]

MAX_EVENTS = 20000


class ZeroReleaseStore:
    """Historique des apparitions de billets a 0 EUR et estimation de sortie.

    Deux sources alimentent le store :
    - la surveillance live (extension navigateur) qui pousse des evenements
      `zero_added` horodates avec les offres 0 EUR detectees,
    - les snapshots du dataset SNCF tgvmax (diff entre deux refreshs).
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def events_file(self) -> Path:
        return self.settings.history_dir / "zero-releases.jsonl"

    def record_live_watch(self, payload: dict) -> dict:
        events: list[dict] = []
        for watch in payload.get("watches") or []:
            if not isinstance(watch, dict):
                continue
            origin = watch.get("origin_label") or ""
            destination = watch.get("destination_label") or ""
            travel_date = watch.get("watch_date") or ""
            offers_by_id: dict[str, dict] = {}
            for offer in watch.get("zero_offers") or []:
                if not isinstance(offer, dict):
                    continue
                offer_id = offer.get("travelId") or offer.get("travel_id")
                if offer_id:
                    offers_by_id[str(offer_id)] = offer
            for entry in watch.get("history") or []:
                if not isinstance(entry, dict):
                    continue
                at = entry.get("at")
                if not at:
                    continue
                if entry.get("type") == "zero_added":
                    travel_ids = entry.get("travelIds") or entry.get("travel_ids") or []
                    matched = [offers_by_id[str(t)] for t in travel_ids if str(t) in offers_by_id]
                    if matched:
                        for offer in matched:
                            events.append(
                                self._release_event(
                                    travel_date=travel_date,
                                    origin=origin,
                                    destination=destination,
                                    departure_time=offer.get("departureTime") or offer.get("departure_time"),
                                    train_no=None,
                                    first_seen_at=at,
                                    source="live_watch",
                                )
                            )
                    else:
                        events.append(
                            self._release_event(
                                travel_date=travel_date,
                                origin=origin,
                                destination=destination,
                                departure_time=None,
                                train_no=None,
                                first_seen_at=at,
                                source="live_watch",
                            )
                        )
                elif entry.get("type") == "check_ok":
                    events.append(
                        {
                            "kind": "observation",
                            "travel_date": travel_date,
                            "origin": origin,
                            "destination": destination,
                            "observed_at": at,
                            "zero_offer_count": entry.get("zeroOfferCount")
                            or entry.get("zero_offer_count")
                            or 0,
                            "source": "live_watch",
                        }
                    )
        return self._append(events)

    def record_snapshot_releases(self, diff: dict) -> dict:
        events: list[dict] = []
        captured_at = diff.get("captured_at")
        if not captured_at:
            return {"recorded": 0, "total": len(self._load())}
        for entry in diff.get("new_trips") or []:
            if not isinstance(entry, dict):
                continue
            events.append(
                self._release_event(
                    travel_date=entry.get("date") or "",
                    origin=entry.get("origin") or "",
                    destination=entry.get("destination") or "",
                    departure_time=entry.get("departure_time"),
                    train_no=entry.get("train_no"),
                    first_seen_at=captured_at,
                    source="snapshot",
                )
            )
        return self._append(events)

    def events(self, limit: int = 200) -> list[dict]:
        loaded = self._load()
        loaded.sort(key=lambda item: str(item.get("first_seen_at") or item.get("observed_at") or ""), reverse=True)
        return loaded[: max(1, limit)]

    def estimate(
        self,
        travel_date: date,
        slot_start: str = "00:00",
        slot_end: str = "23:59",
        origin: str = "",
        destination: str = "",
        weekday_only: bool = True,
        recent_limit: int = 15,
    ) -> dict:
        all_events = self._load()
        releases = [item for item in all_events if item.get("kind") == "release"]
        observations = [item for item in all_events if item.get("kind") == "observation"]

        start = parse_hhmm(slot_start) or time(0, 0)
        end = parse_hhmm(slot_end) or time(23, 59)
        origin_norm = normalize_text(origin)
        destination_norm = normalize_text(destination)

        def route_match(event: dict) -> bool:
            if origin_norm and origin_norm not in normalize_text(event.get("origin")):
                return False
            if destination_norm and destination_norm not in normalize_text(event.get("destination")):
                return False
            return True

        def slot_match(event: dict) -> bool:
            moment = parse_hhmm(event.get("departure_time"))
            if moment is None:
                return False
            return _time_in_slot(moment, start, end)

        def weekday_match(event: dict) -> bool:
            if not weekday_only:
                return True
            try:
                event_date = date.fromisoformat(event.get("travel_date") or "")
            except ValueError:
                return False
            return event_date.weekday() == travel_date.weekday()

        filtered = [
            event
            for event in releases
            if route_match(event) and slot_match(event) and weekday_match(event)
        ]

        payload: dict = {
            "has_data": bool(filtered),
            "travel_date": travel_date.isoformat(),
            "travel_weekday_label": WEEKDAY_LABELS[travel_date.weekday()],
            "slot": {"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")},
            "filters": {
                "origin": origin,
                "destination": destination,
                "weekday_only": weekday_only,
            },
            "sample_size": len(filtered),
            "source_counts": dict(Counter(item.get("source") or "unknown" for item in filtered)),
            "generated_at": datetime.now(PARIS_TZ).isoformat(),
        }

        if not filtered:
            payload["message"] = (
                "Aucun evenement de sortie 0 EUR enregistre pour cette date, cette planche horaire"
                " et ce filtre. Lance la surveillance live ou rafraichis les donnees pour alimenter l'historique."
            )
            payload["recent_events"] = []
            return payload

        by_delay: Counter[int] = Counter()
        by_hour: Counter[int] = Counter()
        by_weekday_hour: Counter[tuple[int, int]] = Counter()
        by_combined: Counter[tuple[int, int, int]] = Counter()
        serialized_events = []

        for event in filtered:
            seen = _parse_datetime(event.get("first_seen_at"))
            local_seen = seen.astimezone(PARIS_TZ) if seen is not None else None
            try:
                event_travel_date = date.fromisoformat(event.get("travel_date") or "")
            except ValueError:
                continue
            days_before = (event_travel_date - local_seen.date()).days if local_seen else None
            weekday = local_seen.weekday() if local_seen else None
            hour = local_seen.hour if local_seen else None
            if days_before is not None:
                by_delay[days_before] += 1
            if hour is not None:
                by_hour[hour] += 1
            if weekday is not None and hour is not None:
                by_weekday_hour[(weekday, hour)] += 1
                if days_before is not None:
                    by_combined[(days_before, weekday, hour)] += 1
            serialized_events.append(
                {
                    "travel_date": event.get("travel_date"),
                    "origin": event.get("origin"),
                    "destination": event.get("destination"),
                    "departure_time": event.get("departure_time"),
                    "train_no": event.get("train_no"),
                    "first_seen_at": event.get("first_seen_at"),
                    "source": event.get("source"),
                    "days_before": days_before,
                    "release_weekday": weekday,
                    "release_weekday_label": WEEKDAY_LABELS[weekday] if weekday is not None else None,
                    "release_hour": hour,
                }
            )

        total = len(filtered)

        def percent(count: int) -> float:
            return round(count * 100.0 / total, 1)

        payload["distribution_by_delay"] = [
            {
                "days_before": days_before,
                "label": f"J-{days_before}",
                "count": count,
                "percent": percent(count),
            }
            for days_before, count in sorted(by_delay.items(), key=lambda item: (-item[1], item[0]))
        ]
        payload["distribution_by_hour"] = [
            {
                "hour": hour,
                "label": f"{hour}h",
                "count": count,
                "percent": percent(count),
            }
            for hour, count in sorted(by_hour.items(), key=lambda item: (-item[1], item[0]))
        ]
        payload["distribution_by_weekday_hour"] = [
            {
                "weekday": weekday,
                "weekday_label": WEEKDAY_LABELS[weekday],
                "hour": hour,
                "label": f"{WEEKDAY_LABELS[weekday]} {hour}h",
                "count": count,
                "percent": percent(count),
            }
            for (weekday, hour), count in sorted(
                by_weekday_hour.items(), key=lambda item: (-item[1], item[0])
            )
        ]

        most_probable = None
        if by_combined:
            days_before, weekday, hour = max(
                by_combined.items(), key=lambda item: (item[1], -item[0][0])
            )[0]
            count = by_combined[(days_before, weekday, hour)]
            expected_date = travel_date - timedelta(days=days_before)
            expected_release_at = datetime.combine(expected_date, time(hour)).isoformat()
            most_probable = {
                "days_before": days_before,
                "weekday": weekday,
                "weekday_label": WEEKDAY_LABELS[weekday],
                "hour": hour,
                "count": count,
                "percent": percent(count),
                "expected_release_at": expected_release_at,
                "label": f"J-{days_before}, {WEEKDAY_LABELS[weekday]} vers {hour}h",
            }
        payload["most_probable_release"] = most_probable
        if total < 5:
            payload["warning"] = (
                f"Seulement {total} evenement(s) dans l'echantillon : les pourcentages sont peu fiables."
            )

        observed_dates = {
            event.get("travel_date")
            for event in observations
            if event.get("travel_date") and route_match(event) and weekday_match(event)
        }
        release_dates = {event.get("travel_date") for event in filtered if event.get("travel_date")}
        dates_with_release = len(observed_dates & release_dates) if observed_dates else len(release_dates)
        denominator = len(observed_dates) if observed_dates else None
        payload["availability"] = {
            "observed_dates": denominator or 0,
            "dates_with_release": dates_with_release,
            "rate_percent": round(dates_with_release * 100.0 / denominator, 1) if denominator else None,
        }

        serialized_events.sort(key=lambda item: str(item.get("first_seen_at") or ""), reverse=True)
        payload["recent_events"] = serialized_events[: max(1, recent_limit)]
        return payload

    def _release_event(
        self,
        travel_date: str,
        origin: str,
        destination: str,
        departure_time: str | None,
        train_no: str | None,
        first_seen_at: str | None,
        source: str,
    ) -> dict:
        return {
            "kind": "release",
            "travel_date": travel_date,
            "origin": origin,
            "destination": destination,
            "departure_time": departure_time,
            "train_no": train_no,
            "first_seen_at": first_seen_at,
            "source": source,
        }

    def _append(self, events: list[dict]) -> dict:
        existing = self._load()
        by_key: dict[str, dict] = {}
        for event in existing:
            by_key[self._event_key(event)] = event
        recorded = 0
        for event in events:
            if not event.get("travel_date"):
                continue
            key = self._event_key(event)
            current = by_key.get(key)
            if current is None:
                by_key[key] = event
                recorded += 1
            elif event.get("kind") == "release" and event.get("departure_time"):
                existing_seen = _parse_datetime(current.get("first_seen_at"))
                new_seen = _parse_datetime(event.get("first_seen_at"))
                if new_seen is not None and (existing_seen is None or new_seen < existing_seen):
                    by_key[key] = event
        merged = list(by_key.values())
        if len(merged) > MAX_EVENTS:
            merged.sort(key=lambda item: str(item.get("first_seen_at") or item.get("observed_at") or ""))
            merged = merged[-MAX_EVENTS:]
        self.settings.history_dir.mkdir(parents=True, exist_ok=True)
        self.events_file.write_text(
            "".join(json.dumps(event, ensure_ascii=True) + "\n" for event in merged),
            encoding="utf-8",
        )
        return {"recorded": recorded, "total": len(merged)}

    def _event_key(self, event: dict) -> str:
        if event.get("kind") == "release" and event.get("departure_time"):
            base = "|".join(
                [
                    "release",
                    event.get("travel_date") or "",
                    normalize_text(event.get("origin")),
                    normalize_text(event.get("destination")),
                    event.get("departure_time") or "",
                    event.get("source") or "",
                ]
            )
        else:
            base = "|".join(
                [
                    event.get("kind") or "",
                    event.get("travel_date") or "",
                    normalize_text(event.get("origin")),
                    normalize_text(event.get("destination")),
                    str(event.get("first_seen_at") or event.get("observed_at") or ""),
                ]
            )
        return sha1(base.encode("utf-8")).hexdigest()

    def _load(self) -> list[dict]:
        if not self.events_file.exists():
            return []
        events = []
        for line in self.events_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                events.append(parsed)
        return events


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=PARIS_TZ)
    return parsed


def _time_in_slot(moment: time, start: time, end: time) -> bool:
    minutes = moment.hour * 60 + moment.minute
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    if start_minutes <= end_minutes:
        return start_minutes <= minutes <= end_minutes
    return minutes >= start_minutes or minutes <= end_minutes
