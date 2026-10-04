#!/bin/bash
# On ERDC: confirmation rounds whenever the fork has new cases. Start once:
#
#   nohup ~/imagemagick-mutation/setup/confirm-loop.sh >> ~/imagemagick-mutation/setup/step7.log 2>&1 &
#
# Every 30 minutes it fetches refactoring-setup. When tools/oracle/cases.py has changed since the
# last round, it takes the step7 lock (so it never overlaps another queue) and runs a round:
# pull, imdriver, indexes, a determinism sweep of the new cases, then every Mac file's survivors
# (all ERDC reports merged; kills by unstable-killers.json cases not counted) against the new
# cases, uncapped (mutation-confirm-<commit>-<file>.json), untrusted files first, a push every
# third file. The last confirmed commit is kept in setup/confirm-loop.last. Stop it with
# pkill -f confirm-loop.sh.
SETUP=~/imagemagick-mutation/setup
LAST_FILE=$SETUP/confirm-loop.last
[ -f $LAST_FILE ] || echo "${START:-0c905bc73}" > $LAST_FILE
cd ~/imagemagick-mutation/ImageMagick && . $SETUP/sysroot.env
export ORACLE_JOBS=28
W=build-oracle/work
BIN=build-oracle/mull-ext1/utilities/magick
MAC_FILES="draw image profile string annotate property utility policy locale memory configure delegate
  mime log type layer transform attribute paint geometry channel enhance resize statistic
  visual-effects effect compare vision threshold shear segment decorate identify compress cipher
  list magic fourier coder colormap random artifact static version thread module client image-view"
push() { $SETUP/push-results.sh > /dev/null 2>&1 && echo "$(date +%H:%M) pushed" || echo "$(date +%H:%M) push failed"; }

round() {
  local last=$1 head
  git pull -q || { echo "$(date +%H:%M) confirm-loop: pull failed"; return 1; }
  head=$(git rev-parse --short HEAD)
  echo "== confirm-loop $(date): cases since $last, at $(git log --oneline -1 | cut -c1-70)"
  tools/oracle/driver/build.sh build-oracle/mull-ext1 > build-oracle/imdriver-ext1.log 2>&1 \
    || echo "$(date +%H:%M) imdriver failed, see build-oracle/imdriver-ext1.log"
  python3 -u tools/oracle/casemap.py > build-oracle/casemap-loop.log 2>&1 && \
    python3 -u tools/oracle/linecov.py > build-oracle/linecov-loop.log 2>&1 || { echo "indexes failed"; return 1; }
  NEW=$(python3 tools/oracle/erdc/new-cases.py $BIN $last 2>> build-oracle/casemap-loop.log)
  if [ -z "$NEW" ]; then
    echo "$(date +%H:%M) no new cases since $last"; echo "$head" > $LAST_FILE; return 0
  fi
  echo "$(date +%H:%M) $(tail -1 build-oracle/casemap-loop.log)"
  python3 -u tools/oracle/oracle.py selfcheck --base-bin $BIN --repeat 6 -j 56 --filter "$NEW" \
    > build-oracle/selfcheck-loop.log 2>&1
  grep -A40 "^selfcheck:" build-oracle/selfcheck-loop.log | sed "s/^/$(date +%H:%M) /"
  rm -rf $W/runs/self[0-9]*
  local n=0 f
  for f in $MAC_FILES; do
    [ -f $W/mutation-ext-$f.json ] || continue
    [ -f $W/mutation-confirm-$head-$f.json ] && continue
    python3 - "$f" <<'PY'
import glob, json, os, sys
sys.path.insert(0, "tools/oracle"); import gate
f = sys.argv[1]; W = "build-oracle/work"; status = {}
reports = ["%s/mutation-%s-%s.json" % (W, n, f) for n in ("ext", "extcap", "extnew", "extnew2", "extnew3", "uncap2")]
reports += sorted(glob.glob("%s/mutation-confirm-*-%s.json" % (W, f)))
for p in reports:
    if os.path.exists(p):
        for r in map(gate.honest, json.load(open(p))):
            if status.get(r["id"]) != "killed":  # a kill stands
                status[r["id"]] = r["status"]
open("%s/confirm-%s.ids" % (W, f), "w").write("".join(i + "\n" for i, s in sorted(status.items()) if s != "killed"))
PY
    [ -s $W/confirm-$f.ids ] || continue
    python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin $BIN --name confirm-$head-$f \
      --ids $W/confirm-$f.ids --cases "$NEW" --max-cases 0 > build-oracle/confirm-$f.log 2>&1
    echo "$(date +%H:%M) confirm $f: $(grep -E 'killed [0-9]' build-oracle/confirm-$f.log || echo failed, see build-oracle/confirm-$f.log)"
    n=$((n+1)); [ $((n % 3)) = 0 ] && push
  done
  push
  echo "$head" > $LAST_FILE
  echo "== confirm-loop round done $(date)"
}

echo "== confirm-loop started $(date), last confirmed $(cat $LAST_FILE)"
while true; do
  last=$(cat $LAST_FILE)
  if git fetch -q origin refactoring-setup && \
     ! git diff --quiet "$last" FETCH_HEAD -- tools/oracle/cases.py 2>/dev/null; then
    exec 9> $SETUP/step7.lock
    flock 9   # waits while another queue holds the lock
    round "$last"
    flock -u 9
    exec 9>&-
  fi
  sleep 1800
done
