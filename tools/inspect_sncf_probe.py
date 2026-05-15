from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.sncf_probe import summarize_probe_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspecte un export SNCF probe et resume les appels itineraries."
    )
    parser.add_argument("probe_file", type=Path, help="Chemin vers le fichier sncf-probe-*.json")
    parser.add_argument(
        "--write-redacted",
        action="store_true",
        help="Ecrit aussi une copie redigee a cote du fichier source.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    summary = summarize_probe_file(args.probe_file)
    printable = {
        "path": summary["path"],
        "event_count": summary["event_count"],
        "urls": summary["urls"],
        "itinerary_event_count": summary["itinerary_event_count"],
        "itinerary_summaries": summary["itinerary_summaries"],
    }
    print(json.dumps(printable, ensure_ascii=False, indent=2))

    if args.write_redacted:
        output_path = args.probe_file.with_name(f"{args.probe_file.stem}.redacted.json")
        output_path.write_text(
            json.dumps(summary["redacted_events"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nCopie redigee ecrite dans {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
