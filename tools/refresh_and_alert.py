"""Refresh du dataset tgvmax sur le backend deploye + alerte nouveaux trains 0 EUR.

Concu pour tourner gratuitement en GitHub Actions (cron, repo public) :

1. POST /api/refresh  -> recharge le dataset open data tgvmax cote backend (Render)
   et enregistre un snapshot + diff zero_watch ;
2. GET /api/watch/latest -> lit le diff (new_zero_count, sample_new_trips...) ;
3. si des nouveaux trains 0 EUR apparaissent et ALERT_ON_NEW_ZERO=true (variable
   de repo GitHub), ouvre une issue GitHub avec la liste (notification par mail).

Granularite : celle de la publication SNCF (1x/jour, debut de matinee) — ce n'est
PAS du temps reel (le temps reel necessite une session navigateur, voir
tools/live_worker/). Mais c'est 24/7, gratuit, et sans aucune machine chez toi.

Usage local :

    python3 tools/refresh_and_alert.py --base-url https://ton-app.onrender.com
    python3 tools/refresh_and_alert.py --base-url https://ton-app.onrender.com --no-issue

Stdlib uniquement.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone


DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def fetch_json(base_url: str, path: str, timeout: float = 60.0) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(base_url: str, path: str, payload: dict | None = None, timeout: float = 180.0) -> dict:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def summarize_watch(watch: dict, base_url: str) -> dict:
    zero_watch = watch.get("zero_watch") or {}
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "has_snapshot": bool(zero_watch.get("has_snapshot")),
        "generated_at": zero_watch.get("generated_at"),
        "current_zero_count": zero_watch.get("current_zero_count", 0),
        "previous_zero_count": zero_watch.get("previous_zero_count"),
        "new_zero_count": zero_watch.get("new_zero_count", 0),
        "removed_zero_count": zero_watch.get("removed_zero_count", 0),
        "sample_new_trips": zero_watch.get("sample_new_trips") or [],
        "sample_removed_trips": zero_watch.get("sample_removed_trips") or [],
    }


def _trip_line(trip: dict) -> str:
    return (
        f"- `{trip.get('date')}` train {trip.get('train_no') or '?'} : "
        f"{trip.get('origin')} -> {trip.get('destination')} "
        f"({trip.get('departure_time')} -> {trip.get('arrival_time')})"
    )


def build_issue_body(summary: dict) -> tuple[str, str]:
    new_trips = summary["sample_new_trips"]
    trip_lines = [_trip_line(trip) for trip in new_trips] or ["- aucun"]
    title = f"[{summary['new_zero_count']} nouveau(x) train(s) 0 EUR] dataset du {summary.get('generated_at') or 'jour'}"
    lines = [
        f"Diff zero_watch du {summary['checked_at']} sur {summary['base_url']}",
        "",
        f"- dataset genere le : {summary.get('generated_at')}",
        f"- trains 0 EUR actuels : {summary['current_zero_count']} (precedent : {summary.get('previous_zero_count')})",
        f"- **nouveaux : {summary['new_zero_count']}** | retires : {summary['removed_zero_count']}",
        "",
        "Nouveaux trains a 0 EUR (echantillon) :",
        *trip_lines,
        "",
        "Verifier sur SNCF Connect avant de reserver (les places partent vite).",
    ]
    return title, "\n".join(lines)


def maybe_create_issue(summary: dict, repo: str) -> bool:
    if os.environ.get("ALERT_ON_NEW_ZERO", "").lower() not in {"1", "true", "yes"}:
        return False
    if summary["new_zero_count"] <= 0:
        return False
    title, body = build_issue_body(summary)
    body_file = "/tmp/zero-issue-body.md"
    with open(body_file, "w", encoding="utf-8") as handle:
        handle.write(body)
    result = subprocess.run(
        ["gh", "issue", "create", "--repo", repo, "--title", title, "--body-file", body_file],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERREUR creation issue : {result.stderr.strip()}")
        return False
    print(f"Issue creee : {result.stdout.strip()}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh dataset tgvmax + alerte nouveaux 0 EUR (CI).")
    parser.add_argument("--base-url", default=os.environ.get("RENDER_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--no-issue", action="store_true", help="ne jamais ouvrir d'issue GitHub")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    try:
        refresh = post_json(base_url, "/api/refresh")
        watch = fetch_json(base_url, "/api/watch/latest")
    except Exception as error:
        print(f"ERREUR backend {base_url} injoignable : {error}")
        return 1

    summary = summarize_watch({"zero_watch": refresh.get("zero_watch") or watch}, base_url)
    summary["zero_watch_source"] = "refresh" if refresh.get("zero_watch") else "watch/latest"

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if not args.no_issue:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if repo and os.environ.get("GH_TOKEN"):
            maybe_create_issue(summary, repo)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
