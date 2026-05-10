from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Callable

import requests

from app.config import Settings
from app.utils import normalize_text


BLOCKED_PATTERNS = (
    "PLEASE ENABLE JS AND DISABLE ANY AD BLOCKER",
    "CAPTCHA DELIVERY",
    "GEO CAPTCHA DELIVERY",
    "BOT PROTECTION",
)

ZERO_PRICE_PATTERN = re.compile(r"(^|[^0-9])0\s*(€|eur)", re.IGNORECASE)

UNAVAILABLE_PATTERNS = (
    "COMPLET",
    "INDISPONIBLE",
    "AUCUN TRAJET",
    "AUCUNE OFFRE",
    "AUCUN RESULTAT",
)


@dataclass(slots=True)
class CachedLiveAvailability:
    expires_at: datetime
    payload: dict


class LiveAvailabilityVerifier:
    def __init__(
        self,
        settings: Settings,
        fetcher: Callable[[str], str] | None = None,
    ):
        self.settings = settings
        self._fetcher = fetcher or self._default_fetcher
        self._cache: dict[str, CachedLiveAvailability] = {}
        self._lock = Lock()

    def verify_trips(self, trips: list[dict], limit: int | None = None) -> dict:
        capped_limit = limit or self.settings.live_check_default_limit
        selected_trips = trips[: max(0, capped_limit)]
        results = [self._verify_trip(trip) for trip in selected_trips]
        counts: dict[str, int] = {}
        for result in results:
            counts[result["status"]] = counts.get(result["status"], 0) + 1

        return {
            "verified_count": len(results),
            "limit": capped_limit,
            "cache_minutes": self.settings.live_check_cache_minutes,
            "results": results,
            "summary": {
                "confirmed_zero": counts.get("confirmed_zero", 0),
                "unavailable": counts.get("unavailable", 0),
                "blocked": counts.get("blocked", 0),
                "unknown": counts.get("unknown", 0),
                "error": counts.get("error", 0),
            },
        }

    def _verify_trip(self, trip: dict) -> dict:
        trip_id = trip.get("id") or ""
        booking_url = trip.get("booking_url") or ""
        cache_key = booking_url or trip_id
        now = datetime.now()

        if cache_key:
            with self._lock:
                cached = self._cache.get(cache_key)
                if cached is not None and cached.expires_at > now:
                    return {**cached.payload, "trip_id": trip_id}

        try:
            html_payload = self._fetcher(booking_url)
            parsed = self._parse_html(html_payload)
        except requests.RequestException as exc:
            parsed = {
                "status": "error",
                "label": "Erreur reseau",
                "reason": f"verification impossible: {exc.__class__.__name__}",
                "source": "sncf_connect_html",
            }
        except Exception as exc:  # pragma: no cover - defensive guard
            parsed = {
                "status": "error",
                "label": "Erreur analyse",
                "reason": f"verification impossible: {exc.__class__.__name__}",
                "source": "sncf_connect_html",
            }

        payload = {
            "trip_id": trip_id,
            "booking_url": booking_url,
            "checked_at": now.isoformat(),
            **parsed,
        }
        if cache_key:
            with self._lock:
                self._cache[cache_key] = CachedLiveAvailability(
                    expires_at=now + timedelta(minutes=self.settings.live_check_cache_minutes),
                    payload=payload,
                )
        return payload

    def _default_fetcher(self, url: str) -> str:
        response = requests.get(
            url,
            timeout=self.settings.live_check_timeout_seconds,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            },
        )
        response.raise_for_status()
        return response.text

    def _parse_html(self, payload: str) -> dict:
        if not payload:
            return {
                "status": "unknown",
                "label": "Inconnu",
                "reason": "reponse vide",
                "source": "sncf_connect_html",
            }

        decoded = html.unescape(payload)
        normalized = normalize_text(decoded)
        if any(pattern in normalized for pattern in BLOCKED_PATTERNS):
            return {
                "status": "blocked",
                "label": "Bloque par le site",
                "reason": "SNCF Connect a renvoye une protection anti-bot",
                "source": "sncf_connect_html",
            }

        if ZERO_PRICE_PATTERN.search(decoded) or ZERO_PRICE_PATTERN.search(normalized):
            return {
                "status": "confirmed_zero",
                "label": "0 EUR confirme",
                "reason": "un prix a 0 EUR a ete detecte sur la page",
                "source": "sncf_connect_html",
            }

        if any(pattern in normalized for pattern in UNAVAILABLE_PATTERNS):
            return {
                "status": "unavailable",
                "label": "Plus dispo",
                "reason": "la page indique une indisponibilite ou aucun resultat",
                "source": "sncf_connect_html",
            }

        return {
            "status": "unknown",
            "label": "Non confirme",
            "reason": "aucun signal de disponibilite clair n'a ete detecte",
            "source": "sncf_connect_html",
        }
