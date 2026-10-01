#!/bin/bash
# batch.sh BUILD FILE...: one Mull build for the files, then per file a full run and a
# rerun of its capped survivors at 1,500 cases (HARNESS-SPLIT.md step 2). Resumable:
# a finished file is skipped, a half-done one continues from its partial results.
cd ~/imagemagick-mutation/ImageMagick && . ~/imagemagick-mutation/setup/sysroot.env
export ORACLE_JOBS=28
build=$1; shift
RX="MagickCore/($(echo "$@" | tr ' ' '|'))\\.c\$"
echo "== mull build $build $(date): $RX"
tools/oracle/build.sh mull "$RX" "$build" 2>&1 | tail -1
BIN=build-oracle/mull-$build/utilities/magick
for f in "$@"; do
  W=build-oracle/work
  [ -f $W/mutation-full-$f.json ] || python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" \
      --bin $BIN --name full-$f > build-oracle/full-$f.log 2>&1
  [ -f $W/mutation-full-$f.json ] || { echo "$(date +%H:%M) $f: full run failed, see build-oracle/full-$f.log"; continue; }
  python3 -c "
import json; r = json.load(open('$W/mutation-full-$f.json'))
open('$W/capped-$f.ids', 'w').write(''.join(x['id'] + '\n' for x in r if x['status'] == 'survived' and x.get('capped')))"
  if [ -s $W/capped-$f.ids ] && [ ! -f $W/mutation-cap1500-$f.json ]; then
    python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin $BIN --name cap1500-$f \
      --ids $W/capped-$f.ids --max-cases 1500 > build-oracle/cap1500-$f.log 2>&1
  fi
  echo "$(date +%H:%M) $f: $(grep -E 'killed [0-9]' build-oracle/full-$f.log) | cap1500: $(grep -E 'killed [0-9]' build-oracle/cap1500-$f.log 2>/dev/null)"
done
echo "== done $build $(date)"
