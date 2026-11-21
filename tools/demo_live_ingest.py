"""Envoie un etat live-watch de demonstration au backend pour voir l'UI sans l'extension.

Genere un payload synthetique realiste (surveillances + calendrier de jours a
0 EUR + offres trains + heartbeat worker + plan full-month) et le pousse vers :

- POST /api/live-watch/ingest
- POST /api/live-worker/heartbeat
- POST /api/live-watch/plan/full-month

Usage (backend local lance avec `make backend`) :

    python3 tools/demo_live_ingest.py
    python3 tools/demo_live_ingest.py --base-url http://127.0.0.1:8000 --origin "Paris Montparnasse" --destination "Bordeaux Saint-Jean"
    python3 tools/demo_live_ingest.py --dry-run   # affiche seulement le payload

Puis ouvre http://127.0.0.1:8000/live-watch (et /api/live-watch/zero-vs-dataset).
Stdlib uniquement.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import date, datetime, timedelta, timezone


DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def build_demo_payload(origin: str, destination: str, watch_date: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    next_day = (date.fromisoformat(watch_date) + timedelta(days=1)).isoformat()
    captured_at = now.isoformat()

    watch = {
        "id": f"{origin}|{destination}|{watch_date}",
        "origin_label": origin,
        "destination_label": destination,
        "watch_date": watch_date,
        "status": "ok",
        "zero_offer_count": 2,
        "zero_days": [
            {"date": watch_date, "label": watch_date, "best_price_datetime": f"{watch_date}T06:23:00"},
            {"date": next_day, "label": next_day, "best_price_datetime": f"{next_day}T07:00:00"},
        ],
        "zero_offers": [
            {
                "travelId": f"{watch_date}T06:23_999901",
                "departureTime": "06:23",
                "arrivalTime": "09:30",
                "origin": origin.upper(),
                "destination": destination.upper(),
                "offerTitle": "2de classe",
                "offerSubtitle": "Tarif Max Jeune",
                "priceLabel": "0 €",
                "fareNames": ["Tarif MAX JEUNE"],
            },
            {
                "travelId": f"{watch_date}T18:47_999902",
                "departureTime": "18:47",
                "arrivalTime": "21:55",
                "origin": origin.upper(),
                "destination": destination.upper(),
                "offerTitle": "2de classe",
                "offerSubtitle": "Tarif Max Jeune",
                "priceLabel": "0 €",
                "fareNames": ["Tarif MAX JEUNE"],
            },
        ],
        "check_count": 42,
        "success_count": 42,
        "last_checked_at": captured_at,
        "last_success_at": captured_at,
        "last_alert_at": captured_at,
        "last_error": None,
        "history": [
            {
                "type": "zero_day_added",
                "at": captured_at,
                "count": 1,
                "days": [next_day],
            },
            {
                "type": "zero_added",
                "at": captured_at,
                "count": 2,
                "travelIds": [f"{watch_date}T06:23_999901", f"{watch_date}T18:47_999902"],
            },
            {"type": "check_ok", "at": captured_at, "zeroOfferCount": 2},
        ],
    }

    return {
        "source": "demo-live-ingest",
        "captured_at": captured_at,
        "summary": {
            "watch_count": 1,
            "ok_count": 1,
            "error_count": 0,
            "waiting_count": 0,
            "zero_watch_count": 1,
            "zero_offer_count": 2,
            "zero_day_count": 2,
        },
        "watches": [watch],
    }


def build_demo_heartbeat(now: datetime | None = None, base_url: str = DEFAULT_BASE_URL) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "captured_at": now.isoformat(),
        "backend_base_url": base_url,
        "status": "ok",
        "watch_tab_url": "https://www.sncf-connect.com/home/search",
        "watch_tab_id": 1,
        "watch_count": 1,
        "browser_open": True,
        "sncf_tab_ready": True,
        "last_error": None,
        "session_hint": "session_sncf_active",
    }


def post_json(base_url: str, path: str, payload: dict, timeout: float = 15.0) -> dict:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Injecte un etat live-watch de demonstration dans le backend.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--origin", default="Paris Montparnasse")
    parser.add_argument("--destination", default="Bordeaux Saint-Jean")
    parser.add_argument("--date", default=None, help="date surveillee (ISO, defaut: J+7)")
    parser.add_argument("--dry-run", action="store_true", help="affiche le payload sans rien poster")
    args = parser.parse_args(argv)

    watch_date = args.date or (date.today() + timedelta(days=7)).isoformat()
    payload = build_demo_payload(args.origin, args.destination, watch_date)

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    ingest = post_json(args.base_url, "/api/live-watch/ingest", payload)
    heartbeat = post_json(args.base_url, "/api/live-worker/heartbeat", build_demo_heartbeat(base_url=args.base_url))
    plan = post_json(
        args.base_url,
        "/api/live-watch/plan/full-month",
        {
            "origin_label": args.origin,
            "destination_label": args.destination,
            "dates": [watch_date],
        },
    )

    print(f"ingest OK   : {ingest['summary']}")
    print(f"heartbeat OK: statut={heartbeat['worker']['status']}")
    print(f"plan OK     : {plan['watch_count']} surveillance(s) planifiee(s)")
    print()
    print(f"Ouvre {args.base_url.rstrip('/')}/live-watch")
    print(f"API : {args.base_url.rstrip('/')}/api/live-watch/zero-calendar")
    print(f"API : {args.base_url.rstrip('/')}/api/live-watch/zero-vs-dataset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
