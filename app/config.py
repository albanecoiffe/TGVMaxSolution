from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(slots=True)
class Settings:
    app_name: str = "Max Explorer"
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("MAX_EXPLORER_DATA_DIR", BASE_DIR / "data")
        )
    )
    refresh_hours: int = int(os.getenv("MAX_EXPLORER_REFRESH_HOURS", "12"))
    tgvmax_url: str = os.getenv(
        "MAX_EXPLORER_TGVMAX_URL",
        "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/tgvmax/exports/csv",
    )
    stations_url: str = os.getenv(
        "MAX_EXPLORER_STATIONS_URL",
        "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/gares-de-voyageurs/exports/geojson",
    )
    sncf_gtfs_url: str = os.getenv(
        "MAX_EXPLORER_SNCF_GTFS_URL",
        "https://eu.ftp.opendatasoft.com/sncf/plandata/Export_OpenData_SNCF_GTFS_NewTripId.zip",
    )
    sncf_api_token: str | None = os.getenv("SNCF_API_TOKEN")
    max_itinerary_results: int = int(os.getenv("MAX_EXPLORER_MAX_RESULTS", "40"))
    live_check_timeout_seconds: int = int(os.getenv("MAX_EXPLORER_LIVE_CHECK_TIMEOUT", "20"))
    live_check_cache_minutes: int = int(os.getenv("MAX_EXPLORER_LIVE_CHECK_CACHE_MINUTES", "10"))
    live_check_default_limit: int = int(os.getenv("MAX_EXPLORER_LIVE_CHECK_LIMIT", "20"))

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def history_dir(self) -> Path:
        return self.data_dir / "history"

    @property
    def tgvmax_cache_file(self) -> Path:
        return self.cache_dir / "tgvmax.csv"

    @property
    def stations_cache_file(self) -> Path:
        return self.cache_dir / "gares-de-voyageurs.geojson"

    @property
    def sncf_gtfs_cache_file(self) -> Path:
        return self.cache_dir / "sncf-gtfs.zip"

    @property
    def mountains_file(self) -> Path:
        return self.data_dir / "mountains.json"

    @property
    def templates_dir(self) -> Path:
        return BASE_DIR / "app" / "templates"

    @property
    def static_dir(self) -> Path:
        return BASE_DIR / "app" / "static"
