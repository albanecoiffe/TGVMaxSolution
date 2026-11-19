"""Rapport temps reel des disponibilites 0 EUR poussees par l'extension navigateur.

Lit le dernier etat live-watch enregistre cote backend
(`data/history/latest-live-watch.json` par defaut) et affiche, par trajet :

- les jours detectes a 0 EUR (calendrier bestPrices, rafraichi a chaque cycle),
- les trains 0 EUR visibles avec leurs horaires de depart,
- la fraicheur du dernier check.

Usage :

    PYTHONPATH=. python3 tools/live_zero_report.py
    PYTHONPATH=. python3 tools/live_zero_report.py --path data/history/latest-live-watch.json
    PYTHONPATH=. python3 tools/live_zero_report.py --json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "history" / "latest-live-watch.json"


def parse_age(iso_value: str | None) -> str:
    if not iso_value:
        return "jamais"
    try:
        parsed = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    except ValueError:
        return iso_value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - parsed
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "a l'instant"
    if seconds < 60:
        return f"il y a {seconds} s"
    if seconds < 3600:
        return f"il y a {seconds // 60} min"
    return f"il y a {seconds // 3600} h {(seconds % 3600) // 60} min"


def build_report(payload: dict) -> dict:
    if not payload.get("has_live_watch"):
        return {
            "has_live_watch": False,
            "message": payload.get("message") or "aucune surveillance live enregistree",
            "captured_at": None,
            "routes": [],
        }

    routes: dict[str, dict] = {}
    for watch in payload.get("watches") or []:
        route = f'{watch.get("origin_label") or "?"} -> {watch.get("destination_label") or "?"}'
        entry = routes.setdefault(
            route,
            {
                "route": route,
                "zero_days": {},
                "dates": {},
                "last_checked_at": None,
            },
        )
        for day in watch.get("zero_days") or []:
            if isinstance(day, dict) and day.get("date"):
                entry["zero_days"].setdefault(day["date"], day)
        watch_date = watch.get("watch_date")
        if watch_date:
            entry["dates"].setdefault(
                watch_date,
                {
                    "watch_date": watch_date,
                    "status": watch.get("status"),
                    "zero_offer_count": watch.get("zero_offer_count") or 0,
                    "departures": [
                        offer.get("departureTime")
                        for offer in watch.get("zero_offers") or []
                        if isinstance(offer, dict) and offer.get("departureTime")
                    ],
                    "last_checked_at": watch.get("last_checked_at"),
                    "last_error": watch.get("last_error"),
                },
            )
        last_checked_at = watch.get("last_checked_at")
        if last_checked_at and (entry["last_checked_at"] is None or last_checked_at > entry["last_checked_at"]):
            entry["last_checked_at"] = last_checked_at

    route_list = []
    for entry in routes.values():
        days = [entry["zero_days"][key] for key in sorted(entry["zero_days"])]
        route_list.append(
            {
                "route": entry["route"],
                "zero_day_count": len(days),
                "zero_days": days,
                "dates": [entry["dates"][key] for key in sorted(entry["dates"])],
                "last_checked_at": entry["last_checked_at"],
            }
        )
    route_list.sort(key=lambda item: item["route"])

    return {
        "has_live_watch": True,
        "captured_at": payload.get("captured_at"),
        "captured_age": parse_age(payload.get("captured_at")),
        "summary": payload.get("summary") or {},
        "routes": route_list,
    }


def render_text(report: dict) -> str:
    if not report.get("has_live_watch"):
        return report.get("message") or "aucune surveillance live enregistree"

    lines = [
        f"Synchronisation live : {report.get('captured_at')} ({report.get('captured_age')})",
        f"Surveillances : {report['summary'].get('watch_count', 0)} | "
        f"jours 0 EUR : {report['summary'].get('zero_day_count', 0)} | "
        f"trains 0 EUR visibles : {report['summary'].get('zero_offer_count', 0)}",
        "",
    ]
    for route in report["routes"]:
        lines.append(f"== {route['route']} (dernier check {parse_age(route.get('last_checked_at'))})")
        if route["zero_days"]:
            days = ", ".join(day.get("label") or day.get("date") or "?" for day in route["zero_days"])
            lines.append(f"   jours à 0 EUR ({route['zero_day_count']}) : {days}")
        else:
            lines.append("   aucun jour à 0 EUR pour le moment")
        for date_entry in route["dates"]:
            departures = ", ".join(date_entry["departures"][:8]) or "-"
            lines.append(
                f"   {date_entry['watch_date']} : {date_entry['zero_offer_count']} train(s) 0 EUR "
                f"[departs: {departures}] statut={date_entry['status']}"
            )
            if date_entry.get("last_error"):
                lines.append(f"      erreur: {date_entry['last_error']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Rapport temps reel des disponibilites 0 EUR (live-watch).")
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH, help="chemin du latest-live-watch.json")
    parser.add_argument("--json", action="store_true", help="sortie JSON brute")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"Aucun fichier live-watch trouve : {args.path}")
        print("Lance d'abord le backend et l'extension navigateur (bouton Verifier maintenant).")
        return 1

    payload = json.loads(args.path.read_text(encoding="utf-8"))
    report = build_report(payload)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
