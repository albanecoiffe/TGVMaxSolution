from __future__ import annotations

import json
from zipfile import ZipFile

import pytest

from app.config import Settings
from app.services.data_loader import DataRepository
from app.services.planner import TravelPlanner


TGVMAX_SAMPLE = """date,train_no,entity,axe,origine_iata,destination_iata,origine,destination,heure_depart,heure_arrivee,od_happy_card
2026-05-23,6611,PARLYN,SE,FPPY,FPLYD,PARIS GARE DE LYON,LYON PART DIEU,06:00,08:00,OUI
2026-05-23,6612,PARLYN,SE,FPPY,FPLYD,PARIS GARE DE LYON,LYON PART DIEU,09:15,11:10,OUI
2026-05-23,6613,PARLIL,NORD,FPPN,FLL,PARIS NORD,LILLE EUROPE,07:00,08:05,OUI
2026-05-23,6615,PARSTR,EST,FPEST,FRSXB,PARIS EST,STRASBOURG,06:45,08:40,OUI
2026-05-23,6621,LYNANN,ALP,FPLYD,FRANC,LYON PART DIEU,ANNECY,08:40,10:35,OUI
2026-05-23,6623,LYNGRN,ALP,FPLYD,FRGRE,LYON PART DIEU,GRENOBLE,08:50,10:05,OUI
2026-05-23,6625,LILPAR,NORD,FLL,FPPN,LILLE EUROPE,19:40,20:45,OUI
2026-05-23,6627,LYNPAR,SE,FPLYD,FPPY,LYON PART DIEU,PARIS GARE DE LYON,19:00,21:00,OUI
2026-05-23,6628,LYNPAR,SE,FPLYD,FPPY,LYON PART DIEU,PARIS GARE DE LYON,21:15,23:15,OUI
2026-05-23,6629,ANNCY,ALP,FRANC,FPLYD,ANNECY,18:20,20:10,OUI
2026-05-23,6631,STRPAR,EST,FRSXB,FPEST,STRASBOURG,19:15,21:10,OUI
2026-05-23,6633,GRNLYN,ALP,FRGRE,FPLYD,GRENOBLE,LYON PART DIEU,18:00,19:20,OUI
2026-05-24,6641,PARLYN,SE,FPPY,FPLYD,PARIS GARE DE LYON,LYON PART DIEU,06:00,08:00,NON
2026-05-24,6643,LYNPAR,SE,FPLYD,FPPY,LYON PART DIEU,PARIS GARE DE LYON,18:00,20:00,OUI
2026-05-24,6645,LILPAR,NORD,FLL,FPPN,LILLE EUROPE,PARIS NORD,17:45,18:50,OUI
2026-05-24,6647,STRPAR,EST,FRSXB,FPEST,STRASBOURG,PARIS EST,18:15,20:10,OUI
2026-05-25,6651,LYNPAR,SE,FPLYD,FPPY,LYON PART DIEU,PARIS GARE DE LYON,07:15,09:15,OUI
"""


STATIONS_SAMPLE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"nom_gare": "PARIS GARE DE LYON", "commune": "Paris"},
            "geometry": {"type": "Point", "coordinates": [2.3730, 48.8443]},
        },
        {
            "type": "Feature",
            "properties": {"nom_gare": "PARIS NORD", "commune": "Paris"},
            "geometry": {"type": "Point", "coordinates": [2.3553, 48.8809]},
        },
        {
            "type": "Feature",
            "properties": {"nom_gare": "PARIS EST", "commune": "Paris"},
            "geometry": {"type": "Point", "coordinates": [2.3592, 48.8767]},
        },
        {
            "type": "Feature",
            "properties": {"nom_gare": "LYON PART DIEU", "commune": "Lyon"},
            "geometry": {"type": "Point", "coordinates": [4.8590, 45.7609]},
        },
        {
            "type": "Feature",
            "properties": {"nom_gare": "LILLE EUROPE", "commune": "Lille"},
            "geometry": {"type": "Point", "coordinates": [3.0750, 50.6397]},
        },
        {
            "type": "Feature",
            "properties": {"nom_gare": "STRASBOURG", "commune": "Strasbourg"},
            "geometry": {"type": "Point", "coordinates": [7.7344, 48.5851]},
        },
        {
            "type": "Feature",
            "properties": {"nom_gare": "ANNECY", "commune": "Annecy"},
            "geometry": {"type": "Point", "coordinates": [6.1214, 45.9034]},
        },
        {
            "type": "Feature",
            "properties": {"nom_gare": "GRENOBLE", "commune": "Grenoble"},
            "geometry": {"type": "Point", "coordinates": [5.7140, 45.1911]},
        },
    ],
}


GTFS_STOPS_SAMPLE = """stop_id,stop_name,stop_lat,stop_lon
lyd,LYON PART DIEU,45.7609,4.8590
annecy,ANNECY,45.9034,6.1214
fayet,SAINT GERVAIS LES BAINS LE FAYET,45.9053,6.7006
chx,CHAMONIX MONT BLANC,45.9237,6.8694
"""


GTFS_TRIPS_SAMPLE = """route_id,service_id,trip_id,trip_headsign
r1,s1,t1,Chamonix Mont Blanc
"""


GTFS_ROUTES_SAMPLE = """route_id,route_short_name,route_long_name,route_type
r1,TER,Alpes,2
"""


GTFS_STOP_TIMES_SAMPLE = """trip_id,arrival_time,departure_time,stop_id,stop_sequence
t1,08:30:00,08:30:00,lyd,1
t1,10:35:00,10:40:00,annecy,2
t1,11:20:00,11:25:00,fayet,3
t1,12:00:00,12:00:00,chx,4
"""


GTFS_CALENDAR_DATES_SAMPLE = """service_id,date,exception_type
s1,20260523,1
"""


@pytest.fixture()
def settings(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = data_dir / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "tgvmax.csv").write_text(TGVMAX_SAMPLE, encoding="utf-8")
    (cache_dir / "gares-de-voyageurs.geojson").write_text(
        json.dumps(STATIONS_SAMPLE),
        encoding="utf-8",
    )
    (data_dir / "mountains.json").write_text(
        json.dumps(
            [
                {
                    "name": "Chamonix-Mont-Blanc",
                    "latitude": 45.9237,
                    "longitude": 6.8694,
                    "region": "Alpes",
                    "tags": ["montagne"],
                }
            ]
        ),
        encoding="utf-8",
    )
    with ZipFile(cache_dir / "sncf-gtfs.zip", "w") as archive:
        archive.writestr("stops.txt", GTFS_STOPS_SAMPLE)
        archive.writestr("trips.txt", GTFS_TRIPS_SAMPLE)
        archive.writestr("routes.txt", GTFS_ROUTES_SAMPLE)
        archive.writestr("stop_times.txt", GTFS_STOP_TIMES_SAMPLE)
        archive.writestr("calendar_dates.txt", GTFS_CALENDAR_DATES_SAMPLE)
    return Settings(
        data_dir=data_dir,
        refresh_hours=9999,
        tgvmax_url="https://example.com/tgvmax.csv",
        stations_url="https://example.com/stations.geojson",
        sncf_gtfs_url="https://example.com/sncf-gtfs.zip",
    )


@pytest.fixture()
def repository(settings):
    return DataRepository(settings)


@pytest.fixture()
def planner(settings, repository):
    return TravelPlanner(settings=settings, repository=repository)
