#!/usr/bin/env bash
# Lance le worker navigateur permanent de la surveillance live TGV MAX.
#
# Prerequis : Chrome/Chromium installe, extension chargee depuis
# tools/sncf_probe_extension, et une session SNCF Connect connectee dans le
# profil persistant (premier lancement : se connecter manuellement sur
# https://www.sncf-connect.com, faire une recherche, regler le champ
# "Backend live-watch" du popup de l'extension).
#
# Variables d'environnement :
#   CHROME_BIN         binaire Chrome/Chromium (auto-detecte sinon)
#   EXTENSION_DIR      dossier de l'extension (defaut: tools/sncf_probe_extension du repo)
#   PROFILE_DIR        profil Chromium persistant (defaut: ~/.config/max-explorer-live-worker)
#   WATCH_TAB_URL      onglet SNCF Connect ouvert au demarrage
#   BACKEND_BASE_URL   rappele ici pour le reglage du popup (defaut: http://127.0.0.1:8000)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CHROME_BIN="${CHROME_BIN:-}"
EXTENSION_DIR="${EXTENSION_DIR:-$REPO_ROOT/tools/sncf_probe_extension}"
PROFILE_DIR="${PROFILE_DIR:-$HOME/.config/max-explorer-live-worker}"
WATCH_TAB_URL="${WATCH_TAB_URL:-https://www.sncf-connect.com/home/search}"
BACKEND_BASE_URL="${BACKEND_BASE_URL:-http://127.0.0.1:8000}"

if [[ -z "$CHROME_BIN" ]]; then
  for candidate in chromium chromium-browser google-chrome google-chrome-stable chrome; do
    if command -v "$candidate" >/dev/null 2>&1; then
      CHROME_BIN="$(command -v "$candidate")"
      break
    fi
  done
fi
if [[ -z "$CHROME_BIN" ]]; then
  echo "ERREUR: aucun binaire Chrome/Chromium trouve. Installe chromium ou renseigne CHROME_BIN." >&2
  exit 1
fi
if [[ ! -d "$EXTENSION_DIR" ]]; then
  echo "ERREUR: extension introuvable dans $EXTENSION_DIR" >&2
  exit 1
fi

mkdir -p "$PROFILE_DIR"

echo "Worker live TGV MAX"
echo "  binaire   : $CHROME_BIN"
echo "  extension : $EXTENSION_DIR"
echo "  profil    : $PROFILE_DIR"
echo "  onglet    : $WATCH_TAB_URL"
echo "  backend   : $BACKEND_BASE_URL (a regler aussi dans le popup de l'extension, une seule fois)"

CHROME_ARGS=(
  --user-data-dir="$PROFILE_DIR"
  --load-extension="$EXTENSION_DIR"
  --no-first-run
  --no-default-browser-check
  --disable-session-crashed-bubble
  "$WATCH_TAB_URL"
)

if [[ -n "${DISPLAY:-}" ]]; then
  exec "$CHROME_BIN" "${CHROME_ARGS[@]}"
elif command -v xvfb-run >/dev/null 2>&1; then
  exec xvfb-run -a -s "-screen 0 1280x800x24" "$CHROME_BIN" "${CHROME_ARGS[@]}"
else
  echo "ERREUR: pas de DISPLAY et xvfb-run introuvable (sudo apt install xvfb) : impossible de lancer Chromium." >&2
  exit 1
fi
