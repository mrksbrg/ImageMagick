#!/bin/bash
cd ~/imagemagick-mutation/ImageMagick && . ~/sysroot.env
export ORACLE_JOBS=28
echo "== selfcheck $(date)";  python3 -u tools/oracle/oracle.py selfcheck --repeat 4 2>&1 | tail -15
echo "== casemap $(date)";    python3 -u tools/oracle/casemap.py 2>&1 | tail -5
echo "== linecov $(date)";    python3 -u tools/oracle/linecov.py 2>&1 | tail -5
echo "== done $(date)"
