from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime, time
from hashlib import sha1
from heapq import heappop, heappush
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from app.config import Settings
from app.models import DataBundle, StationRecord
from app.services.data_loader import DataRepository
from app.services.navitia import NavitiaClient
from app.utils import add_minutes, duration_minutes, format_minutes, match_score, normalize_text


FRENCH_MONTH_NAMES = {
    1: "janvier",
    2: "fevrier",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "aout",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "decembre",
}


class TravelPlanner:
    def __init__(self, settings: Settings, repository: DataRepository | None = None):
        self.settings = settings
        self.repository = repository or DataRepository(settings)
        self.navitia = NavitiaClient(settings)
        self._mountains = self._load_mountains(settings.mountains_file)
        self._hybrid_cache: dict[tuple[str, str, int | None], dict] = {}
        self._local_rail_extensions_cache: dict[tuple[str, str, str, int | None], list[dict]] = {}

    def meta(self) -> dict:
        bundle = self.repository.get_bundle()
        trips = bundle.trips
        available_dates = sorted(trips["date"].dropna().unique().tolist())
        return {
            "app_name": self.settings.app_name,
            "hybrid_enabled": self._hybrid_enabled(bundle),
            "available_dates": available_dates,
            "date_min": available_dates[0] if available_dates else None,
            "date_max": available_dates[-1] if available_dates else None,
            "mountain_destinations": self._mountains,
            "live_check_default_limit": self.settings.live_check_default_limit,
            "generated_at": bundle.generated_at.isoformat(),
        }

    def refresh(self) -> dict:
        self._hybrid_cache.clear()
        self._local_rail_extensions_cache.clear()
        bundle = self.repository.refresh()
        return {
            "ok": True,
            "generated_at": bundle.generated_at.isoformat(),
            "trip_count": int(len(bundle.trips)),
            "station_count": len(bundle.stations),
        }

    def search_stations(self, query: str, limit: int = 12) -> list[dict]:
        bundle = self.repository.get_bundle()
        unique_names = set(bundle.trips["origin"].unique()) | set(bundle.trips["destination"].unique())
        scored = []
        for name in unique_names:
            score = match_score(name, query)
            if score <= 0:
                continue
            scored.append((score, name))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [{"label": name} for _, name in scored[:limit]]

    def direct_trips(
        self,
        origin_query: str,
        travel_date: date,
        return_date: date | None = None,
    ) -> dict:
        bundle = self.repository.get_bundle()
        matched_origins = self._resolve_station_query(bundle, origin_query)
        day_trips = self._day_trips(bundle, travel_date)
        direct = day_trips[
            day_trips["origin"].isin(matched_origins)
            & day_trips["is_zero"]
        ].sort_values(["destination", "depart_dt", "arrive_dt"])

        trips = []
        for row in direct.itertuples(index=False):
            trip_payload = self._serialize_trip(bundle, row)
            trip_payload["return_options"] = self._build_return_options(
                bundle=bundle,
                origin_name=row.destination,
                destination_names=matched_origins,
                earliest_departure=row.arrive_dt,
                return_date=return_date,
            )
            trips.append(trip_payload)
        destinations = self._group_destinations(bundle, direct)
        return {
            "origin_query": origin_query,
            "matched_origins": matched_origins,
            "travel_date": travel_date.isoformat(),
            "return_date": return_date.isoformat() if return_date else None,
            "trip_count": len(trips),
            "trips": trips,
            "destinations": destinations,
        }

    def day_trip_destinations(
        self,
        origin_query: str,
        travel_date: date,
        min_stay_minutes: int = 180,
        latest_return_time: str = "23:30",
        return_date: date | None = None,
    ) -> dict:
        bundle = self.repository.get_bundle()
        matched_origins = self._resolve_station_query(bundle, origin_query)
        day_trips = self._day_trips(bundle, travel_date)
        effective_return_date = return_date or travel_date
        outbound = day_trips[
            day_trips["origin"].isin(matched_origins)
            & day_trips["is_zero"]
        ]
        latest_hour, latest_minute = map(int, latest_return_time.split(":"))
        latest_return_cutoff = time(latest_hour, latest_minute)

        results = []
        for destination in sorted(outbound["destination"].unique()):
            inward = bundle.trips[
                (bundle.trips["date"] == effective_return_date.isoformat())
                & bundle.trips["origin"].eq(destination)
                & bundle.trips["destination"].isin(matched_origins)
                & bundle.trips["is_zero"]
            ]
            if inward.empty:
                continue
            best_option = None
            destination_outbound = outbound[outbound["destination"] == destination].sort_values("depart_dt")
            for outbound_row in destination_outbound.itertuples(index=False):
                valid_returns = inward[
                    inward["depart_dt"] >= add_minutes(outbound_row.arrive_dt, min_stay_minutes)
                ]
                valid_returns = valid_returns[
                    valid_returns["arrive_dt"].dt.time <= latest_return_cutoff
                ]
                if valid_returns.empty:
                    continue
                return_row = valid_returns.sort_values("arrive_dt", ascending=False).iloc[0]
                stay_minutes = duration_minutes(outbound_row.arrive_dt, return_row["depart_dt"])
                total_trip_minutes = duration_minutes(outbound_row.depart_dt, return_row["arrive_dt"])
                candidate = {
                    "destination": destination,
                    "stay_minutes": stay_minutes,
                    "stay_label": format_minutes(stay_minutes),
                    "total_trip_minutes": total_trip_minutes,
                    "total_trip_label": format_minutes(total_trip_minutes),
                    "outbound": self._serialize_trip(bundle, outbound_row),
                    "return": self._serialize_trip(bundle, return_row),
                    "coordinates": self._station_coordinates(bundle, destination),
                }
                if best_option is None or candidate["stay_minutes"] > best_option["stay_minutes"]:
                    best_option = candidate
            if best_option is not None:
                results.append(best_option)

        results.sort(key=lambda item: (-item["stay_minutes"], item["destination"]))
        return {
            "origin_query": origin_query,
            "matched_origins": matched_origins,
            "travel_date": travel_date.isoformat(),
            "return_date": effective_return_date.isoformat(),
            "results": results,
        }

    def max_itineraries(
        self,
        origin_query: str,
        travel_date: date,
        max_connections: int = 2,
        min_connection_minutes: int = 25,
        max_connection_minutes: int | None = None,
        min_connections: int = 0,
        max_results: int | None = None,
    ) -> dict:
        bundle = self.repository.get_bundle()
        matched_origins = self._resolve_station_query(bundle, origin_query)
        day_trips = self._day_trips(bundle, travel_date)
        available = day_trips[day_trips["is_zero"]].sort_values("depart_dt")
        trips_by_origin = {
            origin: group
            for origin, group in available.groupby("origin")
        }

        heap: list[tuple[datetime, str, tuple[str, ...], list[dict]]] = []
        best_arrival: dict[tuple[str, int], datetime] = {}
        itineraries = []

        for origin in matched_origins:
            heappush(heap, (datetime.combine(travel_date, time(0, 0)), origin, tuple([origin]), []))
            best_arrival[(origin, 0)] = datetime.combine(travel_date, time(0, 0))

        limit = max_results or self.settings.max_itinerary_results

        while heap and len(itineraries) < limit:
            current_time, station, visited, path = heappop(heap)
            if len(path) >= max(1, min_connections + 1):
                itineraries.append(self._serialize_path(bundle, path))
            if len(path) > max_connections:
                continue

            next_trips = trips_by_origin.get(station)
            if next_trips is None:
                continue

            for trip in next_trips.itertuples(index=False):
                minimum_departure = current_time
                maximum_departure = None
                if path:
                    minimum_departure = add_minutes(current_time, min_connection_minutes)
                    if max_connection_minutes is not None:
                        maximum_departure = add_minutes(current_time, max_connection_minutes)
                if trip.depart_dt < minimum_departure:
                    continue
                if maximum_departure is not None and trip.depart_dt > maximum_departure:
                    continue
                if trip.destination in visited:
                    continue
                new_path = path + [trip]
                depth = len(new_path)
                best_key = (trip.destination, depth)
                if best_arrival.get(best_key) and best_arrival[best_key] <= trip.arrive_dt:
                    continue
                best_arrival[best_key] = trip.arrive_dt
                heappush(
                    heap,
                    (
                        trip.arrive_dt,
                        trip.destination,
                        tuple([*visited, trip.destination]),
                        new_path,
                    ),
                )

        grouped = defaultdict(list)
        for itinerary in itineraries:
            grouped[itinerary["destination"]].append(itinerary)
        grouped_results = [
            {
                "destination": destination,
                "coordinates": self._station_coordinates(bundle, destination),
                "itineraries": sorted(
                    items,
                    key=lambda item: (
                        item["duration_minutes"],
                        item["connections"],
                        item["departure_time"],
                    ),
                )[:3],
            }
            for destination, items in grouped.items()
        ]
        grouped_results.sort(
            key=lambda item: (
                item["itineraries"][0]["duration_minutes"],
                item["destination"],
            )
        )
        return {
            "origin_query": origin_query,
            "matched_origins": matched_origins,
            "travel_date": travel_date.isoformat(),
            "results": grouped_results,
        }

    def hybrid_itineraries(
        self,
        origin_query: str,
        travel_date: date,
        max_connections: int = 2,
        min_connection_minutes: int = 25,
        max_connection_minutes: int | None = None,
    ) -> dict:
        cache_key = (normalize_text(origin_query), travel_date.isoformat(), max_connection_minutes)
        cached = self._hybrid_cache.get(cache_key)
        if cached is not None:
            return cached

        bundle = self.repository.get_bundle()
        if not self._hybrid_enabled(bundle):
            payload = {
                "enabled": False,
                "reason": "Le GTFS SNCF ouvert n'est pas disponible",
                "results": [],
            }
            self._hybrid_cache[cache_key] = payload
            return payload

        matched_origins = self._resolve_station_query(bundle, origin_query)
        day_trips = self._day_trips(bundle, travel_date)
        direct_max_trips = day_trips[
            day_trips["origin"].isin(matched_origins)
            & day_trips["is_zero"]
        ].sort_values(["destination", "arrive_dt", "depart_dt"])
        best_max_by_via_station: dict[str, dict] = {}
        best_direct_by_destination: dict[str, dict] = {}
        for row in direct_max_trips.itertuples(index=False):
            itinerary = self._serialize_path(bundle, [row])
            via_station_key = normalize_text(itinerary["destination"])
            via_existing = best_max_by_via_station.get(via_station_key)
            if (
                via_existing is None
                or itinerary["arrival_datetime"] < via_existing["arrival_datetime"]
                or (
                    itinerary["arrival_datetime"] == via_existing["arrival_datetime"]
                    and itinerary["duration_minutes"] < via_existing["duration_minutes"]
                )
            ):
                best_max_by_via_station[via_station_key] = itinerary
            destination_key = normalize_text(itinerary["destination"])
            existing = best_direct_by_destination.get(destination_key)
            if existing is None or itinerary["duration_minutes"] < existing["duration_minutes"]:
                best_direct_by_destination[destination_key] = itinerary

        combined_results = []
        seen_pairs: set[tuple[str, str]] = set()
        for itinerary in best_max_by_via_station.values():
            extensions = self._list_local_rail_extensions(
                bundle=bundle,
                origin_name=itinerary["destination"],
                departure_after=itinerary["arrival_datetime"],
                max_connection_minutes=max_connection_minutes,
                max_results_per_origin=8,
            )
            for extension in extensions:
                identity = (itinerary["destination"], extension["destination"])
                if identity in seen_pairs:
                    continue
                seen_pairs.add(identity)
                direct_max_trip = best_direct_by_destination.get(normalize_text(extension["destination"]))
                combined_results.append(
                    {
                        "destination": extension["destination"],
                        "via_max_station": itinerary["destination"],
                        "total_duration_minutes": itinerary["duration_minutes"]
                        + extension["duration_minutes"],
                        "total_duration_label": format_minutes(
                            itinerary["duration_minutes"] + extension["duration_minutes"]
                        ),
                        "max_itinerary": itinerary,
                        "ter_extension": extension,
                        "direct_max_available": direct_max_trip is not None,
                        "direct_max_trip": direct_max_trip,
                        "target_coordinates": self._hybrid_target_coordinates(
                            bundle,
                            {"name": extension["destination"]},
                        ),
                    }
                )

        combined_results.sort(
            key=lambda item: (
                item["total_duration_minutes"],
                item["via_max_station"],
                item["destination"],
            )
        )
        payload = {
            "enabled": True,
            "calculation_note": "Les prolongements TER sont calcules a partir des trains MAX directs du jour puis du GTFS SNCF ouvert.",
            "results": combined_results,
        }
        self._hybrid_cache[cache_key] = payload
        return payload

    def _day_trips(self, bundle: DataBundle, travel_date: date):
        day_trips = bundle.trips[bundle.trips["date"] == travel_date.isoformat()]
        return self._exclude_departed_trips(day_trips, travel_date)

    @staticmethod
    def _current_local_datetime() -> datetime:
        return datetime.now().astimezone().replace(tzinfo=None)

    def _exclude_departed_trips(self, trips_frame, travel_date: date):
        if trips_frame.empty:
            return trips_frame
        now = self._current_local_datetime()
        if travel_date != now.date():
            return trips_frame
        return trips_frame[trips_frame["depart_dt"] >= now]

    def _resolve_station_query(self, bundle: DataBundle, query: str) -> list[str]:
        station_names = set(bundle.trips["origin"].unique()) | set(bundle.trips["destination"].unique())
        scored = [(match_score(name, query), name) for name in station_names]
        scored = [(score, name) for score, name in scored if score > 0]
        if not scored:
            raise ValueError(f"Aucune gare ou ville trouvee pour '{query}'")
        scored.sort(key=lambda item: (-item[0], item[1]))
        top_score = scored[0][0]
        matches = [name for score, name in scored if score >= max(40, top_score - 20)]
        return sorted(matches)

    def _resolve_station(self, bundle: DataBundle, name: str) -> StationRecord | None:
        if name in bundle.stations:
            return bundle.stations[name]
        name_norm = normalize_text(name)
        exact_match = next(
            (station for station_name, station in bundle.stations.items() if normalize_text(station_name) == name_norm),
            None,
        )
        if exact_match is not None:
            return exact_match
        contains_matches = [
            station
            for station_name, station in bundle.stations.items()
            if name_norm and name_norm in normalize_text(station_name)
        ]
        if len(contains_matches) == 1:
            return contains_matches[0]
        return None

    def _hybrid_enabled(self, bundle: DataBundle) -> bool:
        return self._local_rail_enabled(bundle)

    @staticmethod
    def _local_rail_enabled(bundle: DataBundle) -> bool:
        return bool(bundle.rail_segments is not None and not bundle.rail_segments.empty)

    def _hybrid_target_coordinates(self, bundle: DataBundle, target: dict) -> dict | None:
        latitude = target.get("latitude")
        longitude = target.get("longitude")
        if latitude is not None and longitude is not None:
            return {"latitude": latitude, "longitude": longitude}
        rail_stop = self._resolve_rail_stop(bundle, target.get("name", ""))
        if rail_stop is not None:
            return {"latitude": rail_stop.latitude, "longitude": rail_stop.longitude}
        return self._station_coordinates(bundle, target.get("name", ""))

    def _resolve_rail_stop(self, bundle: DataBundle, query: str) -> StationRecord | None:
        if not bundle.rail_stops:
            return None
        query_norm = normalize_text(query)
        if not query_norm:
            return None

        exact_match = next(
            (
                stop
                for stop_name, stop in bundle.rail_stops.items()
                if normalize_text(stop_name) == query_norm
            ),
            None,
        )
        if exact_match is not None:
            return exact_match

        contains_matches = [
            stop
            for stop_name, stop in bundle.rail_stops.items()
            if query_norm in normalize_text(stop_name)
        ]
        if len(contains_matches) == 1:
            return contains_matches[0]
        if contains_matches:
            contains_matches.sort(key=lambda item: item.name)
            return contains_matches[0]
        return None

    def _list_local_rail_extensions(
        self,
        bundle: DataBundle,
        origin_name: str,
        departure_after: datetime,
        max_connection_minutes: int | None = None,
        max_initial_departures: int = 8,
        max_results_per_origin: int = 12,
    ) -> list[dict]:
        cache_key = (
            normalize_text(origin_name),
            departure_after.date().isoformat(),
            departure_after.strftime("%H:%M"),
            max_connection_minutes,
        )
        cached = self._local_rail_extensions_cache.get(cache_key)
        if cached is not None:
            return cached

        if bundle.rail_segments is None or bundle.rail_segments.empty:
            return []

        origin_stop = self._resolve_rail_stop(bundle, origin_name)
        if origin_stop is None:
            return []

        active_service_ids = self._active_rail_service_ids(bundle, departure_after.date())
        if not active_service_ids:
            return []

        active_segments = bundle.rail_segments[
            bundle.rail_segments["service_id"].isin(active_service_ids)
        ]
        if active_segments.empty:
            return []
        base_time = datetime.combine(departure_after.date(), time(0, 0))
        best_paths_by_destination: dict[str, dict] = {}

        origin_segments = active_segments[active_segments["from_stop_name"] == origin_stop.name].copy()
        if origin_segments.empty:
            return []
        origin_segments["departure_dt"] = origin_segments["departure_minutes"].map(
            lambda minutes: base_time + pd.Timedelta(minutes=int(minutes))
        )
        origin_segments = origin_segments[origin_segments["departure_dt"] >= departure_after]
        if max_connection_minutes is not None:
            latest_departure = add_minutes(departure_after, max_connection_minutes)
            origin_segments = origin_segments[origin_segments["departure_dt"] <= latest_departure]
        if origin_segments.empty:
            return []
        origin_segments = origin_segments.sort_values(["departure_dt", "arrival_minutes", "to_stop_name"])

        trip_chains = {
            trip_id: group.sort_values("stop_sequence")
            for trip_id, group in active_segments.groupby("trip_id")
        }

        for segment in origin_segments.head(max_initial_departures).itertuples(index=False):
            chain = trip_chains.get(segment.trip_id)
            if chain is None:
                continue
            downstream = chain[chain["stop_sequence"] >= segment.stop_sequence]
            path: list[dict] = []
            for step in downstream.itertuples(index=False):
                path.append(
                    {
                        "trip_id": step.trip_id,
                        "from": step.from_stop_name,
                        "to": step.to_stop_name,
                        "departure_dt": base_time + pd.Timedelta(minutes=int(step.departure_minutes)),
                        "arrival_dt": base_time + pd.Timedelta(minutes=int(step.arrival_minutes)),
                        "mode": step.mode or "Train",
                        "label": step.label or "",
                    }
                )
                destination_name = step.to_stop_name
                if normalize_text(destination_name) == normalize_text(origin_stop.name):
                    continue
                existing = best_paths_by_destination.get(destination_name)
                serialized = self._serialize_local_rail_path(path)
                serialized["destination"] = destination_name
                if (
                    existing is None
                    or serialized["duration_minutes"] < existing["duration_minutes"]
                    or serialized["arrival_time"] < existing["arrival_time"]
                ):
                    best_paths_by_destination[destination_name] = serialized
        results = list(best_paths_by_destination.values())
        results.sort(key=lambda item: (item["duration_minutes"], item["arrival_time"], item["destination"]))
        trimmed_results = results[:max_results_per_origin]
        self._local_rail_extensions_cache[cache_key] = trimmed_results
        return trimmed_results

    def _serialize_local_rail_path(self, path: list[dict]) -> dict:
        departure = path[0]["departure_dt"]
        arrival = path[-1]["arrival_dt"]
        return {
            "departure_time": departure.strftime("%H:%M"),
            "arrival_time": arrival.strftime("%H:%M"),
            "duration_minutes": duration_minutes(departure, arrival),
            "sections": [
                {
                    "type": "public_transport",
                    "mode": segment["mode"],
                    "label": segment["label"],
                    "from": segment["from"],
                    "to": segment["to"],
                }
                for segment in path
            ],
        }

    def _active_rail_service_ids(self, bundle: DataBundle, travel_date: date) -> set[str]:
        active_service_ids: set[str] = set()
        weekday_columns = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]

        if bundle.rail_calendar is not None and not bundle.rail_calendar.empty:
            weekday_column = weekday_columns[travel_date.weekday()]
            active_calendar = bundle.rail_calendar[
                bundle.rail_calendar["start_date"].dt.date.le(travel_date)
                & bundle.rail_calendar["end_date"].dt.date.ge(travel_date)
                & bundle.rail_calendar[weekday_column].astype(str).eq("1")
            ]
            active_service_ids.update(active_calendar["service_id"].dropna().astype(str))

        if bundle.rail_exceptions is not None and not bundle.rail_exceptions.empty:
            exceptions = bundle.rail_exceptions[
                bundle.rail_exceptions["date"].dt.date.eq(travel_date)
            ]
            for row in exceptions.itertuples(index=False):
                if str(row.exception_type) == "1":
                    active_service_ids.add(str(row.service_id))
                elif str(row.exception_type) == "2":
                    active_service_ids.discard(str(row.service_id))
        return active_service_ids

    def _station_coordinates(self, bundle: DataBundle, name: str) -> dict | None:
        station = self._resolve_station(bundle, name)
        if station is None:
            fallback = self._commune_centroid(bundle, name)
            if fallback is None:
                return None
            return fallback
        return {"latitude": station.latitude, "longitude": station.longitude}

    def _commune_centroid(self, bundle: DataBundle, name: str) -> dict | None:
        cleaned = re.sub(r"\([^)]*\)", " ", name)
        cleaned = cleaned.replace("/", " ").replace("-", " ")
        commune_query = normalize_text(cleaned)
        if not commune_query:
            return None

        matching_stations = [
            station
            for station in bundle.stations.values()
            if normalize_text(station.commune or "") == commune_query
        ]
        if not matching_stations:
            matching_stations = [
                station
                for station in bundle.stations.values()
                if normalize_text(station.name).startswith(f"{commune_query} ")
                or f" {commune_query} " in f" {normalize_text(station.name)} "
            ]
        if not matching_stations:
            return None

        latitude = sum(station.latitude for station in matching_stations) / len(matching_stations)
        longitude = sum(station.longitude for station in matching_stations) / len(matching_stations)
        return {"latitude": latitude, "longitude": longitude}

    def _group_destinations(self, bundle: DataBundle, trips_frame) -> list[dict]:
        grouped = []
        for destination, group in trips_frame.groupby("destination"):
            grouped.append(
                {
                    "destination": destination,
                    "coordinates": self._station_coordinates(bundle, destination),
                    "trip_count": int(len(group)),
                    "first_departure": group["depart_time"].min(),
                    "last_departure": group["depart_time"].max(),
                }
            )
        grouped.sort(key=lambda item: (item["first_departure"], item["destination"]))
        return grouped

    def _build_return_options(
        self,
        bundle: DataBundle,
        origin_name: str,
        destination_names: list[str],
        earliest_departure: datetime,
        return_date: date | None,
        max_dates: int = 5,
        max_times_per_date: int = 5,
    ) -> dict:
        returns = bundle.trips[
            bundle.trips["origin"].eq(origin_name)
            & bundle.trips["destination"].isin(destination_names)
            & bundle.trips["is_zero"]
        ]

        if return_date is not None:
            returns = returns[returns["date"] >= return_date.isoformat()]

        returns = returns[returns["depart_dt"] >= earliest_departure].sort_values(
            ["depart_dt", "arrive_dt"]
        )

        available_dates = []
        for trip_date, group in returns.groupby("date"):
            if len(available_dates) >= max_dates:
                break
            available_dates.append(
                {
                    "date": trip_date,
                    "total_times": int(len(group)),
                    "times": [
                        self._serialize_trip(bundle, row)
                        for row in group.head(max_times_per_date).itertuples(index=False)
                    ],
                }
            )

        return {
            "requested_return_date": return_date.isoformat() if return_date else None,
            "has_any": bool(available_dates),
            "total_dates": int(returns["date"].nunique()) if not returns.empty else 0,
            "total_trips": int(len(returns)),
            "available_dates": available_dates,
        }

    def _serialize_trip(self, bundle: DataBundle, row) -> dict:
        if hasattr(row, "_asdict"):
            data = row._asdict()
        else:
            data = dict(row)
        booking_url = self._build_sncf_booking_url(
            bundle,
            data["origin"],
            data["destination"],
            data["depart_dt"],
        )
        return {
            "id": self._trip_identifier(data),
            "train_no": data.get("train_no") or "",
            "origin": data["origin"],
            "destination": data["destination"],
            "departure_time": data["depart_time"],
            "arrival_time": data["arrive_time"],
            "departure_datetime": data["depart_dt"],
            "arrival_datetime": data["arrive_dt"],
            "duration_minutes": duration_minutes(data["depart_dt"], data["arrive_dt"]),
            "duration_label": format_minutes(duration_minutes(data["depart_dt"], data["arrive_dt"])),
            "booking_url": booking_url,
            "coordinates": {
                "origin": self._station_coordinates(bundle, data["origin"]),
                "destination": self._station_coordinates(bundle, data["destination"]),
            },
        }

    @staticmethod
    def _trip_identifier(data: dict) -> str:
        identity = "|".join(
            [
                str(data.get("date") or ""),
                str(data.get("origin") or ""),
                str(data.get("destination") or ""),
                str(data.get("depart_time") or ""),
                str(data.get("arrive_time") or ""),
                str(data.get("train_no") or ""),
            ]
        )
        return sha1(identity.encode("utf-8")).hexdigest()[:16]

    def _serialize_path(self, bundle: DataBundle, path: list) -> dict:
        first = path[0]
        last = path[-1]
        segments = [self._serialize_trip(bundle, segment) for segment in path]
        path_duration = duration_minutes(first.depart_dt, last.arrive_dt)
        return {
            "origin": first.origin,
            "destination": last.destination,
            "departure_time": first.depart_time,
            "arrival_time": last.arrive_time,
            "departure_datetime": first.depart_dt,
            "arrival_datetime": last.arrive_dt,
            "duration_minutes": path_duration,
            "duration_label": format_minutes(path_duration),
            "connections": max(0, len(path) - 1),
            "segments": segments,
        }

    def _resolve_hybrid_target(self, bundle: DataBundle, query: str) -> dict | None:
        query_norm = normalize_text(query)
        for item in self._mountains:
            if normalize_text(item["name"]) == query_norm:
                return item
        for item in self._mountains:
            if query_norm and query_norm in normalize_text(item["name"]):
                return item

        station = self._resolve_station(bundle, query)
        if station is not None:
            return {
                "name": station.name,
                "latitude": station.latitude,
                "longitude": station.longitude,
                "tags": ["gare"],
                "region": station.commune or "",
            }
        return None

    @staticmethod
    def _load_mountains(path: Path) -> list[dict]:
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def _build_sncf_booking_url(
        self,
        bundle: DataBundle,
        origin_name: str,
        destination_name: str,
        departure_datetime: datetime | None,
    ) -> str:
        origin_label = self._sncf_search_label(bundle, origin_name)
        destination_label = self._sncf_search_label(bundle, destination_name)
        if not origin_label or not destination_label:
            return "https://www.sncf-connect.com/home/search/od"

        search_parts = [f"{origin_label} - {destination_label}", "aller-simple"]
        if departure_datetime is not None:
            search_parts.append(f"Le {self._format_sncf_search_date(departure_datetime.date())}")
        search_parts.append("1 voyageur")

        user_input = ", ".join(search_parts)
        return f"https://www.sncf-connect.com/home/search?userInput={quote(user_input)}"

    def _sncf_search_label(self, bundle: DataBundle, place_name: str) -> str:
        station = self._resolve_station(bundle, place_name)
        candidate = station.name if station is not None else place_name
        cleaned = re.sub(r"\([^)]*\)", " ", candidate)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
        if normalize_text(cleaned).startswith("PARIS"):
            return "Paris"
        if cleaned.isupper():
            return cleaned.title()
        return cleaned

    @staticmethod
    def _format_sncf_search_date(travel_date: date) -> str:
        return f"{travel_date.day} {FRENCH_MONTH_NAMES[travel_date.month]}"
