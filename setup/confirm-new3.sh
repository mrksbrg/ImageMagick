#!/bin/bash
# On ERDC: the third confirm-new round, queued behind night2.sh under the step7 lock:
#
#   nohup flock ~/imagemagick-mutation/setup/step7.lock ~/imagemagick-mutation/setup/confirm-new3.sh \
#     >> ~/imagemagick-mutation/setup/step7.log 2>&1 &
#
# 1. Pull, build imdriver (the C driver, tools/oracle/driver) against the mutation build; the
#    coverage and base builds get theirs from tools/oracle/build.sh as casemap rebuilds them.
#    Rebuild the indexes.
# 2. A determinism sweep of the cases added since 58568f861 (ICC, 8BIM, EXIF, masks, driver
#    and Ghostscript cases, never run on Linux), six runs under 56 jobs.
# 3. Each Mac file's survivors (ext, extcap, extnew, extnew2 and uncap2 merged; kills by
#    unstable-killers.json cases not counted) against the cases added since 58568f861,
#    uncapped (mutation-extnew3-<file>.json); untrusted files first, a push every third file.
# Without Ghostscript on ERDC its two cases fail alike in every run and count for nothing.
# Each file is skipped once its report exists, so the script can be started again.
SINCE=${SINCE:-58568f861}
SETUP=~/imagemagick-mutation/setup
cd ~/imagemagick-mutation/ImageMagick && . $SETUP/sysroot.env
export ORACLE_JOBS=28
W=build-oracle/work
BIN=build-oracle/mull-ext1/utilities/magick
MAC_FILES="draw image profile string annotate property utility policy locale memory configure delegate
  mime log type layer transform attribute paint geometry channel enhance resize statistic
  visual-effects effect compare vision threshold shear segment decorate identify compress cipher
  list magic fourier coder colormap random artifact static version thread module client image-view"
push() { $SETUP/push-results.sh > /dev/null 2>&1 && echo "$(date +%H:%M) pushed" || echo "$(date +%H:%M) push failed"; }

echo "== confirm-new3 $(date): pull, imdriver, indexes"
git pull -q && git log --oneline -1
tools/oracle/driver/build.sh build-oracle/mull-ext1 > build-oracle/imdriver-ext1.log 2>&1 \
  && echo "$(date +%H:%M) imdriver built" || echo "$(date +%H:%M) imdriver failed, see build-oracle/imdriver-ext1.log"
python3 -u tools/oracle/casemap.py > build-oracle/casemap-new3.log 2>&1 && \
  python3 -u tools/oracle/linecov.py > build-oracle/linecov-new3.log 2>&1 || { echo "indexes failed"; exit 1; }
NEW=$(python3 tools/oracle/erdc/new-cases.py $BIN $SINCE 2>> build-oracle/casemap-new3.log)
[ -n "$NEW" ] || { echo "$(date +%H:%M) no new-case list; not rerunning against the whole catalogue"; exit 1; }
echo "$(date +%H:%M) $(tail -1 build-oracle/casemap-new3.log)"

echo "== confirm-new3 $(date): determinism sweep of the new cases"
python3 -u tools/oracle/oracle.py selfcheck --base-bin $BIN --repeat 6 -j 56 --filter "$NEW" \
  > build-oracle/selfcheck-new3.log 2>&1
grep -A40 "^selfcheck:" build-oracle/selfcheck-new3.log | sed "s/^/$(date +%H:%M) /"
rm -rf $W/runs/self[0-9]*
push

echo "== confirm-new3 $(date): survivors against the new cases"
n=0
for f in $MAC_FILES; do
  [ -f $W/mutation-ext-$f.json ] || continue
  [ -f $W/mutation-extnew3-$f.json ] && continue
  python3 - "$f" <<'PY'
import json, os, sys
sys.path.insert(0, "tools/oracle"); import gate
f = sys.argv[1]; W = "build-oracle/work"; status = {}
for name in ("ext", "extcap", "extnew", "extnew2", "uncap2"):
    p = "%s/mutation-%s-%s.json" % (W, name, f)
    if os.path.exists(p):
        for r in map(gate.honest, json.load(open(p))):
            if status.get(r["id"]) != "killed":  # a kill stands
                status[r["id"]] = r["status"]
open("%s/extnew3-%s.ids" % (W, f), "w").write("".join(i + "\n" for i, s in sorted(status.items()) if s != "killed"))
PY
  [ -s $W/extnew3-$f.ids ] || { echo "$(date +%H:%M) extnew3 $f: nothing left to rerun"; continue; }
  python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin $BIN --name extnew3-$f \
    --ids $W/extnew3-$f.ids --cases "$NEW" --max-cases 0 > build-oracle/extnew3-$f.log 2>&1
  echo "$(date +%H:%M) extnew3 $f: $(grep -E 'killed [0-9]' build-oracle/extnew3-$f.log || echo failed, see build-oracle/extnew3-$f.log)"
  n=$((n+1)); [ $((n % 3)) = 0 ] && push
done
push
echo "== confirm-new3 done $(date)"
