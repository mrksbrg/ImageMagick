#!/bin/bash
# Push ERDC's mutation reports and logs to the erdc-results branch of the fork.
set -euo pipefail
SRC=~/imagemagick-mutation/ImageMagick
DST=~/imagemagick-mutation/results
if [ ! -d "$DST/.git" ]; then
  git init -q -b erdc-results "$DST"
  git -C "$DST" remote add origin https://github.com/mrksbrg/ImageMagick.git
  git -C "$DST" config credential.helper "store --file $HOME/.git-credentials-erdc"
  git -C "$DST" config user.name "ERDC (for Markus Borg)"
  git -C "$DST" config user.email markus.borg@cs.lth.se
fi
mkdir -p "$DST/work" "$DST/logs" "$DST/setup"
for f in "$SRC"/build-oracle/work/mutation-*.json; do
  b=$(basename "$f"); cp -p "$f" "$DST/work/${b/mutation-/mutation-erdc-}"
done
cp -p "$SRC"/build-oracle/*.log "$DST/logs/" 2>/dev/null || true
cp -p ~/imagemagick-mutation/setup/*.sh ~/imagemagick-mutation/setup/*.log "$DST/setup/"
rev=$(git -C "$SRC" rev-parse --short HEAD)
echo "$rev" > "$DST/MEASURED_AT"
git -C "$DST" add -A
if git -C "$DST" diff --cached --quiet; then echo "nothing new"; exit 0; fi
git -C "$DST" commit -q -m "ERDC results, $(date -u '+%F %H:%M') UTC, ImageMagick at $rev"
git -C "$DST" push -u origin erdc-results
