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
make install
make backend
```

Puis ouvrir [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Hebergement Render

Le depot contient un fichier [render.yaml](/Users/albanecoiffe/Library/Mobile%20Documents/com~apple~CloudDocs/Documents/tgvmax/render.yaml:1) pour deployer l'application web sur Render.

Important :

- Render peut heberger le site, le plan de surveillance, l'historique et les futures alertes.
- Render ne remplace pas a lui seul le moteur navigateur SNCF Connect.
- Le moteur live depend encore d'un vrai navigateur avec une vraie session SNCF Connect.

Architecture cible :

1. Render heberge l'application web.
2. Un worker navigateur dedie execute l'extension en continu.
3. L'extension pousse :
   - l'etat des surveillances vers `/api/live-watch/ingest`
   - le heartbeat du worker vers `/api/live-worker/heartbeat`
4. La page `/live-watch` affiche :
   - le plan de surveillance
   - l'etat persistant des checks
   - le statut du worker

Le champ `Backend live-watch` de l'extension peut pointer soit vers le backend local, soit vers l'URL Render.

## Commandes Make utiles

```bash
make help
make test
make test-api
make test-planner
make refresh
```

## Variables utiles

- `SNCF_API_TOKEN` : enrichit le mode `MAX + TER` avec les prix TER via l'API SNCF/Navitia.
- `MAX_EXPLORER_REFRESH_HOURS` : frequence de refresh du cache local.
- `MAX_EXPLORER_DATA_DIR` : emplacement du cache local.
- `MAX_EXPLORER_SNCF_GTFS_URL` : URL du zip GTFS SNCF ouvert.

## Activer le mode MAX + TER

Par defaut, l'application charge le GTFS SNCF ouvert pour proposer automatiquement les prolongements ferroviaires apres les trajets MAX.
Si `SNCF_API_TOKEN` est renseigne, les resultats affichent aussi le prix TER quand l'API SNCF/Navitia le renvoie.
Sinon, l'interface affiche un lien direct vers la recherche SNCF Connect du prolongement TER pour verifier le tarif.

## Lancer les tests

```bash
uv run pytest
```

## POC session navigateur reelle

Un POC d'observation reseau pour SNCF Connect est disponible dans [tools/sncf_probe_extension/README.md](/Users/albanecoiffe/Library/Mobile%20Documents/com~apple~CloudDocs/Documents/tgvmax/tools/sncf_probe_extension/README.md:1).

Cette extension Chrome/Chromium ne scrape pas le HTML et ne lance pas de headless. Elle hooke `fetch` et `XMLHttpRequest` dans une session humaine deja ouverte afin de capturer les appels reseau visibles par le front SNCF Connect.

Pour inspecter un export ensuite :

```bash
PYTHONPATH=. python3 tools/inspect_sncf_probe.py tools/sncf-probe-YYYY-MM-DDTHH-MM-SS.json --write-redacted
```

Le script resume les appels `bff/api/v1/itineraries` et peut ecrire une copie `.redacted.json` en supprimant les champs sensibles connus.

Pour rejouer un appel `itineraries` a partir d'un export :

```bash
python3 tools/replay_sncf_itineraries.py tools/sncf-probe-YYYY-MM-DDTHH-MM-SS.json
python3 tools/replay_sncf_itineraries.py tools/sncf-probe-YYYY-MM-DDTHH-MM-SS.json --outward-datetime 2026-05-18T15:38:00.000Z --execute
```

Sans `--execute`, le script affiche le template reconstruit. Avec `--execute`, il envoie vraiment le `POST` vers `bff/api/v1/itineraries` avec les headers/session capturés dans le probe.

## Notes

- Le dataset `tgvmax` couvre une fenetre glissante d'environ 30 jours.
- Le dataset `tgvmax` est annonce par SNCF Open Data comme mis a jour tous les jours en debut de matinee.
- Les prolongements `MAX + TER` dependent du zip GTFS SNCF ouvert telecharge cote serveur.
- La carte s'appuie sur Leaflet et des tuiles OpenStreetMap.
- La vue directe affiche le dataset SNCF tel qu'il a ete charge cote application, avec un indicateur de fraicheur base sur `generated_at`.

## Suivre les changements de trains a 0 EUR

- `POST /api/refresh` force un rechargement des donnees locales et enregistre un snapshot des trajets `0 EUR`.
- La reponse contient `zero_watch` avec le diff par rapport au snapshot precedent :
  - `new_zero_count`
  - `removed_zero_count`
  - `current_zero_count`
  - `sample_new_trips`
  - `sample_removed_trips`
- `GET /api/watch/latest` renvoie le dernier diff enregistre.

Les snapshots sont stockes dans `data/history/`. Cela permet de detecter tout de suite la mise a jour du matin cote SNCF, meme si la publication source n'est pas continue toute la journee.
