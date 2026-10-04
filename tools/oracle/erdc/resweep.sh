#!/bin/bash
# On ERDC: a standing re-sweep that keeps the container busy when the confirm-loop is idle.
# Start it once, alongside the confirm-loop:
#
#   nohup ~/imagemagick-mutation/setup/resweep.sh >> ~/imagemagick-mutation/setup/step7.log 2>&1 &
#
# It re-measures every Mac file in full against the CURRENT catalogue (one fresh report per file,
# mutation-resweep-<file>.json), so kills from cases added since the last full run are picked up and
# each file gets one consistent figure. It takes the step7 lock per file, so it never overlaps a
# confirm-loop round (which also holds that lock) and simply runs in the gaps between rounds. A file
# is skipped once its report exists, so it can be restarted after a failure; delete a file's report
# to force a re-run. When every file is done it pulls, and if cases.py changed since the sweep began
# it starts a fresh sweep (new reports), otherwise it waits and checks again. Stop with
# pkill -f resweep.sh.
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

sweep() {
  local head n=0 f
  git pull -q; head=$(git rev-parse --short HEAD)
  python3 -u tools/oracle/casemap.py > build-oracle/casemap-resweep.log 2>&1 && \
    python3 -u tools/oracle/linecov.py > build-oracle/linecov-resweep.log 2>&1 || { echo "$(date +%H:%M) resweep: indexes failed"; return 1; }
  echo "== resweep $(date): all Mac files at $head, untrusted first"
  # untrusted files first, so the figures that matter refresh soonest
  for f in profile log delegate configure mime policy memory annotate draw string locale image utility \
           $MAC_FILES; do
    [ -f $W/mutation-resweep-$f.json ] && continue
    exec 9> $SETUP/step7.lock; flock 9           # wait out any confirm-loop round
    python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin $BIN --name resweep-$f \
      > build-oracle/resweep-$f.log 2>&1
    flock -u 9; exec 9>&-
    echo "$(date +%H:%M) resweep $f: $(grep -E 'killed [0-9]' build-oracle/resweep-$f.log | tail -1 || echo 'failed, see build-oracle/resweep-'$f'.log')"
    n=$((n+1)); [ $((n % 3)) = 0 ] && push
  done
  push
  echo "== resweep pass done $(date), at $head"
  echo "$head" > $SETUP/resweep.at
}

echo "== resweep started $(date)"
while true; do
  # a file still to do in this pass?
  todo=0
  for f in $MAC_FILES; do [ -f $W/mutation-resweep-$f.json ] || { todo=1; break; }; done
  if [ $todo = 1 ]; then
    sweep
  else
    # pass complete: start a new one only when the catalogue has moved on, else idle-check
    git pull -q
    if [ -f $SETUP/resweep.at ] && ! git diff --quiet "$(cat $SETUP/resweep.at)" HEAD -- tools/oracle/cases.py 2>/dev/null; then
      echo "$(date +%H:%M) resweep: cases changed since last pass, starting fresh"
      rm -f $W/mutation-resweep-*.json
    else
      sleep 1800
    fi
  fi
done
