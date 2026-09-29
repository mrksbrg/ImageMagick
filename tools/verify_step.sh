#!/bin/bash
# The per-commit verification sequence from AGENTS.md, in one call.
#
#   tools/verify_step.sh MagickCore/resize.c ScaleImage [OtherFunction ...]
#
# 1. builds the candidate, 2. runs the literal and call guards, 3. runs the
# oracle on every case that executes the named functions, 4. prints the
# file's Code Health and the named functions' findings. Exits non-zero if
# the build, a guard or the oracle fails; the Code Health judgement (rule 2
# of the playbook) stays with whoever reads the output.
#
# New helpers are not in the case map, so name them in SHOW to see their
# findings without handing them to the oracle:
#   SHOW="ScaleScanlineX" tools/verify_step.sh MagickCore/resize.c ScaleImage
set -uo pipefail
cd "$(dirname "$0")/.."
file=${1:?usage: verify_step.sh <file> <Function> [Function ...]}
shift
[ $# -ge 1 ] || { echo "name the function(s) you refactored" >&2; exit 2; }

fail=0
if ! tools/oracle/build.sh cand > /dev/null; then
  echo "BUILD FAILED"; exit 1
fi
warn=$(grep -E "$(basename "$file")[^ ]*: (warning|error)" build-oracle/cand/make.log | head -5)
echo "build:  ok${warn:+ (warnings below)}"
[ -n "$warn" ] && echo "$warn"

g=$(python3 tools/refactor_guard.py "$file" 2>&1); gs=$?
c=$(python3 tools/refactor_guard.py --calls "$file" 2>&1); cs=$?
echo "guard:  $(echo "$g" | grep -E '^(OK|WARN|FAIL)' | head -1 | cut -c1-70)"
echo "calls:  $(echo "$c" | grep -E '^(OK|WARN|FAIL)' | head -1 | cut -c1-70)"
[ $gs -ne 0 ] && { echo "$g" | tail -8; fail=1; }
[ $cs -ne 0 ] && { echo "$c" | tail -8; fail=1; }

args=()
for f in "$@"; do args+=(--function "$f"); done
o=$(python3 tools/oracle/oracle.py run "${args[@]}" 2>&1); os=$?
echo "oracle: $(echo "$o" | grep -E '^oracle: [0-9]+ cases' | sed 's/^oracle: //')"
[ $os -ne 0 ] && { echo "$o" | grep -E 'DIVERGED|no case|^    ' | head -12; fail=1; }

python3 tools/ch.py --json "$file" | python3 -c "
import json, sys
names = set(sys.argv[1:])
data = json.load(sys.stdin)
d = next(iter(data.values()))
print('health: %s' % d['score'])
for c in d['review']:
    for f in c.get('functions') or []:
        base = f['title'].split(':')[0]
        if base in names:
            print('        %-28s %-30s %s' % (base, c['category'], f.get('details') or ''))
" "$@" ${SHOW:-}
exit $fail
