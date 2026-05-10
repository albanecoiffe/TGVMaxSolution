# Max Explorer

Application web Python pour explorer les trajets `TGV MAX` a 0 EUR avec :

- les trains disponibles par jour depuis une gare ou une ville,
- une carte des destinations accessibles,
- des suggestions d'aller-retour dans la journee,
- des itineraires avec correspondances `MAX`,
- un mode hybride `MAX + TER` qui liste automatiquement les prolongements ferroviaires depuis les gares atteignables en MAX.

## Sources de donnees

- `tgvmax` SNCF Open Data : disponibilite a 30 jours des places MAX.
- `gares-de-voyageurs` SNCF Open Data : referentiel des gares et geolocalisation.
- GTFS SNCF ouvert pour les prolongements ferroviaires `MAX + TER`.

## Lancer le projet

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Puis ouvrir [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Variables utiles

- `SNCF_API_TOKEN` : active les calculs hybrides via API SNCF/Navitia.
- `MAX_EXPLORER_REFRESH_HOURS` : frequence de refresh du cache local.
- `MAX_EXPLORER_DATA_DIR` : emplacement du cache local.
- `MAX_EXPLORER_SNCF_GTFS_URL` : URL du zip GTFS SNCF ouvert.

## Activer le mode MAX + TER

Par defaut, l'application charge le GTFS SNCF ouvert pour proposer automatiquement les prolongements ferroviaires apres les trajets MAX.

## Lancer les tests

```bash
uv run pytest
```

## Notes

- Le dataset `tgvmax` couvre une fenetre glissante d'environ 30 jours.
- Les prolongements `MAX + TER` dependent du zip GTFS SNCF ouvert telecharge cote serveur.
- La carte s'appuie sur Leaflet et des tuiles OpenStreetMap.
