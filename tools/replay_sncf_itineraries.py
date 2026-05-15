from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.sncf_replay import (
    build_replay_template,
    replay_itineraries,
    summarize_replay_response,
    update_template_trip,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rejoue un appel SNCF Connect itineraries a partir d'un export probe."
    )
    parser.add_argument("probe_file", type=Path, help="Chemin vers le fichier sncf-probe-*.json")
    parser.add_argument(
        "--event-index",
        type=int,
        default=-1,
        help="Index de l'evenement itineraries a utiliser parmi ceux du probe. Defaut: le dernier.",
    )
    parser.add_argument("--origin-id")
    parser.add_argument("--origin-label")
    parser.add_argument("--destination-id")
    parser.add_argument("--destination-label")
    parser.add_argument(
        "--outward-datetime",
        help="Nouvelle date/heure ISO ex: 2026-05-18T15:38:00.000Z",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute vraiment le POST vers SNCF Connect. Sans ce flag, affiche juste le template.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    template = build_replay_template(args.probe_file, event_index=args.event_index)
    template = update_template_trip(
        template,
        origin_id=args.origin_id,
        origin_label=args.origin_label,
        destination_id=args.destination_id,
        destination_label=args.destination_label,
        outward_datetime_iso=args.outward_datetime,
    )

    if not args.execute:
        printable = {
            "source_path": str(template.source_path),
            "event_index": template.event_index,
            "url": template.url,
            "headers": template.headers,
            "body": template.body,
        }
        print(json.dumps(printable, ensure_ascii=False, indent=2))
        return 0

    payload = replay_itineraries(template)
    summary = summarize_replay_response(template, payload)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
