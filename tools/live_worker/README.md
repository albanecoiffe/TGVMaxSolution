# Worker live 24/7 (sans laisser ton PC portable allumé)

## Limites actuelles de l'extension

- la machine worker doit rester **allumée et non en veille** ;
- **Chrome/Chromium doit tourner** avec l'extension `tools/sncf_probe_extension` chargée ;
- **au moins un onglet `sncf-connect.com` doit rester ouvert et connecté** (l'extension en ouvre un dédié, épinglé) ;
- cadence : 1 check/min par défaut, 30 s entre 06:00 et 12:00 (burst), max 3 scans de dates par trajet et par cycle ;
- la session SNCF Connect expire (clé BFF / cookies DataDome) : il suffit alors de **refaire une recherche manuelle** sur SNCF Connect, l'extension réamorce automatiquement les surveillances ;
- les notifications du navigateur sont **locales à la machine worker** : pour les alertes à distance, vois le watchdog ci-dessous et la page `/live-watch` hébergée sur Render ;
- un téléphone ne peut pas faire tourner l'extension (Chrome mobile ne supporte pas les extensions).

Le backend (site + API + historique) tourne lui 24/7 sur Render via `render.yaml` ; seul le **moteur navigateur** a besoin d'une machine dédiée.

## Options pour une machine toujours allumée

1. **Raspberry Pi / mini-PC / NAS à la maison** (recommandé, ~3-8 W) : installe Chromium + xvfb, clone le repo, branche le service systemd ci-dessous.
2. **VPS pas cher** : possible, mais l'IP datacenter et l'absence d'empreinte navigateur humaine augmentent le risque de blocage DataDome. À tester, déconseillé en premier.
3. **Ton PC portable** : fonctionne, mais doit rester allumé — d'où ce kit.

## Installation sur une machine dédiée (ex. Raspberry Pi OS)

```bash
sudo apt update && sudo apt install -y chromium xvfb
# desactive la veille :
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

# clone le repo dans le home de l'utilisateur :
git clone https://github.com/albanecoiffe/TGVMaxSolution.git ~/TGVMaxSolution

# installe le service utilisateur :
mkdir -p ~/.config/systemd/user
cp ~/TGVMaxSolution/tools/live_worker/max-explorer-live-worker.service ~/.config/systemd/user/
# adapte le chemin ExecStart dans ce fichier (~/TGVMaxSolution/...)
systemctl --user daemon-reload
systemctl --user enable --now max-explorer-live-worker.service
```

Premier lancement : ouvre le popup de l'extension dans ce Chromium, connecte-toi à SNCF Connect, fais **une recherche manuelle**, puis règle le champ **Backend live-watch** sur :

- `https://ton-app.onrender.com` si le backend est sur Render (recommandé, consultable depuis n'importe où),
- ou `http://127.0.0.1:8000` si le backend tourne en local sur la même machine.

Le réglage est persistant (profil Chromium dédié dans `~/.config/max-explorer-live-worker`).

## Watchdog + alertes à distance (cron)

`check_live_worker.py` interroge le backend et sort :

- 0 = worker OK, pas d'alerte récente,
- 1 = worker down / heartbeat périmé / onglet SNCF non prêt,
- 2 = worker OK mais alerte 0 EUR (`zero_added` / `zero_day_added`) dans la fenêtre.

Exemple cron (toutes les 5 min, la sortie non vide déclenche le mail cron) :

```cron
*/5 * * * * python3 ~/TGVMaxSolution/tools/live_worker/check_live_worker.py --base-url https://ton-app.onrender.com --max-age-minutes 5 >> ~/.max-explorer-watchdog.log 2>&1
```

Depuis n'importe quel appareil, tu peux aussi consulter directement :

- `GET https://ton-app.onrender.com/api/live-watch/latest` (état complet)
- `GET https://ton-app.onrender.com/api/live-watch/zero-calendar` (jours à 0 €)
- `GET https://ton-app.onrender.com/api/live-watch/zero-vs-dataset` (trains 0 € live absents de la base API)
- `GET https://ton-app.onrender.com/live-watch` (page visuelle)

## Fichiers

- `run-live-worker.sh` : lance Chromium avec l'extension et l'onglet SNCF (xvfb si pas de DISPLAY).
- `max-explorer-live-worker.service` : unité systemd utilisateur (redémarrage auto).
- `check_live_worker.py` : watchdog / relai d'alertes (stdlib uniquement).
