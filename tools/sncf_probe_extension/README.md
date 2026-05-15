# SNCF Connect Probe

POC d'observation reseau pour une vraie session navigateur SNCF Connect.

Objectif :

- ne pas relancer un navigateur automatise,
- ne pas copier un profil,
- ne pas faire de scraping HTTP brut,
- capturer les appels `fetch` et `XMLHttpRequest` emis par l'application web dans une session humaine deja ouverte.

## Installer l'extension

1. Ouvrir Chrome ou Chromium.
2. Aller sur `chrome://extensions`.
3. Activer le `Mode developpeur`.
4. Cliquer sur `Charger l'extension non empaquetee`.
5. Selectionner le dossier :

```text
tools/sncf_probe_extension
```

## Utilisation

1. Ouvrir SNCF Connect dans le navigateur normal.
2. Se connecter et passer les etapes humaines necessaires.
3. Faire une recherche manuelle qui devrait afficher des resultats MAX ou prix.
4. Ouvrir le popup de l'extension.
5. Cliquer sur `Rafraichir` pour voir les appels captures.
6. Cliquer sur `Exporter JSON` pour sauvegarder les evenements.

## Replay dans le navigateur

Le bouton `Rejouer` du popup tente de rejouer le dernier appel `bff/api/v1/itineraries` directement dans l'onglet SNCF Connect courant.

Cela permet de reutiliser :

- les cookies reels,
- la session navigateur reelle,
- le contexte DataDome du navigateur.

Le resultat affiche un resume :

- meilleurs prix par jour,
- nombre de jours a `0 €`,
- offres `0 €` detectees,
- OD et date utilisees.

Le bouton `Rejouer avec params` permet de modifier :

- l'origine,
- la destination,
- la date / heure de depart,

sans refaire la recherche manuellement dans l'interface SNCF Connect. Les noms de gare sont resolves via l'endpoint `autocomplete` du site dans le contexte du vrai navigateur.

## Surveillance automatique

Le bouton `Surveiller` enregistre le trajet courant du formulaire et active une verification automatique toutes les 5 minutes.
Un premier check est lance immediatement apres la creation de la surveillance.

Pour la surveillance, l'heure du formulaire est ignoree :

- seule la date locale est conservee,
- la surveillance est pensee comme une surveillance de journee entiere,
- l'extension rejoue ensuite une heure technique fixe pour interroger l'API sur cette journee.

Comportement :

- l'extension cherche un onglet `sncf-connect.com` ouvert,
- rejoue l'appel `itineraries` dans ce vrai navigateur,
- compare les `travelId` a `0 €` avec l'etat precedent,
- affiche une notification locale quand un nouveau train a `0 €` apparait.

Conditions :

- Chrome/Chromium doit rester ouvert,
- au moins un onglet SNCF Connect doit rester ouvert,
- la session SNCF Connect doit rester valide.

## Backend configurable

Le champ `Backend live-watch` du popup permet de choisir ou pousser l'etat des surveillances et ou lire le plan:

- en local : `http://127.0.0.1:8000`
- sur un site distant : par exemple `https://ton-app.onrender.com`

Cela permet de garder l'application web sur un hebergement distant, meme si le moteur navigateur tourne ailleurs.

Conseils d'exploitation :

- si tu refais une recherche manuelle SNCF Connect, l'extension reutilise automatiquement le dernier appel `itineraries` capture comme seed pour les surveillances suivantes ;
- le bouton `Verifier maintenant` force un cycle immediat sans attendre les 5 minutes ;
- si la cle API du seed devient invalide, une recherche manuelle fraiche sur SNCF Connect suffit en pratique a reamorcer les surveillances sans les recreer.

## Ce qui est capture

- URL
- methode HTTP
- statut
- duree
- apercu du body de requete si c'est une chaine
- headers de reponse
- apercu du body de reponse pour les contenus JSON et texte

## Limites

- Le hook ne voit que ce qui transite par `fetch` et `XMLHttpRequest`.
- Si SNCF Connect utilise un transport natif non hooke, il faudra etendre le probe.
- Les bodies binaires ne sont pas exportes.
- Les apercus sont tronques a 20 000 caracteres pour rester lisibles.

## Etape suivante

Une fois un export obtenu, on pourra :

1. identifier les endpoints vraiment utiles,
2. voir si les reponses contiennent la disponibilite MAX a `0 EUR`,
3. construire ensuite un parser cible sur ces payloads plutot que sur le DOM.
