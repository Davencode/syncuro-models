#!/bin/sh
# Pubblica lo stato attuale del catalogo come nuova versione.
#
#   tools/publish.sh v0.2.0
#
# Crea il tag, aggiorna index.json (che l'app legge da main) e svuota la
# cache di jsDelivr per index.json, così l'app vede subito la nuova versione.
set -eu

tag="${1:-}"
case "$tag" in
  v[0-9]*.[0-9]*.[0-9]*) ;;
  *) echo "Uso: tools/publish.sh vX.Y.Z" >&2; exit 1 ;;
esac

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Ci sono modifiche non committate: committale prima di pubblicare." >&2
  exit 1
fi
python3 -I -c "import json; json.load(open('catalog.json'))"

git tag "$tag"
git push origin "$tag"

printf '{\n  "schemaVersion": 1,\n  "catalogTag": "%s"\n}\n' "$tag" > index.json
git add index.json
git commit -m "Publish $tag"
git push origin main

curl -fsS "https://purge.jsdelivr.net/gh/Davencode/syncuro-models@main/index.json" > /dev/null
echo "Pubblicato $tag"
