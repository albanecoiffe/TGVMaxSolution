from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.services.live_watch import LiveWatchStore
from app.services.live_watch_plan import LiveWatchPlanStore
from app.services.live_worker import LiveWorkerStore
from app.services.planner import TravelPlanner


PAGES = {
    "direct": {
        "key": "direct",
        "path": "/",
        "label": "Trains a 0 EUR du jour",
        "hero_title": "Voir les trajets MAX marques a 0 EUR dans le dataset SNCF.",
        "hero_text": "Cette vue affiche les trajets signales a 0 EUR dans le dataset SNCF Open Data et indique quand ce dataset a ete vu et recharge cote application.",
        "map_help": "Destinations directes disponibles a 0 EUR depuis le point de depart.",
        "result_title": "Dataset SNCF tgvmax",
        "result_help": "Les trajets listes proviennent du dataset SNCF `tgvmax`.",
        "fields": ["origin", "date", "return_date"],
    },
    "day_trips": {
        "key": "day_trips",
        "path": "/aller-retour-journee",
        "label": "Aller-retour journee",
        "hero_title": "Trouver les destinations faisables en aller-retour sur la journee.",
        "hero_text": "Cette page isole les destinations qui ont un aller et un retour a 0 EUR compatibles avec ton temps minimal sur place.",
        "map_help": "Destinations compatibles avec un aller-retour MAX sur la meme journee.",
        "result_title": "Aller-retour journee",
        "result_help": "Suggestions triees par temps utile sur place.",
        "fields": ["origin", "date", "return_date", "min_stay_minutes", "latest_return_time"],
    },
    "routes_max": {
        "key": "routes_max",
        "path": "/correspondances-max",
        "label": "Correspondances MAX",
        "hero_title": "Explorer les destinations accessibles avec correspondances 100% MAX.",
        "hero_text": "Cette vue sert a pousser le reseau plus loin avec des changements de train, sans melanger les autres modes d'exploration.",
        "map_help": "Destinations accessibles en combinant plusieurs segments MAX.",
        "result_title": "Correspondances MAX",
        "result_help": "Cette page n'affiche que des itineraires avec au moins une correspondance reelle.",
        "fields": [
            "origin",
            "date",
            "return_date",
            "min_connection_minutes",
            "max_connection_minutes",
            "max_connections",
        ],
    },
    "hybrid": {
        "key": "hybrid",
        "path": "/max-ter",
        "label": "MAX + TER",
        "hero_title": "Lister automatiquement les prolongements TER apres un trajet MAX.",
        "hero_text": "Cette page cherche les gares atteignables en MAX pour la date choisie, puis affiche les prolongements ferroviaires ouverts depuis ces gares sans demander de destination finale.",
        "map_help": "Derniere gare atteinte en MAX puis gare finale accessible en prolongement ferroviaire.",
        "result_title": "MAX + TER",
        "result_help": "La liste se remplit automatiquement a partir des gares accessibles en MAX.",
        "fields": [
            "origin",
            "date",
            "return_date",
            "min_connection_minutes",
            "max_connection_minutes",
            "max_connections",
        ],
    },
    "live_watch": {
        "key": "live_watch",
        "path": "/live-watch",
        "label": "Surveillance live",
        "hero_title": "Suivre les trajets 0 EUR detectes par la surveillance navigateur.",
        "hero_text": "Cette page affiche l'etat persistant des surveillances live poussees depuis l'extension navigateur vers l'application locale.",
        "map_help": "La carte n'est pas utilisee pour la surveillance live. Utilise le panneau principal pour suivre les apparitions et disparitions de 0 EUR.",
        "result_title": "Surveillance live SNCF Connect",
        "result_help": "Etat persistant des checks realises depuis ton navigateur reel.",
        "fields": [],
    },
}


def _page_context(request: Request, planner: TravelPlanner, page_key: str) -> dict:
    meta = planner.meta()
    filters = {
        "origin": request.query_params.get("origin", "Paris"),
        "date": request.query_params.get("date", meta["date_min"] or ""),
        "return_date": request.query_params.get("return_date", ""),
        "min_stay_minutes": request.query_params.get("min_stay_minutes", "240"),
        "min_connection_minutes": request.query_params.get("min_connection_minutes", "25"),
        "max_connection_minutes": request.query_params.get("max_connection_minutes", ""),
        "max_connections": request.query_params.get("max_connections", "2"),
        "latest_return_time": request.query_params.get("latest_return_time", "23:30"),
    }
    return {
        "meta": meta,
        "page": PAGES[page_key],
        "pages": list(PAGES.values()),
        "filters": filters,
        "request": request,
    }


