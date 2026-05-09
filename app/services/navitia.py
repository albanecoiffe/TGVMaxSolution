from __future__ import annotations

from datetime import datetime

import requests

from app.config import Settings
from app.models import StationRecord
from app.utils import duration_minutes


class NavitiaClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.sncf_api_token)

    def plan_from_station(
        self,
        origin: StationRecord,
        target_latitude: float,
        target_longitude: float,
        departure_after: datetime,
    ) -> dict | None:
        if not self.enabled:
            return None

        params = {
            "from": f"{origin.longitude};{origin.latitude}",
            "to": f"{target_longitude};{target_latitude}",
            "datetime": departure_after.strftime("%Y%m%dT%H%M%S"),
            "count": 1,
            "min_nb_journeys": 1,
            "data_freshness": "base_schedule",
        }
        try:
            response = requests.get(
                "https://api.sncf.com/v1/coverage/sncf/journeys",
                params=params,
                timeout=40,
                auth=(self.settings.sncf_api_token or "", ""),
            )
            response.raise_for_status()
        except requests.RequestException:
            return None

        payload = response.json()
        journeys = payload.get("journeys") or []
        if not journeys:
            return None

        for journey in journeys:
            parsed = self._parse_journey(journey)
            if parsed is not None:
                return parsed
        return None

    def _parse_journey(self, journey: dict) -> dict | None:
        departure = self._parse_navitia_datetime(journey.get("departure_date_time"))
        arrival = self._parse_navitia_datetime(journey.get("arrival_date_time"))
        if departure is None or arrival is None:
            return None

        sections_output = []
        for section in journey.get("sections", []):
            section_type = section.get("type")
            from_name = ((section.get("from") or {}).get("name")) or ""
            to_name = ((section.get("to") or {}).get("name")) or ""
            display_info = section.get("display_informations") or {}
            commercial_mode = display_info.get("commercial_mode", "")
            sections_output.append(
                {
                    "type": section_type,
                    "mode": commercial_mode or display_info.get("physical_mode", "") or section_type,
                    "label": display_info.get("label") or display_info.get("headsign") or "",
                    "from": from_name,
                    "to": to_name,
                }
            )

        if not sections_output:
            return None

        return {
            "departure_time": departure.strftime("%H:%M"),
            "arrival_time": arrival.strftime("%H:%M"),
            "duration_minutes": duration_minutes(departure, arrival),
            "sections": sections_output,
        }

    @staticmethod
    def _parse_navitia_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y%m%dT%H%M%S")
        except ValueError:
            return None

