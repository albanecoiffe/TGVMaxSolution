from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from app.config import Settings


class LiveWatchPlanStore:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def latest_file(self) -> Path:
        return self.settings.history_dir / "latest-live-watch-plan.json"

    def latest(self) -> dict:
        payload = self._load_json(self.latest_file)
        if payload is not None:
            return payload
        return {
            "has_plan": False,
            "message": "aucun plan de surveillance live n'a encore ete configure",
            "watches": [],
        }

    def save(self, payload: dict) -> dict:
        self.settings.history_dir.mkdir(parents=True, exist_ok=True)
        self.latest_file.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        return payload

    def clear(self) -> dict:
        payload = {
            "has_plan": False,
            "message": "plan de surveillance supprime",
            "watches": [],
        }
        return self.save(payload)

    def build_full_month_plan(
        self,
        origin_label: str,
        destination_label: str,
        available_dates: list[str],
        include_return: bool = False,
        dates: list[str] | None = None,
    ) -> dict:
        if dates:
            selected_dates = sorted({str(value)[:10] for value in dates})
        else:
            today = date.today()
            max_date = today + timedelta(days=31)
            selected_dates = sorted(
                {
                    raw_value
                    for raw_value in available_dates
                    if today <= date.fromisoformat(raw_value) <= max_date
                }
            )

        watches = []
        for candidate in selected_dates:
            watches.append(
                {
                    "id": f"{origin_label}|{destination_label}|{candidate}",
                    "origin_label": origin_label,
                    "destination_label": destination_label,
                    "watch_date": candidate,
                    "rule_label": "full_month",
                }
            )
            if include_return:
                watches.append(
                    {
                        "id": f"{destination_label}|{origin_label}|{candidate}",
                        "origin_label": destination_label,
                        "destination_label": origin_label,
                        "watch_date": candidate,
                        "rule_label": "full_month_return",
                    }
                )

        payload = {
            "has_plan": True,
            "source": f"full_month_{origin_label}_{destination_label}",
            "generated_at": date.today().isoformat(),
            "watch_count": len(watches),
            "watches": watches,
            "message": (
                f"plan full month {origin_label} -> {destination_label} "
                f"sur {len(selected_dates)} date(s) a partir des dates fournies"
            ),
        }
        return self.save(payload)

    def build_default_weekend_plan(self, available_dates: list[str]) -> dict:
        today = date.today()
        max_date = today + timedelta(days=31)
        watches = []

        for raw_value in available_dates:
            candidate = date.fromisoformat(raw_value)
            if candidate < today or candidate > max_date:
                continue

            if candidate.weekday() in {4, 5}:
                watches.append(
                    {
                        "id": f"Paris Montparnasse|Bordeaux Saint-Jean|{candidate.isoformat()}",
                        "origin_label": "Paris Montparnasse",
                        "destination_label": "Bordeaux Saint-Jean",
                        "watch_date": candidate.isoformat(),
                        "rule_label": "weekend_bordeaux",
                    }
                )
            elif candidate.weekday() in {6, 0}:
                watches.append(
                    {
                        "id": f"Bordeaux Saint-Jean|Paris Montparnasse|{candidate.isoformat()}",
                        "origin_label": "Bordeaux Saint-Jean",
                        "destination_label": "Paris Montparnasse",
                        "watch_date": candidate.isoformat(),
                        "rule_label": "retour_paris",
                    }
                )

        payload = {
            "has_plan": True,
            "source": "default_weekend_bordeaux_paris",
            "generated_at": date.today().isoformat(),
            "watch_count": len(watches),
            "watches": watches,
            "message": "plan weekend Bordeaux/Paris sur 1 mois genere a partir des dates disponibles tgvmax",
        }
        return self.save(payload)

    def _load_json(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
