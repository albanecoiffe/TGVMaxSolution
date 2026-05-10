from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd


@dataclass(slots=True)
class StationRecord:
    name: str
    latitude: float
    longitude: float
    commune: str | None = None
    trigram: str | None = None
    code_uic: str | None = None


@dataclass(slots=True)
class DataBundle:
    trips: pd.DataFrame
    stations: dict[str, StationRecord]
    station_names: list[str]
    generated_at: datetime
    rail_segments: pd.DataFrame | None = None
    rail_stops: dict[str, StationRecord] | None = None
    rail_calendar: pd.DataFrame | None = None
    rail_exceptions: pd.DataFrame | None = None
