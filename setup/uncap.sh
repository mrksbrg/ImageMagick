#!/bin/bash
# Rerun every survivor still capped after cap1500 against all the cases that reach it.
cd ~/imagemagick-mutation/ImageMagick && . ~/imagemagick-mutation/setup/sysroot.env
export ORACLE_JOBS=28
W=build-oracle/work
for fb in image:erdc2 policy:erdc2 geometry:erdc1 log:erdc2 memory:erdc1 magic:erdc1 locale:erdc1 random:erdc1; do
  f=${fb%%:*}; b=${fb##*:}
  python3 -c "
import json; r = json.load(open('$W/mutation-cap1500-$f.json'))
open('$W/uncap-$f.ids', 'w').write(''.join(x['id'] + '\n' for x in r if x['status'] == 'survived' and x.get('capped')))"
  [ -s $W/uncap-$f.ids ] && [ ! -f $W/mutation-uncap-$f.json ] && python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" \
      --bin build-oracle/mull-$b/utilities/magick --name uncap-$f --ids $W/uncap-$f.ids --max-cases 0 > build-oracle/uncap-$f.log 2>&1
  echo "$(date +%H:%M) $f uncapped: $(grep -E 'killed [0-9]' build-oracle/uncap-$f.log)"
done
echo "== done uncap $(date)"
