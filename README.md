# Max Explorer

Application web Python pour explorer les trajets `TGV MAX` a 0 EUR avec :

- les trains disponibles par jour depuis une gare ou une ville,
- une carte des destinations accessibles,
- des suggestions d'aller-retour dans la journee,
- des itineraires avec correspondances `MAX`,
- un mode hybride `MAX + TER` quand une cle API SNCF est fournie.

## Sources de donnees

- `tgvmax` SNCF Open Data : disponibilite a 30 jours des places MAX.
- `gares-de-voyageurs` SNCF Open Data : referentiel des gares et geolocalisation.
- API SNCF/Navitia optionnelle pour les trajets hybrides `MAX + TER`.

## Lancer le projet

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Puis ouvrir [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Variables utiles

- `SNCF_API_TOKEN` : active le mode hybride `MAX + TER`.
- `MAX_EXPLORER_REFRESH_HOURS` : frequence de refresh du cache local.
- `MAX_EXPLORER_DATA_DIR` : emplacement du cache local.

## Activer le mode MAX + TER

Je ne peux pas generer la cle `SNCF_API_TOKEN` a ta place : elle doit etre demandee depuis ton propre acces a l'API SNCF/Navitia.

Etapes :

1. Demander un token developpeur sur le formulaire SNCF.
2. Attendre la reception de la cle.
3. Exporter la cle dans ton shell.
4. Relancer le serveur.

Exemple :

```bash
export SNCF_API_TOKEN="ton_token_ici"
uv run uvicorn app.main:app --reload
```

Verification rapide :

```bash
echo "$SNCF_API_TOKEN"
```

Si la variable est vide, la page `MAX + TER` restera desactivee.

## Lancer les tests

```bash
uv run pytest
```

## Notes

- Le dataset `tgvmax` couvre une fenetre glissante d'environ 30 jours.
- Sans `SNCF_API_TOKEN`, toutes les vues `MAX` fonctionnent, mais les prolongements `TER` sont desactives.
- La carte s'appuie sur Leaflet et des tuiles OpenStreetMap.
