"""Watchdog du worker live navigateur + relai des alertes 0 EUR recentes.

Interroge le backend (local ou Render) :

- GET /api/live-worker/latest  : heartbeat du worker navigateur
- GET /api/live-watch/latest   : dernier etat live (alertes zero_added / zero_day_added)

Codes de sortie :

- 0 : worker OK, aucune alerte 0 EUR recente
- 1 : worker absent / heartbeat perime / onglet SNCF non pret
- 2 : worker OK mais au moins une alerte 0 EUR dans la fenetre

Usage (cron toutes les 5 min, la sortie non vide declenche un mail cron) :

    */5 * * * * python3 /chemin/TGVMaxSolution/tools/live_worker/check_live_worker.py \
        --base-url https://ton-app.onrender.com --max-age-minutes 5

Sans argument, cible http://127.0.0.1:8000. Aucune dependance externe (stdlib).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ALERT_TYPES = ("zero_added", "zero_day_added")


def parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def evaluate_worker(heartbeat: dict, now: datetime | None = None, max_age_minutes: float = 5.0) -> tuple[bool, list[str]]:
    now = now or datetime.now(timezone.utc)
    if not heartbeat.get("has_worker"):
        return False, ["aucun heartbeat worker recu"]

    reasons: list[str] = []
    captured_at = parse_iso(heartbeat.get("captured_at"))
    if captured_at is None:
        reasons.append("captured_at illisible ou absent")
    else:
        age_minutes = (now - captured_at).total_seconds() / 60
        if age_minutes > max_age_minutes:
            reasons.append(f"dernier heartbeat il y a {age_minutes:.1f} min (max {max_age_minutes:g} min)")

    worker = heartbeat.get("worker") or {}
    if not worker.get("browser_open", True):
        reasons.append("navigateur ferme")
    if not worker.get("sncf_tab_ready", False):
        reasons.append("onglet SNCF Connect non pret / session expiree (refaire une recherche sur SNCF Connect)")
    status = worker.get("status")
    if status not in (None, "ok"):
        reasons.append(f"statut worker : {status}")
    if worker.get("last_error"):
        reasons.append(f"erreur worker : {worker['last_error']}")
    return (not reasons), reasons


def extract_recent_zero_alerts(
    live_payload: dict,
    now: datetime | None = None,
    window_minutes: float = 5.0,
    alert_types: tuple[str, ...] = DEFAULT_ALERT_TYPES,
) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    alerts: list[dict] = []
    if not live_payload.get("has_live_watch"):
        return alerts
    for item in live_payload.get("recent_activity") or []:
        if not isinstance(item, dict) or item.get("type") not in alert_types:
            continue
        at = parse_iso(item.get("at"))
        if at is None:
            continue
        age_minutes = (now - at).total_seconds() / 60
        if age_minutes <= window_minutes:
            alerts.append(
                {
                    "route": item.get("route"),
                    "type": item.get("type"),
                    "at": item.get("at"),
                    "watch_date": item.get("watch_date"),
                    "details": item.get("details") or {},
                }
            )
    alerts.sort(key=lambda item: item.get("at") or "", reverse=True)
    return alerts


def fetch_json(base_url: str, path: str, timeout: float = 15.0) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watchdog du worker live + alertes 0 EUR recentes.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"backend (defaut: {DEFAULT_BASE_URL})")
    parser.add_argument("--max-age-minutes", type=float, default=5.0, help="age max du heartbeat (defaut: 5)")
    parser.add_argument("--alert-window-minutes", type=float, default=None, help="fenetre des alertes 0 EUR (defaut: max-age)")
    parser.add_argument("--json", action="store_true", help="sortie JSON")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    alert_window = args.alert_window_minutes if args.alert_window_minutes is not None else args.max_age_minutes

    try:
        heartbeat = fetch_json(args.base_url, "/api/live-worker/latest")
        live = fetch_json(args.base_url, "/api/live-watch/latest")
    except Exception as error:
        print(f"ERREUR backend {args.base_url} injoignable : {error}")
        return 1

    worker_ok, reasons = evaluate_worker(heartbeat, now=now, max_age_minutes=args.max_age_minutes)
    alerts = extract_recent_zero_alerts(live, now=now, window_minutes=alert_window)

    report = {
        "checked_at": now.isoformat(),
        "base_url": args.base_url,
        "worker_ok": worker_ok,
        "worker_reasons": reasons,
        "alert_count": len(alerts),
        "alerts": alerts,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = "OK" if worker_ok else "KO"
        print(f"[{report['checked_at']}] worker {status} (backend {args.base_url})")
        for reason in reasons:
            print(f"  - {reason}")
        for alert in alerts:
            details = alert["details"]
            extra = ""
            if alert["type"] == "zero_added":
                extra = f" {details.get('count', 0)} train(s)"
            elif alert["type"] == "zero_day_added":
                extra = f" {details.get('count', 0)} jour(s) {details.get('days', [])}"
            print(f"  ALERTE {alert['type']} | {alert.get('route')} | {alert.get('watch_date')} | {alert.get('at')}{extra}")

    if not worker_ok:
        return 1
    if alerts:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