def create_app(
    settings: Settings | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    planner = TravelPlanner(app_settings)
    live_watch_store = LiveWatchStore(app_settings)
    live_watch_plan_store = LiveWatchPlanStore(app_settings)
    live_worker_store = LiveWorkerStore(app_settings)

    app = FastAPI(title=app_settings.app_name)
    app.state.settings = app_settings
    app.state.planner = planner

    templates = Jinja2Templates(directory=str(app_settings.templates_dir))
    app.mount("/static", StaticFiles(directory=str(app_settings.static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return templates.TemplateResponse(request, "index.html", _page_context(request, planner, "direct"))

    @app.get("/aller-retour-journee", response_class=HTMLResponse)
    def page_day_trips(request: Request):
        return templates.TemplateResponse(request, "index.html", _page_context(request, planner, "day_trips"))

    @app.get("/correspondances-max", response_class=HTMLResponse)
    def page_routes_max(request: Request):
        return templates.TemplateResponse(request, "index.html", _page_context(request, planner, "routes_max"))

    @app.get("/max-ter", response_class=HTMLResponse)
    def page_hybrid(request: Request):
        return templates.TemplateResponse(request, "index.html", _page_context(request, planner, "hybrid"))

    @app.get("/live-watch", response_class=HTMLResponse)
    def page_live_watch(request: Request):
        return templates.TemplateResponse(request, "index.html", _page_context(request, planner, "live_watch"))

    @app.get("/api/meta")
    def meta():
        return planner.meta()

    @app.post("/api/refresh")
    def refresh():
        return planner.refresh()

    @app.get("/api/watch/latest")
    def watch_latest():
        return planner.latest_zero_watch()

    @app.get("/api/live-watch/latest")
    def live_watch_latest():
        return live_watch_store.latest()

    @app.post("/api/live-watch/ingest")
    async def live_watch_ingest(request: Request):
        payload = await request.json()
        return live_watch_store.ingest(payload)

    @app.get("/api/live-watch/plan")
    def live_watch_plan():
        return live_watch_plan_store.latest()

    @app.post("/api/live-watch/plan/default-weekend-bordeaux-paris")
    def live_watch_plan_default_weekend_bordeaux_paris():
        return live_watch_plan_store.build_default_weekend_plan(planner.meta()["available_dates"])

    @app.post("/api/live-watch/plan/clear")
    def live_watch_plan_clear():
        return live_watch_plan_store.clear()

    @app.get("/api/live-worker/latest")
    def live_worker_latest():
        return live_worker_store.latest()

    @app.post("/api/live-worker/heartbeat")
    async def live_worker_heartbeat(request: Request):
        payload = await request.json()
        return live_worker_store.ingest(payload)

    @app.get("/api/stations")
    def stations(q: str = Query("", min_length=1)):
        return {"results": planner.search_stations(q)}

    @app.get("/api/direct")
    def direct(
        origin: str,
        travel_date: date = Query(alias="date"),
        return_date: date | None = Query(default=None, alias="return_date"),
        include_returns: bool = True,
    ):
        try:
            return planner.direct_trips(
                origin_query=origin,
                travel_date=travel_date,
                return_date=return_date,
                include_returns=include_returns,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/day-trips")
    def day_trips(
        origin: str,
        travel_date: date = Query(alias="date"),
        return_date: date | None = Query(default=None, alias="return_date"),
        min_stay_minutes: int = 180,
        latest_return_time: str = "23:30",
    ):
        try:
            return planner.day_trip_destinations(
                origin_query=origin,
                travel_date=travel_date,
                return_date=return_date,
                min_stay_minutes=min_stay_minutes,
                latest_return_time=latest_return_time,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/routes/max")
    def routes_max(
        origin: str,
        travel_date: date = Query(alias="date"),
        return_date: date | None = Query(default=None, alias="return_date"),
        max_connections: int = 2,
        min_connection_minutes: int = 25,
        max_connection_minutes: int | None = None,
    ):
        try:
            return planner.max_itineraries(
                origin_query=origin,
                travel_date=travel_date,
                return_date=return_date,
                max_connections=max_connections,
                min_connection_minutes=min_connection_minutes,
                max_connection_minutes=max_connection_minutes,
                min_connections=1,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/routes/hybrid")
    def routes_hybrid(
        origin: str,
        travel_date: date = Query(alias="date"),
        max_connections: int = 2,
        min_connection_minutes: int = 25,
        max_connection_minutes: int | None = None,
    ):
        try:
            payload = planner.hybrid_itineraries(
                origin_query=origin,
                travel_date=travel_date,
                max_connections=max_connections,
                min_connection_minutes=min_connection_minutes,
                max_connection_minutes=max_connection_minutes,
            )
            if not payload["enabled"]:
                return JSONResponse(payload, status_code=412)
            return payload
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


app = create_app()
