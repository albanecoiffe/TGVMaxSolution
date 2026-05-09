from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

import pandas as pd
import requests

from app.config import Settings
from app.models import DataBundle, StationRecord
from app.utils import normalize_header, normalize_text, parse_coord_string


MAX_COLUMN_CANDIDATES = {
    "date": ["date"],
    "train_no": ["train_no", "train", "numero_train"],
    "origin": ["origine", "origin"],
    "destination": ["destination"],
    "depart_time": ["heure_depart", "departure_time"],
    "arrive_time": ["heure_arrivee", "arrival_time"],
    "availability": ["od_happy_card", "happy_card", "max_disponible", "availability"],
    "axis": ["axe", "axis"],
    "entity": ["entity", "entite"],
}

STATION_PROPERTY_CANDIDATES = {
    "name": ["nom_gare", "nom", "name"],
    "trigram": ["trigramme", "trigram", "libellecourt"],
    "commune": ["commune", "nom_commune", "libelle_commune", "city"],
    "code_uic": ["code_uic", "codes_uic", "uic"],
    "coords": ["position_geographique", "position", "coordonnees"],
}


class DataRepository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._bundle: DataBundle | None = None
        self._lock = Lock()

    def get_bundle(self, force_refresh: bool = False) -> DataBundle:
        with self._lock:
            if force_refresh:
                self._refresh_files(force=True)
                self._bundle = None
            if self._bundle is not None:
                if not self._files_stale():
                    return self._bundle
                self._refresh_files(force=False)
                self._bundle = None
            if self._bundle is None:
                self._refresh_files(force=False)
                self._bundle = self._build_bundle()
            return self._bundle

    def refresh(self) -> DataBundle:
        return self.get_bundle(force_refresh=True)

    def _build_bundle(self) -> DataBundle:
        trips = self._load_tgvmax()
        stations = self._load_stations()
        station_names = sorted(stations.keys())
        return DataBundle(
            trips=trips,
            stations=stations,
            station_names=station_names,
            generated_at=datetime.now(),
        )

    def _files_stale(self) -> bool:
        max_age = timedelta(hours=self.settings.refresh_hours)
        cache_files = [
            self.settings.tgvmax_cache_file,
            self.settings.stations_cache_file,
        ]
        now = datetime.now()
        for cache_file in cache_files:
            if not cache_file.exists():
                return True
            modified = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if now - modified > max_age:
                return True
        return False

    def _refresh_files(self, force: bool) -> None:
        self.settings.cache_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_file(
            self.settings.tgvmax_url,
            self.settings.tgvmax_cache_file,
            force=force,
        )
        self._ensure_file(
            self.settings.stations_url,
            self.settings.stations_cache_file,
            force=force,
        )

    def _ensure_file(self, url: str, destination: Path, force: bool) -> None:
        if destination.exists() and not force and not self._files_stale():
            return
        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()
        except requests.RequestException:
            if destination.exists():
                return
            raise
        destination.write_bytes(response.content)

    def _load_tgvmax(self) -> pd.DataFrame:
        raw = pd.read_csv(
            self.settings.tgvmax_cache_file,
            dtype=str,
            sep=None,
            engine="python",
            encoding="utf-8-sig",
        )
        raw.columns = [normalize_header(column) for column in raw.columns]

        column_map = {
            canonical: self._pick_column(raw.columns, candidates)
            for canonical, candidates in MAX_COLUMN_CANDIDATES.items()
        }

        required = ["date", "origin", "destination", "depart_time", "arrive_time", "availability"]
        missing = [name for name in required if column_map[name] is None]
        if missing:
            raise ValueError(f"Colonnes tgvmax introuvables: {', '.join(missing)}")

        trips = pd.DataFrame(
            {
                "date": raw[column_map["date"]].fillna("").astype(str),
                "train_no": self._read_optional(raw, column_map["train_no"]),
                "axis": self._read_optional(raw, column_map["axis"]),
                "entity": self._read_optional(raw, column_map["entity"]),
                "origin": raw[column_map["origin"]].fillna("").astype(str).str.strip(),
                "destination": raw[column_map["destination"]].fillna("").astype(str).str.strip(),
                "depart_time": raw[column_map["depart_time"]].fillna("").astype(str).str.strip(),
                "arrive_time": raw[column_map["arrive_time"]].fillna("").astype(str).str.strip(),
                "availability_raw": raw[column_map["availability"]].fillna("").astype(str).str.strip(),
            }
        )

        trips = trips[(trips["origin"] != "") & (trips["destination"] != "")]
        trips["origin_norm"] = trips["origin"].map(normalize_text)
        trips["destination_norm"] = trips["destination"].map(normalize_text)
        trips["is_zero"] = trips["availability_raw"].map(self._availability_to_bool)
        trips["depart_dt"] = pd.to_datetime(
            trips["date"] + " " + trips["depart_time"], errors="coerce"
        )
        trips["arrive_dt"] = pd.to_datetime(
            trips["date"] + " " + trips["arrive_time"], errors="coerce"
        )
        overnight_mask = trips["arrive_dt"] < trips["depart_dt"]
        trips.loc[overnight_mask, "arrive_dt"] = (
            trips.loc[overnight_mask, "arrive_dt"] + pd.Timedelta(days=1)
        )
        trips = trips.dropna(subset=["depart_dt", "arrive_dt"])
        trips = trips.sort_values(["date", "depart_dt", "origin", "destination"]).reset_index(
            drop=True
        )
        return trips

    def _load_stations(self) -> dict[str, StationRecord]:
        geojson = json.loads(self.settings.stations_cache_file.read_text(encoding="utf-8"))
        features = geojson.get("features", [])
        stations: dict[str, StationRecord] = {}

        for feature in features:
            properties = feature.get("properties", {})
            normalized_props = {normalize_header(key): value for key, value in properties.items()}

            name = self._pick_value(normalized_props, STATION_PROPERTY_CANDIDATES["name"])
            if not name:
                continue

            latitude = longitude = None
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates") or []
            if len(coordinates) >= 2:
                longitude = coordinates[0]
                latitude = coordinates[1]
            if latitude is None or longitude is None:
                coord_value = self._pick_value(
                    normalized_props,
                    STATION_PROPERTY_CANDIDATES["coords"],
                )
                latitude, longitude = parse_coord_string(coord_value)
            if latitude is None or longitude is None:
                continue

            station = StationRecord(
                name=str(name).strip(),
                latitude=float(latitude),
                longitude=float(longitude),
                commune=self._pick_value(normalized_props, STATION_PROPERTY_CANDIDATES["commune"]),
                trigram=self._pick_value(normalized_props, STATION_PROPERTY_CANDIDATES["trigram"]),
                code_uic=self._pick_value(normalized_props, STATION_PROPERTY_CANDIDATES["code_uic"]),
            )
            stations[station.name] = station
        return stations

    @staticmethod
    def _pick_column(columns: pd.Index, candidates: list[str]) -> str | None:
        normalized = {normalize_header(column): column for column in columns}
        for candidate in candidates:
            if candidate in normalized:
                return normalized[candidate]
        return None

    @staticmethod
    def _pick_value(properties: dict[str, object], candidates: list[str]) -> str | None:
        for candidate in candidates:
            value = properties.get(candidate)
            if value not in (None, ""):
                return str(value)
        return None

    @staticmethod
    def _read_optional(frame: pd.DataFrame, column: str | None) -> pd.Series:
        if column is None:
            return pd.Series([""] * len(frame), index=frame.index, dtype=str)
        return frame[column].fillna("").astype(str)

    @staticmethod
    def _availability_to_bool(value: str) -> bool:
        normalized = normalize_text(value)
        return normalized in {"OUI", "YES", "TRUE", "1", "AVAILABLE"}
