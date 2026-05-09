from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime, time
from heapq import heappop, heappush
from pathlib import Path

from app.config import Settings
from app.models import DataBundle, StationRecord
from app.services.data_loader import DataRepository
from app.services.navitia import NavitiaClient
from app.utils import add_minutes, duration_minutes, format_minutes, match_score, normalize_text


COMMON_ROUTE_SUFFIXES = {
    "GARE",
    "HALL",
    "TGV",
    "CEDEX",
    "INTRAMUROS",
}


class TravelPlanner:
    def __init__(self, settings: Settings, repository: DataRepository | None = None):
        self.settings = settings
        self.repository = repository or DataRepository(settings)
        self.navitia = NavitiaClient(settings)
        self._mountains = self._load_mountains(settings.mountains_file)

    def meta(self) -> dict:
        bundle = self.repository.get_bundle()
        trips = bundle.trips
        available_dates = sorted(trips["date"].dropna().unique().tolist())
        return {
            "app_name": self.settings.app_name,
            "hybrid_enabled": self.navitia.enabled,
            "available_dates": available_dates,
            "date_min": available_dates[0] if available_dates else None,
            "date_max": available_dates[-1] if available_dates else None,
            "mountain_destinations": self._mountains,
            "generated_at": bundle.generated_at.isoformat(),
        }

    def refresh(self) -> dict:
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
        ]

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
                if path:
                    minimum_departure = add_minutes(current_time, min_connection_minutes)
                if trip.depart_dt < minimum_departure:
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
        destination_query: str,
        max_connections: int = 2,
        min_connection_minutes: int = 25,
    ) -> dict:
        if not self.navitia.enabled:
            return {
                "enabled": False,
                "reason": "SNCF_API_TOKEN manquant",
                "results": [],
            }

        bundle = self.repository.get_bundle()
        target = self._resolve_hybrid_target(bundle, destination_query)
        if target is None:
            return {
                "enabled": True,
                "reason": "Destination finale introuvable",
                "results": [],
            }

        max_routes = self.max_itineraries(
            origin_query=origin_query,
            travel_date=travel_date,
            max_connections=max_connections,
            min_connection_minutes=min_connection_minutes,
            max_results=25,
        )["results"]

        combined_results = []
        for group in max_routes:
            for itinerary in group["itineraries"]:
                station = self._resolve_station(bundle, itinerary["destination"])
                if station is None:
                    continue
                navitia_journey = self.navitia.plan_from_station(
                    origin=station,
                    target_latitude=target["latitude"],
                    target_longitude=target["longitude"],
                    departure_after=itinerary["arrival_datetime"],
                )
                if navitia_journey is None:
                    continue
                combined_results.append(
                    {
                        "destination": target["name"],
                        "via_max_station": itinerary["destination"],
                        "total_duration_minutes": itinerary["duration_minutes"]
                        + navitia_journey["duration_minutes"],
                        "total_duration_label": format_minutes(
                            itinerary["duration_minutes"] + navitia_journey["duration_minutes"]
                        ),
                        "max_itinerary": itinerary,
                        "ter_extension": navitia_journey,
                        "target_coordinates": {
                            "latitude": target["latitude"],
                            "longitude": target["longitude"],
                        },
                    }
                )
                if len(combined_results) >= 10:
                    break
            if len(combined_results) >= 10:
                break

        combined_results.sort(key=lambda item: item["total_duration_minutes"])
        return {
            "enabled": True,
            "target": target,
            "results": combined_results,
        }

    def _day_trips(self, bundle: DataBundle, travel_date: date):
        return bundle.trips[bundle.trips["date"] == travel_date.isoformat()]

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

    def _station_coordinates(self, bundle: DataBundle, name: str) -> dict | None:
        station = self._resolve_station(bundle, name)
        if station is None:
            return None
        return {"latitude": station.latitude, "longitude": station.longitude}

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
            returns = returns[returns["date"] == return_date.isoformat()]

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
        booking_url = self._build_sncf_booking_url(bundle, data["origin"], data["destination"])
        return {
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
    ) -> str:
        origin_slug = self._sncf_place_slug(bundle, origin_name)
        destination_slug = self._sncf_place_slug(bundle, destination_name)
        if not origin_slug or not destination_slug:
            return "https://www.sncf-connect.com/"
        return f"https://www.sncf-connect.com/train/horaires/{origin_slug}/{destination_slug}"

    def _sncf_place_slug(self, bundle: DataBundle, place_name: str) -> str:
        station = self._resolve_station(bundle, place_name)
        if station is not None and station.commune:
            return self._slugify_route_part(station.commune)

        cleaned = re.sub(r"\([^)]*\)", " ", place_name)
        cleaned = cleaned.replace("&", " ").replace("/", " ").replace(" - ", " ")
        normalized_parts = normalize_text(cleaned).split()
        significant_parts = [
            part
            for part in normalized_parts
            if part not in COMMON_ROUTE_SUFFIXES and not part.isdigit()
        ]
        if not significant_parts:
            significant_parts = normalized_parts
        if significant_parts[:2] == ["PARIS", "GARE"]:
            return "paris"
        return self._slugify_route_part(" ".join(significant_parts[:4]))

    @staticmethod
    def _slugify_route_part(value: str) -> str:
        normalized = normalize_text(value)
        return normalized.lower().replace(" ", "-")
