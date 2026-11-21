# Max Explorer

[![CI](https://github.com/albanecoiffe/TGVMaxSolution/actions/workflows/ci.yml/badge.svg)](https://github.com/albanecoiffe/TGVMaxSolution/actions/workflows/ci.yml)

Application web Python pour explorer les trajets `TGV MAX` a 0 EUR avec :

- les trains disponibles par jour depuis une gare ou une ville,
- une carte des destinations accessibles,
- des suggestions d'aller-retour dans la journee,
- des itineraires avec correspondances `MAX`,
- un mode hybride `MAX + TER` qui liste automatiquement les prolongements ferroviaires depuis les gares atteignables en MAX,
- une page « Estimation train 0 » (`/estimation-train-0`) qui agrège l'historique des sorties de billets a 0 EUR (surveillance live navigateur + snapshots du dataset SNCF) pour estimer, par date et planche horaire, le jour et l'heure les plus probables de sortie d'un train a 0 EUR.

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

## Tester et voir la surveillance live sans l'extension

```bash
make install
make backend          # http://127.0.0.1:8000
# dans un autre terminal : injecte un etat live de demo
python3 tools/demo_live_ingest.py            # ou --dry-run pour voir le payload
```

Puis ouvre :

- [http://127.0.0.1:8000/live-watch](http://127.0.0.1:8000/live-watch) : calendrier 0 EUR, surveillances, activite, worker
- `GET /api/live-watch/latest`, `/api/live-watch/zero-calendar`, `/api/live-watch/zero-vs-dataset`, `/api/live-watch/history`, `/api/live-worker/latest`
- `python3 tools/live_zero_report.py --dataset data/cache/tgvmax.csv` : rapport CLI + trains 0 EUR hors base API
- `python3 tools/live_worker/check_live_worker.py` : watchdog (codes 0/1/2)

Avec la vraie extension : charge `tools/sncf_probe_extension` dans `chrome://extensions`, connecte-toi sur SNCF Connect, fais une recherche, puis bouton `Surveiller` du popup — l'etat remonte toutes les minutes sur `/live-watch`.

CI : `.github/workflows/ci.yml` (pytest + `node --check` sur l'extension et l'UI + `bash -n` sur le lanceur worker + `py_compile` des outils) se declenche sur chaque push/PR.

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

## Disponibilites MAX en temps reel (hors API open data)

Constat : SNCF publie le dataset `tgvmax` une fois par jour en debut de matinee et indique que les disponibilites reelles se lisent sur les canaux de vente (SNCF Connect). Il n'existe pas de flux open data temps reel des places MAX ; le GTFS-RT (mis a jour toutes les 2 minutes) decrit la circulation des trains, pas les sieges MAX.

Le seul signal temps reel exploitable est donc l'appel `POST https://www.sncf-connect.com/bff/api/v1/itineraries` de SNCF Connect, rejoue depuis une vraie session navigateur authentifiee par l'extension `tools/sncf_probe_extension`. Une seule reponse contient :

- `longDistance.proposals.bestPrices` : le meilleur prix par jour sur ~30 jours, donc le calendrier des jours a `0 EUR` pour ce trajet, rafraichi a chaque appel ;
- `longDistance.proposals.proposals` : les offres par train avec `priceLabel` a `0 EUR` pour la date demandee.

Comportement de la surveillance live :

- cycle de base toutes les 1 minute ;
- fenetre "burst" de 06:00 a 12:00 (heure locale) : toutes les 30 s pour capter les ouvertures du matin (constantes `BURST_START_HOUR`, `BURST_END_HOUR`, `BURST_INTERVAL_MINUTES` dans `background.js`) ;
- les surveillances sont regroupees par trajet (origine -> destination) : au moins 1 appel par trajet et par cycle rafraichit le calendrier de jours a 0 EUR, et jusqu'a `MAX_SCAN_SLOTS_PER_OD` (3) dates sont scannees en detail par cycle, en priorisant les dates deja signalees a 0 EUR et les moins recemment verifiees ;
- alertes navigateur : `zero_added` (nouveaux trains 0 EUR), `zero_day_added` (nouveau jour 0 EUR), `zero_removed`, `zero_day_removed`.

Nouveaux endpoints backend :

- `GET /api/live-watch/zero-calendar` : calendrier agrège des jours a 0 EUR par trajet, construit depuis le dernier ingest ;
- `GET /api/live-watch/history?limit=50` : historique borne (1000 entrees) des synchronisations live (`data/history/live-watch-history.jsonl`) ;
- `GET /api/live-watch/zero-vs-dataset` : compare chaque offre 0 EUR capturee en live avec le dataset tgvmax charge cote serveur. Chaque offre est classee `in_dataset_zero` (present a 0 EUR dans la base), `in_dataset_present_not_zero` (present mais plus a 0 EUR depuis la publication du matin) ou `not_in_dataset` (train absent de la base API, ex. place ouverte depuis la publication). Le `travelId` (format `2026-12-01T06:20_6641`) sert de cle (date + numero de train), avec repli sur (date, heure de depart, gares) ;
- `POST /api/live-watch/plan/full-month` avec `{ "origin_label": "...", "destination_label": "...", "include_return": false, "dates": ["2026-05-23", ...] }` : plan de surveillance sur toutes les dates (les `dates` sont optionnelles ; sinon les dates du dataset tgvmax dans la fenetre J..J+31 sont utilisees).

La page `/live-watch` affiche desormais un panneau "Calendrier 0 EUR (temps reel)" par trajet.

Rapport en ligne de commande depuis le dernier etat enregistre :

```bash
PYTHONPATH=. python3 tools/live_zero_report.py
PYTHONPATH=. python3 tools/live_zero_report.py --path data/history/latest-live-watch.json --json
# avec comparaison contre la base API open data (liste les trains 0 EUR captures absents de la base) :
PYTHONPATH=. python3 tools/live_zero_report.py --dataset data/cache/tgvmax.csv
```

Limites et politesse : une seule session humaine, un seul onglet SNCF Connect, aucun scraping du DOM, aucun contournement des protections anti-bot (DataDome) ; cadence minimale de 30 s et au plus 3 scans par trajet et par cycle. Respecte les CGU de SNCF Connect : l'outil ne reserve rien, il ne fait que lire des disponibilites pour ton propre abonnement, et une place peut partir entre deux checks — confirme toujours sur SNCF Connect avant de voyager.

## Worker live 24/7 (sans laisser ton PC allumé)

Oui, aujourd'hui le moteur navigateur a besoin d'une machine allumée : Chrome/Chromium ouvert avec l'extension, un onglet `sncf-connect.com` connecté, la machine non en veille. Mais ce n'est pas forcément ton PC portable :

- le **backend tourne 24/7 sur Render** (`render.yaml`) : pages, historique, calendriers et alertes consultables depuis n'importe quel appareil ;
- le **worker navigateur** peut tourner sur un petit boîtier dédié (Raspberry Pi / mini-PC / NAS, ~3-8 W) : voir [tools/live_worker/README.md](tools/live_worker/README.md) pour le kit complet (lanceur Chromium `run-live-worker.sh`, unité systemd `max-explorer-live-worker.service`, watchdog `check_live_worker.py` avec codes de sortie 0/1/2 utilisable en cron pour recevoir les alertes 0 EUR par mail).

Un VPS pas cher fonctionne aussi mais subit plus de blocages DataDome (IP datacenter). Un téléphone ne peut pas héberger l'extension (Chrome mobile sans extensions).

Si la session SNCF Connect expire côté worker, une seule recherche manuelle sur SNCF Connect suffit à réamorcer les surveillances (le seed `itineraries` est recapturé automatiquement).

## Option gratuite 24/7 sans aucune machine chez toi

Deux couches, selon ce que tu veux :

### 1. Donnees ouvertes + alertes (100% gratuit, aucune machine allumée, aucune session SNCF)

`.github/workflows/daily-tgvmax-refresh.yml` tourne en cron GitHub Actions (**gratuit sur un repo public**, minutes illimitées ; sur un repo privé ça consomme les 2000 min/mo du plan gratuit) :

1. `POST /api/refresh` sur le backend déployé (Render) → recharge le dataset `tgvmax` et enregistre le diff `zero_watch` ;
2. `GET /api/watch/latest` → lit les nouveaux trains à 0 € publiés ;
3. si `new_zero_count > 0` et que la variable de repo `ALERT_ON_NEW_ZERO=true`, ouvre une **issue GitHub** avec la liste (tu reçois la notification par mail).

Configuration (Settings → Secrets and variables → Actions → Variables) :

- `RENDER_BASE_URL` = `https://ton-app.onrender.com`
- `ALERT_ON_NEW_ZERO` = `true` (optionnel)

Lance aussi manuellement : `python3 tools/refresh_and_alert.py --base-url https://ton-app.onrender.com`

Granularité : celle de la publication SNCF (1×/jour, début de matinée). Ce n'est **pas** du temps réel.

### 2. Temps réel (nécessite un navigateur connecté quelque part)

Pas d'API publique temps réel des places MAX, et le scraping de SNCF Connect contourne la connexion + DataDome : interdit par les CGU et par l'article 323-1 du Code pénal — je ne fournis pas d'outil dans ce but. Le temps réel passe donc par une vraie session navigateur (l'extension) sur une machine allumée : ton PC, ou un **Oracle Cloud Always Free** (VM ARM gratuite à vie, ~1/6 OCPU) avec le kit `tools/live_worker/` — avec le risque de blocage DataDome lié aux IP datacenter.
