#!/usr/bin/env python3
"""Which oracle cases execute which functions.

    tools/oracle/casemap.py            build build-oracle/work/casemap.json
    tools/oracle/casemap.py FUNCTION   list the cases that execute FUNCTION

Runs every case once with the coverage build (tools/oracle/build.sh cov), keeps
a profile per case, and records the functions each case executed. The map is
what lets tools/oracle/mutate.py test a mutant only on the cases that can
reach it, and what answers "does the oracle reach this function at all?"
before a function is refactored.

Function names are as LLVM records them: `name` for external functions,
`file.c;name` (or `path/file.c:name`) for static ones.
"""

import concurrent.futures
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oracle  # noqa: E402

MAP = os.path.join(oracle.WORK, "casemap.json")
PROFDATA = oracle.llvm_tool("llvm-profdata")
RAW = os.path.join(oracle.WORK, "casemap-raw")


def catalogue_digest(cases):
    return hashlib.sha1(json.dumps([c["id"] for c in cases]).encode()).hexdigest()


def functions_of(case_id):
    d = os.path.join(RAW, case_id.replace("/", "_"))
    raws = sorted(glob.glob(os.path.join(d, "*.profraw")))
    if not raws:
        return []
    merged = os.path.join(d, "merged.profdata")
    r = subprocess.run([PROFDATA, "merge", "-sparse", "-o", merged] + raws,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:  # e.g. a process killed mid-write; the case maps to nothing
        sys.stderr.write("casemap: no profile for %s: %s\n" % (case_id, r.stderr.decode()[:200]))
        return None
    out = subprocess.run([PROFDATA, "show", "--covered", "--all-functions", merged],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         check=True).stdout.decode()
    shutil.rmtree(d, ignore_errors=True)
    # With --covered, show prints one executed function name per line.
    return [line.strip() for line in out.splitlines() if line.strip()]


def build_map():
    cov_bin = oracle.build("cov")
    base_bin = oracle.build("base", "origin/main")
    manifest, cases = oracle.load_cases(base_bin)
    shutil.rmtree(RAW, ignore_errors=True)
    start = time.time()

    def one(case):
        d = os.path.join(RAW, case["id"].replace("/", "_"))
        os.makedirs(d, exist_ok=True)
        oracle.run_case(cov_bin, "casemap", case, manifest,
                        {"LLVM_PROFILE_FILE": os.path.join(d, "%p.profraw")})
        shutil.rmtree(oracle.case_dir("casemap", case), ignore_errors=True)
        return functions_of(case["id"])

    per_case = oracle.parallel(one, cases, os.cpu_count(), "casemap")
    by_function, unmapped = {}, sorted(c for c, n in per_case.items() if n is None)
    for cid, names in per_case.items():
        for n in names or []:
            by_function.setdefault(n, []).append(cid)
    for v in by_function.values():
        v.sort()
    with open(MAP, "w") as f:
        json.dump({"catalogue": catalogue_digest(cases), "cov_binary": oracle.file_sha(cov_bin),
                   "functions": by_function, "unmapped": unmapped}, f)
    print("casemap: %d cases, %d functions reached, %d cases without a profile, %.0fs"
          % (len(cases), len(by_function), len(unmapped), time.time() - start))


def load_map(cases=None):
    with open(MAP) as f:
        m = json.load(f)
    if cases is not None and m["catalogue"] != catalogue_digest(cases):
        sys.exit("casemap.json is stale: the catalogue changed; rerun tools/oracle/casemap.py")
    return m["functions"]


def cases_for(function, fmap):
    """Cases executing `function`, matching static-function spellings too."""
    hits = set(fmap.get(function, []))
    for name, ids in fmap.items():
        if name.endswith(";" + function) or name.endswith(":" + function):
            hits.update(ids)
    return sorted(hits)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        build_map()
    else:
        ids = cases_for(sys.argv[1], load_map())
        print("%d cases execute %s" % (len(ids), sys.argv[1]))
        for i in ids[:40]:
            print("  " + i)
