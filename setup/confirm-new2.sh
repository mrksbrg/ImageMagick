#!/bin/bash
# On ERDC: the second confirm-new round. confirm-new.sh reran each Mac file's survivors
# against the cases added up to bf51acd29; this reruns what still survives (ext, extcap and
# extnew merged) against the cases added since, uncapped (mutation-extnew2-<file>.json).
# Run it under the step7 lock, so that it starts once confirm-new.sh has finished:
#
#   nohup flock ~/imagemagick-mutation/setup/step7.lock ~/imagemagick-mutation/setup/confirm-new2.sh \
#     >> ~/imagemagick-mutation/setup/step7.log 2>&1 &
#
# Each file is skipped once its report exists, so the script can be started again.
SINCE=${SINCE:-bf51acd29}
SETUP=~/imagemagick-mutation/setup
cd ~/imagemagick-mutation/ImageMagick && . $SETUP/sysroot.env
export ORACLE_JOBS=28
W=build-oracle/work
BIN=build-oracle/mull-ext1/utilities/magick
# the files still short of 80% first, then the rest
MAC_FILES="property image annotate string utility draw layer policy locale memory configure delegate
  profile mime log transform attribute paint type geometry channel enhance resize statistic
  visual-effects effect compare vision threshold shear segment decorate identify compress cipher
  list magic fourier coder colormap random artifact static version thread module client image-view"
push() { $SETUP/push-results.sh > /dev/null 2>&1 && echo "$(date +%H:%M) pushed" || echo "$(date +%H:%M) push failed"; }

echo "== confirm-new2 $(date): pull, indexes, the cases since $SINCE"
git pull -q && git log --oneline -1
python3 -u tools/oracle/casemap.py > build-oracle/casemap-new2.log 2>&1 && \
  python3 -u tools/oracle/linecov.py > build-oracle/linecov-new2.log 2>&1 || { echo "indexes failed"; exit 1; }
NEW=$(python3 tools/oracle/erdc/new-cases.py $BIN $SINCE 2>> build-oracle/casemap-new2.log)
[ -n "$NEW" ] || { echo "$(date +%H:%M) no new-case list; not rerunning against the whole catalogue"; exit 1; }
echo "$(date +%H:%M) $(tail -1 build-oracle/casemap-new2.log)"
n=0
for f in $MAC_FILES; do
  [ -f $W/mutation-ext-$f.json ] || continue
  [ -f $W/mutation-extnew2-$f.json ] && continue
  python3 - "$f" <<'PY'
import json, os, sys
f = sys.argv[1]; W = "build-oracle/work"; status = {}
for name in ("ext", "extcap", "extnew"):
    p = "%s/mutation-%s-%s.json" % (W, name, f)
    if os.path.exists(p):
        for r in json.load(open(p)):
            if status.get(r["id"]) != "killed":  # a kill stands
                status[r["id"]] = r["status"]
open("%s/extnew2-%s.ids" % (W, f), "w").write("".join(i + "\n" for i, s in sorted(status.items()) if s != "killed"))
PY
  [ -s $W/extnew2-$f.ids ] || { echo "$(date +%H:%M) extnew2 $f: nothing left to rerun"; continue; }
  python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin $BIN --name extnew2-$f \
    --ids $W/extnew2-$f.ids --cases "$NEW" --max-cases 0 > build-oracle/extnew2-$f.log 2>&1
  echo "$(date +%H:%M) extnew2 $f: $(grep -E 'killed [0-9]' build-oracle/extnew2-$f.log || echo failed, see build-oracle/extnew2-$f.log)"
  n=$((n+1)); [ $((n % 3)) = 0 ] && push
done
push
echo "== confirm-new2 done $(date)"
