#!/bin/bash
# On ERDC: the first queue under the extended operators (HARNESS-SPLIT.md, decided
# 2026-10-02). Copy it to ~/imagemagick-mutation/setup/ and run it from there under the
# step7 lock, so a git pull cannot change it while it runs:
#
#   nohup flock ~/imagemagick-mutation/setup/step7.lock ~/imagemagick-mutation/setup/day.sh \
#     >> ~/imagemagick-mutation/setup/step7.log 2>&1 &
#
# 1. Pull and rebuild the indexes; 1b. the night's new cases, uncapped, for five files.
# 2. Statement deletion for the 38 Windows files ERDC can build: one build (sdlw), then
#    only the cxx_remove_void_call mutants per file, capped at 1,500 cases
#    (mutation-sdl-<file>.json), for the Windows agent to read.
# 3. Full runs of all 48 Mac files on today's catalogue with the extended operators: one
#    build (ext1), then per file every mutant and the capped survivors at 1,500
#    (mutation-ext-<file>.json, mutation-extcap-<file>.json). These become the Mac
#    files' figures.
# Results are pushed after every fifth file and every step. Each step skips what is
# already done, so the script can be started again after a failure.
SETUP=~/imagemagick-mutation/setup
cd ~/imagemagick-mutation/ImageMagick && . $SETUP/sysroot.env
export ORACLE_JOBS=28
W=build-oracle/work
WIN_FILES="distribute-cache cache-view quantum-import linked-list pixel splay-tree
  quantum-export token matrix blob color stream timer cache magick fx registry quantize distort
  xml-tree option montage prepress quantum signature resource constitute exception feature
  morphology colorspace composite gem histogram monitor resample semaphore deprecate"
MAC_FILES="draw property enhance resize statistic visual-effects effect compare image annotate
  vision threshold attribute shear transform profile segment layer string decorate identify utility
  geometry delegate paint policy compress channel type log configure cipher locale list magic mime
  memory fourier coder colormap random artifact static version thread module client image-view"
push() { $SETUP/push-results.sh > /dev/null 2>&1 && echo "$(date +%H:%M) pushed" || echo "$(date +%H:%M) push failed"; }
regex() { echo "MagickCore/($(echo $* | tr ' ' '|'))\\.c\$"; }

echo "== day $(date): step 1, pull and indexes"
git pull -q && git log --oneline -1
python3 -u tools/oracle/casemap.py > build-oracle/casemap-day.log 2>&1 && \
  python3 -u tools/oracle/linecov.py > build-oracle/linecov-day.log 2>&1 || { echo "indexes failed"; exit 1; }
echo "$(date +%H:%M) indexes rebuilt"

echo "== day $(date): step 1b, the night's new cases, uncapped, for five files"
# confirm.sh capped each survivor at the default case count over the whole gaps
# family, so in functions most cases reach the new cases rarely ran. Rerun the
# survivors against the 63 new cases only (their ids, in the repository), uncapped.
NEW=$(cat tools/oracle/erdc/new-cases-2026-10-01.regex)
for bf in erdc1:magic erdc1:memory erdc1:geometry erdc2:policy erdc2:image; do
  b=${bf%%:*}; f=${bf##*:}
  [ -f $W/mutation-conf2-$f.json ] && continue
  python3 -c "
import json; r = json.load(open('$W/mutation-conf1-$f.json'))
open('$W/conf2-$f.ids', 'w').write(''.join(x['id'] + '\\n' for x in r if x['status'] != 'killed'))"
  python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin build-oracle/mull-$b/utilities/magick \
    --name conf2-$f --ids $W/conf2-$f.ids --cases "$NEW" --max-cases 0 > build-oracle/conf2-$f.log 2>&1
  echo "$(date +%H:%M) conf2-$f: $(grep -E 'killed [0-9]' build-oracle/conf2-$f.log || echo failed)"
done
push

echo "== day $(date): step 2, statement deletion on the Windows files"
BIN=build-oracle/mull-sdlw/utilities/magick
[ -x $BIN ] || tools/oracle/build.sh mull "$(regex $WIN_FILES)" sdlw 2>&1 | tail -1
if [ -x $BIN ]; then
  n=0
  for f in $WIN_FILES; do
    [ -f $W/mutation-sdl-$f.json ] && continue
    python3 - "$f" > $W/sdl-$f.ids <<'PY'
import sys
sys.path.insert(0, "tools/oracle")
import mutate
for m in mutate.list_mutants("build-oracle/mull-sdlw/utilities/magick", r"MagickCore/%s\.c$" % sys.argv[1]):
    if m["mutator"] == "cxx_remove_void_call":
        print(m["id"])
PY
    if [ ! -s $W/sdl-$f.ids ]; then echo "$(date +%H:%M) sdl $f: no statement-deletion mutants"; continue; fi
    python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin $BIN --name sdl-$f \
      --ids $W/sdl-$f.ids --max-cases 1500 > build-oracle/sdl-$f.log 2>&1
    echo "$(date +%H:%M) sdl $f ($(wc -l < $W/sdl-$f.ids) mutants): $(grep -E 'killed [0-9]' build-oracle/sdl-$f.log || echo failed, see build-oracle/sdl-$f.log)"
    n=$((n+1)); [ $((n % 5)) = 0 ] && push
  done
else
  echo "$(date +%H:%M) sdlw build failed, see build-oracle/mull-sdlw/make.log"
fi
push

echo "== day $(date): step 3, extended full runs of the Mac files"
BIN=build-oracle/mull-ext1/utilities/magick
[ -x $BIN ] || tools/oracle/build.sh mull "$(regex $MAC_FILES)" ext1 2>&1 | tail -1
if [ -x $BIN ]; then
  n=0
  for f in $MAC_FILES; do
    if [ ! -f $W/mutation-ext-$f.json ]; then
      python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin $BIN --name ext-$f \
        > build-oracle/ext-$f.log 2>&1
    fi
    [ -f $W/mutation-ext-$f.json ] || { echo "$(date +%H:%M) ext $f: full run failed, see build-oracle/ext-$f.log"; continue; }
    python3 -c "
import json; r = json.load(open('$W/mutation-ext-$f.json'))
open('$W/extcap-$f.ids', 'w').write(''.join(x['id'] + '\n' for x in r if x['status'] == 'survived' and x.get('capped')))"
    if [ -s $W/extcap-$f.ids ] && [ ! -f $W/mutation-extcap-$f.json ]; then
      python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin $BIN --name extcap-$f \
        --ids $W/extcap-$f.ids --max-cases 1500 > build-oracle/extcap-$f.log 2>&1
    fi
    echo "$(date +%H:%M) ext $f: $(grep -E 'killed [0-9]' build-oracle/ext-$f.log) | cap1500: $(grep -E 'killed [0-9]' build-oracle/extcap-$f.log 2>/dev/null)"
    n=$((n+1)); [ $((n % 5)) = 0 ] && push
  done
else
  echo "$(date +%H:%M) ext1 build failed, see build-oracle/mull-ext1/make.log"
fi
push
echo "== day done $(date)"
