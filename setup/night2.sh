#!/bin/bash
# On ERDC, the night of 2026-10-03: two MagickCore jobs, about 11 hours in all.
#
#   nohup flock ~/imagemagick-mutation/setup/step7.lock ~/imagemagick-mutation/setup/night2.sh \
#     >> ~/imagemagick-mutation/setup/step7.log 2>&1 &
#
# 1. Pull and rebuild the indexes.
# 2. A determinism sweep: every case six times under twice as many jobs as cores
#    (build-oracle/selfcheck-night2.log). Two cases found flaky on 2026-10-03 had faked
#    85 kills; a flaky case found here goes into unstable-killers.json on the Mac. ~1 h.
# 3. The 798 capped survivors no report has killed (uncap-2026-10-03.json), each against
#    every case that reaches it, uncapped (mutation-uncap2-<file>.json); the untrusted files
#    first. The uncapped run of 2026-10-01 took 0.7 min a mutant, so ~10 h.
# Results are pushed after the sweep and every third file. A file is skipped once its
# report exists, so the script can be started again after a failure.
SETUP=~/imagemagick-mutation/setup
cd ~/imagemagick-mutation/ImageMagick && . $SETUP/sysroot.env
export ORACLE_JOBS=28
W=build-oracle/work
BIN=build-oracle/mull-ext1/utilities/magick
LIST=tools/oracle/erdc/uncap-2026-10-03.json
push() { $SETUP/push-results.sh > /dev/null 2>&1 && echo "$(date +%H:%M) pushed" || echo "$(date +%H:%M) push failed"; }

echo "== night2 $(date): step 1, pull and indexes"
git pull -q && git log --oneline -1
python3 -u tools/oracle/casemap.py > build-oracle/casemap-night2.log 2>&1 && \
  python3 -u tools/oracle/linecov.py > build-oracle/linecov-night2.log 2>&1 || { echo "indexes failed"; exit 1; }
echo "$(date +%H:%M) indexes rebuilt"

echo "== night2 $(date): step 2, determinism sweep"
if [ ! -f build-oracle/selfcheck-night2.log ] || ! grep -q "^selfcheck:" build-oracle/selfcheck-night2.log; then
  python3 -u tools/oracle/oracle.py selfcheck --base-bin $BIN --repeat 6 -j 56 > build-oracle/selfcheck-night2.log 2>&1
fi
grep -A40 "^selfcheck:" build-oracle/selfcheck-night2.log | sed "s/^/$(date +%H:%M) /"
rm -rf $W/runs/self[0-9]*  # kept by selfcheck when a case was flaky; the log has what matters
push

echo "== night2 $(date): step 3, capped survivors uncapped"
n=0
for f in $(python3 -c "import json; print(' '.join(json.load(open('$LIST'))['order']))"); do
  [ -f $W/mutation-uncap2-$f.json ] && continue
  python3 -c "import json, os, sys; print('\n'.join(i.replace(':MagickCore/', ':%s/MagickCore/' % os.getcwd(), 1)
              for i in json.load(open('$LIST'))['ids'][sys.argv[1]]))" $f > $W/uncap2-$f.ids  # ids are stored repository-relative
  python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin $BIN --name uncap2-$f \
    --ids $W/uncap2-$f.ids --max-cases 0 > build-oracle/uncap2-$f.log 2>&1
  echo "$(date +%H:%M) uncap2 $f ($(grep -c . $W/uncap2-$f.ids)): $(grep -E 'killed [0-9]' build-oracle/uncap2-$f.log || echo failed, see build-oracle/uncap2-$f.log)"
  n=$((n+1)); [ $((n % 3)) = 0 ] && push
done
push
echo "== night2 done $(date)"
