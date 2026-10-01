#!/bin/bash
# confirm.sh BUILD:FILE...: pull the new cases, rebuild the indexes, rerun each file's
# survivors (not killed in its full, cap1500 or uncap run) against the gaps family.
cd ~/imagemagick-mutation/ImageMagick && . ~/imagemagick-mutation/setup/sysroot.env
export ORACLE_JOBS=28
W=build-oracle/work
git pull -q && git log --oneline -1
python3 -u tools/oracle/casemap.py > build-oracle/casemap-confirm.log 2>&1 && \
  python3 -u tools/oracle/linecov.py > build-oracle/linecov-confirm.log 2>&1 || { echo "indexes failed"; exit 1; }
echo "indexes rebuilt $(date +%H:%M)"
for fb in "$@"; do
  b=${fb%%:*}; f=${fb##*:}; n=$(ls $W/mutation-conf*-$f.json 2>/dev/null | wc -l); name=conf$((n+1))-$f
  python3 - "$f" "$name" <<'PY'
import json, sys
f, name = sys.argv[1:]; W = "build-oracle/work"; killed, ids = set(), set()
import glob
for p in glob.glob(W + "/mutation-*-%s.json" % f):
    for r in json.load(open(p)):
        ids.add(r["id"]); killed |= {r["id"]} if r["status"] == "killed" else set()
open(W + "/%s.ids" % name, "w").write("".join(i + "\n" for i in sorted(ids - killed)))
PY
  python3 -u tools/oracle/mutate.py --file "MagickCore/$f\\.c\$" --bin build-oracle/mull-$b/utilities/magick \
    --name $name --ids $W/$name.ids --cases '^gaps/' > build-oracle/$name.log 2>&1
  echo "$(date +%H:%M) $name: $(grep -E 'killed [0-9]' build-oracle/$name.log)"
done
echo "== done confirm $(date)"
