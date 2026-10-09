#!/bin/bash
# On ERDC: rerun every Mac file's survivors from its extended full run (day.sh step 3,
# mutation-ext-<file>.json and mutation-extcap-<file>.json) against only the cases
# added since that run's catalogue, uncapped (mutation-extnew-<file>.json). The three
# reports together are the file's figures. Copy it to ~/imagemagick-mutation/setup/
# and run it from there under the step7 lock:
#
#   nohup flock ~/imagemagick-mutation/setup/step7.lock ~/imagemagick-mutation/setup/confirm-new.sh \
#     >> ~/imagemagick-mutation/setup/step7.log 2>&1 &
#
# SINCE is the commit day.sh measured at (its step 1 pull). Each file is skipped once
# its report exists, so the script can be started again after a failure.
SINCE=${SINCE:-17a49b2ac}
SETUP=~/imagemagick-mutation/setup
cd ~/imagemagick-mutation/ImageMagick && . $SETUP/sysroot.env
export ORACLE_JOBS=28
W=build-oracle/work
BIN=build-oracle/mull-ext1/utilities/magick
MAC_FILES="draw property enhance resize statistic visual-effects effect compare image annotate
  vision threshold attribute shear transform profile segment layer string decorate identify utility
  geometry delegate paint policy compress channel type log configure cipher locale list magic mime
  memory fourier coder colormap random artifact static version thread module client image-view"
push() { $SETUP/push-results.sh > /dev/null 2>&1 && echo "$(date +%H:%M) pushed" || echo "$(date +%H:%M) push failed"; }

echo "== confirm-new $(date): pull, indexes, the cases since $SINCE"
git pull -q && git log --oneline -1
python3 -u tools/oracle/casemap.py > build-oracle/casemap-new.log 2>&1 && \
  python3 -u tools/oracle/linecov.py > build-oracle/linecov-new.log 2>&1 || { echo "indexes failed"; exit 1; }
NEW=$(python3 tools/oracle/erdc/new-cases.py $BIN $SINCE 2>> build-oracle/casemap-new.log)
[ -n "$NEW" ] || { echo "$(date +%H:%M) no new-case list; not rerunning against the whole catalogue"; exit 1; }
echo "$(date +%H:%M) $(tail -1 build-oracle/casemap-new.log)"
n=0
for f in $MAC_FILES; do
  [ -f $W/mutation-ext-$f.json ] || continue
  [ -f $W/mutation-extnew-$f.json ] && continue
  python3 - "$f" <<'PY'
import json, os, sys
f = sys.argv[1]; W = "build-oracle/work"; status = {}
for name in ("ext", "extcap"):
    p = "%s/mutation-%s-%s.json" % (W, name, f)
    if os.path.exists(p):
        for r in json.load(open(p)):
            status[r["id"]] = r["status"]
open("%s/extnew-%s.ids" % (W, f), "w").write("".join(i + "\n" for i, s in sorted(status.items()) if s != "killed"))
PY
  [ -s $W/extnew-$f.ids ] || { echo "$(date +%H:%M) extnew $f: nothing left to rerun"; continue; }
  python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin $BIN --name extnew-$f \
    --ids $W/extnew-$f.ids --cases "$NEW" --max-cases 0 > build-oracle/extnew-$f.log 2>&1
  echo "$(date +%H:%M) extnew $f: $(grep -E 'killed [0-9]' build-oracle/extnew-$f.log || echo failed, see build-oracle/extnew-$f.log)"
  n=$((n+1)); [ $((n % 5)) = 0 ] && push
done
push
echo "== confirm-new done $(date)"
