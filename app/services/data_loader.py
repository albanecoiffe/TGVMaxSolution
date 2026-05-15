from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from zipfile import ZipFile

import pandas as pd
import requests

from app.config import Settings
from app.models import DataBundle, StationRecord
from app.utils import normalize_header, normalize_text, parse_coord_string, parse_gtfs_time_to_minutes


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

    def get_bundle(self, force_refresh: bool = False, include_gtfs: bool = False) -> DataBundle:
        with self._lock:
            if force_refresh:
                self._refresh_files(force=True, include_gtfs=include_gtfs)
                self._bundle = None
            if self._bundle is not None:
                if not self._files_stale(include_gtfs=include_gtfs):
                    if include_gtfs and self._bundle.rail_segments is None:
                        self._refresh_files(force=False, include_gtfs=True)
                        self._attach_gtfs(self._bundle)
                    return self._bundle
                self._refresh_files(force=False, include_gtfs=include_gtfs)
                self._bundle = None
            if self._bundle is None:
                self._refresh_files(force=False, include_gtfs=include_gtfs)
                self._bundle = self._build_bundle(include_gtfs=include_gtfs)
            return self._bundle

    def refresh(self) -> DataBundle:
        return self.get_bundle(force_refresh=True)

    def _build_bundle(self, include_gtfs: bool = False) -> DataBundle:
        trips = self._load_tgvmax()
        stations = self._load_stations()
        rail_segments = rail_stops = rail_calendar = rail_exceptions = None
        if include_gtfs:
            rail_segments, rail_stops, rail_calendar, rail_exceptions = self._load_sncf_gtfs()
        station_names = sorted(stations.keys())
        return DataBundle(
            trips=trips,
            stations=stations,
            station_names=station_names,
            generated_at=datetime.now(),
            rail_segments=rail_segments,
            rail_stops=rail_stops,
            rail_calendar=rail_calendar,
            rail_exceptions=rail_exceptions,
        )

    def has_gtfs_cache(self) -> bool:
        return self.settings.sncf_gtfs_cache_file.exists()

    def _attach_gtfs(self, bundle: DataBundle) -> None:
        rail_segments, rail_stops, rail_calendar, rail_exceptions = self._load_sncf_gtfs()
        bundle.rail_segments = rail_segments
        bundle.rail_stops = rail_stops
        bundle.rail_calendar = rail_calendar
        bundle.rail_exceptions = rail_exceptions

    def _files_stale(self, include_gtfs: bool = False) -> bool:
        max_age = timedelta(hours=self.settings.refresh_hours)
        cache_files = [
            self.settings.tgvmax_cache_file,
            self.settings.stations_cache_file,
        ]
        if include_gtfs:
            cache_files.append(self.settings.sncf_gtfs_cache_file)
        now = datetime.now()
        for cache_file in cache_files:
            if not cache_file.exists():
                return True
            modified = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if now - modified > max_age:
                return True
        return False

    def _refresh_files(self, force: bool, include_gtfs: bool = False) -> None:
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
        if include_gtfs:
            self._ensure_file(
                self.settings.sncf_gtfs_url,
                self.settings.sncf_gtfs_cache_file,
                force=force,
                optional=True,
            )

    def _ensure_file(self, url: str, destination: Path, force: bool, optional: bool = False) -> None:
        if destination.exists() and not force and not self._files_stale():
            return
        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()
        except requests.RequestException:
            if destination.exists():
                return
            if optional:
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

    def _load_sncf_gtfs(
        self,
    ) -> tuple[pd.DataFrame | None, dict[str, StationRecord] | None, pd.DataFrame | None, pd.DataFrame | None]:
        archive_path = self.settings.sncf_gtfs_cache_file
        if not archive_path.exists():
            return None, None, None, None

        try:
            with ZipFile(archive_path) as archive:
                stops = self._read_gtfs_csv(
                    archive,
                    "stops.txt",
                    ["stop_id", "stop_name", "stop_lat", "stop_lon"],
                )
                trips = self._read_gtfs_csv(
                    archive,
                    "trips.txt",
                    ["trip_id", "route_id", "service_id", "trip_headsign"],
                )
                stop_times = self._read_gtfs_csv(
                    archive,
                    "stop_times.txt",
                    ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
                )
                routes = self._read_gtfs_csv(
                    archive,
                    "routes.txt",
                    ["route_id", "route_short_name", "route_long_name", "route_type"],
                )
                calendar = self._read_gtfs_csv(
                    archive,
                    "calendar.txt",
                    [
                        "service_id",
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                        "start_date",
                        "end_date",
                    ],
                    required=False,
                )
                calendar_dates = self._read_gtfs_csv(
                    archive,
                    "calendar_dates.txt",
                    ["service_id", "date", "exception_type"],
                    required=False,
                )
        except (KeyError, ValueError, OSError):
            return None, None, None, None

        if stops.empty or trips.empty or stop_times.empty:
            return None, None, None, None

        stop_lookup = (
            stops[["stop_id", "stop_name", "stop_lat", "stop_lon"]]
            .dropna(subset=["stop_id", "stop_name"])
            .copy()
        )
        stop_lookup["stop_name"] = stop_lookup["stop_name"].astype(str).str.strip()
        stop_lookup["stop_lat"] = pd.to_numeric(stop_lookup["stop_lat"], errors="coerce")
        stop_lookup["stop_lon"] = pd.to_numeric(stop_lookup["stop_lon"], errors="coerce")

        rail_stops: dict[str, StationRecord] = {}
        grouped_stops = stop_lookup.dropna(subset=["stop_lat", "stop_lon"]).groupby("stop_name", as_index=False)
        for row in grouped_stops.agg({"stop_lat": "mean", "stop_lon": "mean"}).itertuples(index=False):
            rail_stops[row.stop_name] = StationRecord(
                name=row.stop_name,
                latitude=float(row.stop_lat),
                longitude=float(row.stop_lon),
            )

        stop_times = stop_times.dropna(subset=["trip_id", "stop_id", "departure_time", "arrival_time"]).copy()
        stop_times["stop_sequence"] = pd.to_numeric(stop_times["stop_sequence"], errors="coerce")
        stop_times = stop_times.dropna(subset=["stop_sequence"]).sort_values(["trip_id", "stop_sequence"])
        stop_times["departure_minutes"] = stop_times["departure_time"].map(parse_gtfs_time_to_minutes)
        stop_times["arrival_minutes"] = stop_times["arrival_time"].map(parse_gtfs_time_to_minutes)
        stop_times = stop_times.dropna(subset=["departure_minutes", "arrival_minutes"])
        stop_times = stop_times.merge(stop_lookup[["stop_id", "stop_name"]], on="stop_id", how="left")
        stop_times = stop_times.dropna(subset=["stop_name"])

        segments = stop_times[["trip_id", "stop_name", "departure_minutes", "stop_sequence"]].copy()
        segments["next_stop_name"] = stop_times.groupby("trip_id")["stop_name"].shift(-1)
        segments["next_arrival_minutes"] = stop_times.groupby("trip_id")["arrival_minutes"].shift(-1)
        segments["next_trip_id"] = stop_times.groupby("trip_id")["trip_id"].shift(-1)
        segments = segments[segments["trip_id"] == segments["next_trip_id"]].copy()
        segments = segments.dropna(subset=["next_stop_name", "next_arrival_minutes"])
        segments = segments.rename(
            columns={
                "stop_name": "from_stop_name",
                "next_stop_name": "to_stop_name",
            }
        )
        segments = segments.merge(
            trips[["trip_id", "route_id", "service_id", "trip_headsign"]],
            on="trip_id",
            how="left",
        )
        if not routes.empty:
            segments = segments.merge(
                routes[["route_id", "route_short_name", "route_long_name", "route_type"]],
                on="route_id",
                how="left",
            )
        else:
            segments["route_short_name"] = ""
            segments["route_long_name"] = ""
            segments["route_type"] = ""
        segments["label"] = (
            segments["route_short_name"].fillna("").astype(str).str.strip()
        )
        empty_label_mask = segments["label"] == ""
        segments.loc[empty_label_mask, "label"] = (
            segments.loc[empty_label_mask, "trip_headsign"].fillna("").astype(str).str.strip()
        )
        empty_label_mask = segments["label"] == ""
        segments.loc[empty_label_mask, "label"] = (
            segments.loc[empty_label_mask, "route_long_name"].fillna("").astype(str).str.strip()
        )
        segments["mode"] = segments["route_type"].map(self._gtfs_route_type_label).fillna("Train")
        segments = segments[
            [
                "trip_id",
                "service_id",
                "from_stop_name",
                "to_stop_name",
                "departure_minutes",
                "next_arrival_minutes",
                "stop_sequence",
                "label",
                "mode",
            ]
        ].rename(columns={"next_arrival_minutes": "arrival_minutes"})
        segments = segments.dropna(subset=["service_id"])
        segments = segments.sort_values(
            ["from_stop_name", "departure_minutes", "arrival_minutes", "to_stop_name"]
        ).reset_index(drop=True)

        if calendar is not None and not calendar.empty:
            calendar = calendar.copy()
            calendar["start_date"] = pd.to_datetime(calendar["start_date"], format="%Y%m%d", errors="coerce")
            calendar["end_date"] = pd.to_datetime(calendar["end_date"], format="%Y%m%d", errors="coerce")
        else:
            calendar = None
        if calendar_dates is not None and not calendar_dates.empty:
            calendar_dates = calendar_dates.copy()
            calendar_dates["date"] = pd.to_datetime(calendar_dates["date"], format="%Y%m%d", errors="coerce")
        else:
            calendar_dates = None

        return segments, rail_stops, calendar, calendar_dates

    @staticmethod
    def _read_gtfs_csv(
        archive: ZipFile,
        filename: str,
        columns: list[str],
        required: bool = True,
    ) -> pd.DataFrame:
        member_name = DataRepository._find_archive_member(archive, filename)
        if member_name is None:
            if required:
                raise KeyError(filename)
            return pd.DataFrame(columns=columns)
        with archive.open(member_name) as handle:
            frame = pd.read_csv(handle, dtype=str)
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise ValueError(f"Colonnes GTFS introuvables dans {filename}: {', '.join(missing)}")
        return frame[columns].copy()

    @staticmethod
    def _find_archive_member(archive: ZipFile, filename: str) -> str | None:
        target = filename.lower()
        for member_name in archive.namelist():
            if member_name.lower().endswith(target):
                return member_name
        return None

    @staticmethod
    def _gtfs_route_type_label(value: object) -> str:
        labels = {
            "0": "Tram",
            "1": "Metro",
            "2": "Train",
            "3": "Bus",
            "109": "TER",
        }
        return labels.get(str(value), "Train")

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
