#!/bin/bash
# On ERDC: a night's queue for the Mac's files (HARNESS-SPLIT.md). Copy it to
# ~/imagemagick-mutation/setup/ and run it from there under the step7 lock, so a
# git pull cannot change it while it runs:
#
#   nohup flock ~/imagemagick-mutation/setup/step7.lock ~/imagemagick-mutation/setup/night.sh \
#     >> ~/imagemagick-mutation/setup/step7.log 2>&1 &
#
# 1. confirm.sh for fourier.c and list.c (pulls, rebuilds the indexes).
# 2. The operator trial: one Mull build of every Mac file with statement deletion
#    (cxx_remove_void_call) added to the defaults, then per file only the new
#    mutants, capped at 1,500 cases (reports mutation-sdl-<file>.json).
# 3. Full runs of the ten Phase 1 files on today's catalogue, default operators
#    (batch.sh: full run, then the capped survivors at 1,500).
# Results are pushed after every step and every tenth file. Each step skips what
# is already done, so the script can be started again after a failure.
SETUP=~/imagemagick-mutation/setup
cd ~/imagemagick-mutation/ImageMagick && . $SETUP/sysroot.env
export ORACLE_JOBS=28
W=build-oracle/work
MAC_FILES="draw property enhance resize statistic visual-effects effect compare image annotate
  vision threshold attribute shear transform profile segment layer string decorate identify utility
  geometry delegate paint policy compress channel type log configure cipher locale list magic mime
  memory fourier coder colormap random artifact static version thread module client image-view"
PHASE1="resize compare enhance visual-effects statistic threshold shear segment decorate colormap"
push() { $SETUP/push-results.sh > /dev/null 2>&1 && echo "$(date +%H:%M) pushed" || echo "$(date +%H:%M) push failed"; }

echo "== night $(date): step 1, confirm fourier list"
$SETUP/confirm.sh erdc1:fourier erdc1:list
push

echo "== night $(date): step 2, statement deletion on the Mac files"
RX="MagickCore/($(echo $MAC_FILES | tr ' ' '|'))\\.c\$"
BIN=build-oracle/mull-sdl/utilities/magick
[ -x $BIN ] || MULL_MUTATORS="cxx_default cxx_remove_void_call" \
  tools/oracle/build.sh mull "$RX" sdl 2>&1 | tail -1
if [ -x $BIN ]; then
  n=0
  for f in $MAC_FILES; do
    [ -f $W/mutation-sdl-$f.json ] && continue
    python3 - "$f" > $W/sdl-$f.ids <<'PY'
import sys
sys.path.insert(0, "tools/oracle")
import mutate
f = sys.argv[1]
for m in mutate.list_mutants("build-oracle/mull-sdl/utilities/magick", r"MagickCore/%s\.c$" % f):
    if m["mutator"] == "cxx_remove_void_call":
        print(m["id"])
PY
    if [ ! -s $W/sdl-$f.ids ]; then echo "$(date +%H:%M) sdl $f: no statement-deletion mutants"; continue; fi
    python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin $BIN --name sdl-$f \
      --ids $W/sdl-$f.ids --max-cases 1500 > build-oracle/sdl-$f.log 2>&1
    echo "$(date +%H:%M) sdl $f ($(wc -l < $W/sdl-$f.ids) mutants): $(grep -E 'killed [0-9]' build-oracle/sdl-$f.log || echo failed, see build-oracle/sdl-$f.log)"
    n=$((n+1)); [ $((n % 10)) = 0 ] && push
  done
else
  echo "$(date +%H:%M) sdl build failed, see build-oracle/mull-sdl/make.log"
fi
push

echo "== night $(date): step 3, Phase 1 files on today's catalogue"
$SETUP/batch.sh erdc4 $PHASE1
push
echo "== night done $(date)"
