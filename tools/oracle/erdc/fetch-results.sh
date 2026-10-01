#!/bin/bash
# On the Mac: fetch ERDC's reports from the erdc-results branch into build-oracle/work.
#
#   tools/oracle/erdc/fetch-results.sh
#
# ERDC's absolute paths are rewritten to this checkout's, as the reports would read
# had they been made here; the figures themselves are ERDC's (HARNESS-SPLIT.md).
# Prints which reports are new or changed since the last fetch.
set -euo pipefail
ROOT=$(git rev-parse --show-toplevel)
ERDC=/home/jovyan/imagemagick-mutation/ImageMagick
git -C "$ROOT" fetch -q origin erdc-results
echo "ERDC measured at $(git -C "$ROOT" show origin/erdc-results:MEASURED_AT)"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git -C "$ROOT" archive origin/erdc-results work | tar x -C "$tmp"
mkdir -p "$ROOT/build-oracle/work"
for f in "$tmp"/work/*.json; do
  t="$ROOT/build-oracle/work/$(basename "$f")"
  sed "s#$ERDC#$ROOT#g" "$f" > "$tmp/rewritten"
  if [ ! -e "$t" ]; then echo "new      $(basename "$f")"
  elif ! cmp -s "$tmp/rewritten" "$t"; then echo "changed  $(basename "$f")"
  else continue; fi
  mv "$tmp/rewritten" "$t"
done
