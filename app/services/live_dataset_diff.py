from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from app.services.data_loader import MAX_COLUMN_CANDIDATES
from app.utils import normalize_header, normalize_text


TRAVEL_ID_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2})(?::\d{2})?(?:[.,]\d+)?Z?_(?P<train_no>[A-Za-z0-9]+)$"
)

STATUS_ZERO = "in_dataset_zero"
STATUS_PRESENT_NOT_ZERO = "in_dataset_present_not_zero"
STATUS_MISSING = "not_in_dataset"


def parse_travel_id(travel_id: object) -> dict | None:
    if not isinstance(travel_id, str):
        return None
    match = TRAVEL_ID_RE.match(travel_id.strip())
    if not match:
        return None
    return {
        "date": match.group("date"),
        "time": match.group("time"),
        "train_no": match.group("train_no"),
    }


def load_tgvmax_csv(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str, sep=None, engine="python", encoding="utf-8-sig")
    raw.columns = [normalize_header(column) for column in raw.columns]

    def pick(candidates: list[str]) -> str | None:
        for candidate in candidates:
            if candidate in raw.columns:
                return candidate
        return None

    column_map = {
        canonical: pick(candidates) for canonical, candidates in MAX_COLUMN_CANDIDATES.items()
    }
    required = ["date", "origin", "destination", "depart_time", "arrive_time", "availability"]
    missing = [name for name in required if column_map[name] is None]
    if missing:
        raise ValueError(f"Colonnes tgvmax introuvables: {', '.join(missing)}")

    def read_optional(canonical: str) -> pd.Series:
        column = column_map[canonical]
        if column is None:
            return pd.Series([""] * len(raw), index=raw.index, dtype=str)
        return raw[column].fillna("").astype(str).str.strip()

    availability = raw[column_map["availability"]].fillna("").astype(str).str.strip()
    trips = pd.DataFrame(
        {
            "date": raw[column_map["date"]].fillna("").astype(str).str.strip(),
            "train_no": read_optional("train_no"),
            "origin": raw[column_map["origin"]].fillna("").astype(str).str.strip(),
            "destination": raw[column_map["destination"]].fillna("").astype(str).str.strip(),
            "depart_time": raw[column_map["depart_time"]].fillna("").astype(str).str.strip(),
            "arrive_time": raw[column_map["arrive_time"]].fillna("").astype(str).str.strip(),
            "is_zero": availability.map(
                lambda value: normalize_text(value) in {"OUI", "YES", "TRUE", "1", "AVAILABLE"}
            ),
        }
    )
    return trips[(trips["origin"] != "") & (trips["destination"] != "")].reset_index(drop=True)


class DatasetIndex:
    def __init__(self, trips: pd.DataFrame):
        self.by_train: dict[tuple[str, str], dict] = {}
        self.by_time: dict[tuple[str, str], list[dict]] = {}
        for row in trips.itertuples(index=False):
            train_no = str(getattr(row, "train_no", "") or "").strip()
            date = str(getattr(row, "date", "") or "")
            depart_time = str(getattr(row, "depart_time", "") or "")
            record = {
                "date": date,
                "train_no": train_no or None,
                "origin": str(getattr(row, "origin", "") or ""),
                "destination": str(getattr(row, "destination", "") or ""),
                "depart_time": depart_time,
                "arrive_time": str(getattr(row, "arrive_time", "") or ""),
                "is_zero": bool(getattr(row, "is_zero", False)),
            }
            if date and train_no:
                self.by_train.setdefault((date, train_no), record)
            if date and depart_time:
                self.by_time.setdefault((date, depart_time), []).append(record)

    def classify(
        self,
        *,
        travel_id: object = None,
        watch_date: object = None,
        departure_time: object = None,
        origin: object = None,
        destination: object = None,
    ) -> tuple[str, dict | None]:
        parsed = parse_travel_id(travel_id)
        if parsed:
            record = self.by_train.get((parsed["date"], parsed["train_no"]))
            if record is not None:
                return (STATUS_ZERO if record["is_zero"] else STATUS_PRESENT_NOT_ZERO), record
            return STATUS_MISSING, None

        date = str(watch_date or "")[:10]
        time = str(departure_time or "")[:5]
        candidates = self.by_time.get((date, time), []) if date and time else []
        if not candidates:
            return STATUS_MISSING, None

        origin_norm = normalize_text(str(origin or ""))
        destination_norm = normalize_text(str(destination or ""))
        for record in candidates:
            if origin_norm and origin_norm not in normalize_text(record["origin"]):
                continue
            if destination_norm and destination_norm not in normalize_text(record["destination"]):
                continue
            return (STATUS_ZERO if record["is_zero"] else STATUS_PRESENT_NOT_ZERO), record

        record = candidates[0]
        return (STATUS_ZERO if record["is_zero"] else STATUS_PRESENT_NOT_ZERO), record


def diff_live_against_dataset(live_payload: dict, trips: pd.DataFrame) -> dict:
    if not live_payload.get("has_live_watch"):
        return {
            "has_live_watch": False,
            "message": live_payload.get("message") or "aucune surveillance live enregistree",
            "captured_at": None,
            "dataset": {"row_count": len(trips), "zero_count": 0},
            "summary": {"live_zero_offer_count": 0, STATUS_ZERO: 0, STATUS_PRESENT_NOT_ZERO: 0, STATUS_MISSING: 0},
            "routes": [],
        }

    index = DatasetIndex(trips)
    counts = {STATUS_ZERO: 0, STATUS_PRESENT_NOT_ZERO: 0, STATUS_MISSING: 0}
    routes = []

    for watch in live_payload.get("watches") or []:
        offers = [offer for offer in (watch.get("zero_offers") or []) if isinstance(offer, dict)]
        items = []
        for offer in offers:
            travel_id = offer.get("travelId") or offer.get("travel_id")
            departure_time = offer.get("departureTime") or offer.get("departure_time")
            status, matched = index.classify(
                travel_id=travel_id,
                watch_date=watch.get("watch_date"),
                departure_time=departure_time,
                origin=offer.get("origin"),
                destination=offer.get("destination"),
            )
            counts[status] += 1
            items.append(
                {
                    "travel_id": travel_id,
                    "departure_time": departure_time,
                    "arrival_time": offer.get("arrivalTime") or offer.get("arrival_time"),
                    "origin": offer.get("origin"),
                    "destination": offer.get("destination"),
                    "offer_title": offer.get("offerTitle") or offer.get("offer_title"),
                    "fare_names": offer.get("fareNames") or offer.get("fare_names") or [],
                    "dataset_status": status,
                    "matched_dataset_row": matched,
                }
            )
        not_in_dataset = [item for item in items if item["dataset_status"] == STATUS_MISSING]
        routes.append(
            {
                "route": f'{watch.get("origin_label") or "?"} → {watch.get("destination_label") or "?"}',
                "watch_date": watch.get("watch_date"),
                "zero_offer_count": len(items),
                "not_in_dataset_count": len(not_in_dataset),
                "offers": items,
                "not_in_dataset": not_in_dataset,
            }
        )

    routes.sort(key=lambda item: (item["route"], item.get("watch_date") or ""))
    return {
        "has_live_watch": True,
        "captured_at": live_payload.get("captured_at"),
        "dataset": {
            "row_count": len(trips),
            "zero_count": int(trips["is_zero"].sum()) if len(trips) else 0,
        },
        "summary": {"live_zero_offer_count": sum(counts.values()), **counts},
        "routes": routes,
    }
