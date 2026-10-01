#!/bin/bash
# HARNESS-SPLIT.md step 2 on ERDC: one Mull build for the files, then per file a full run
# and a rerun of the capped survivors at 1,500 cases.
cd ~/imagemagick-mutation/ImageMagick && . ~/sysroot.env
export ORACLE_JOBS=28
FILES="client thread module static version artifact coder random memory fourier magic list locale channel paint geometry identify effect draw"
RX="MagickCore/($(echo $FILES | tr ' ' '|'))\\.c\$"
echo "== mull build $(date): $RX"
tools/oracle/build.sh mull "$RX" erdc1 2>&1 | tail -3
BIN=build-oracle/mull-erdc1/utilities/magick
for f in $FILES; do
  python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin $BIN --name full-$f > build-oracle/full-$f.log 2>&1
  python3 -c "
import json; r = json.load(open('build-oracle/work/mutation-full-$f.json'))
open('build-oracle/work/capped-$f.ids', 'w').write(''.join(x['id'] + '\n' for x in r if x['status'] == 'survived' and x.get('capped')))"
  if [ -s build-oracle/work/capped-$f.ids ]; then
    python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin $BIN --name cap1500-$f \
      --ids build-oracle/work/capped-$f.ids --max-cases 1500 > build-oracle/cap1500-$f.log 2>&1
  fi
  echo "$(date +%H:%M) $f: $(grep -E 'killed [0-9]' build-oracle/full-$f.log) | cap1500: $(grep -E 'killed [0-9]' build-oracle/cap1500-$f.log 2>/dev/null)"
done
echo "== done $(date)"
