#!/usr/bin/env python3
"""Which source lines the oracle executes: build-oracle/oracle.lcov.

    tools/oracle/linecov.py

Runs the whole catalogue once with the coverage build (tools/oracle/build.sh
cov), merges the profiles and exports them as lcov. mutate.py and classify.py
read the result to tell a survivor on a line no case executes ("unreached":
the catalogue needs a new input) from one on an executed line (a sharper case
or an equivalent mutant). Rerun it after changing the catalogue, before a
mutation run whose survivors will be read; casemap.py answers the
function-level question and has to be rerun as well.
"""

import glob
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oracle  # noqa: E402

PROF = os.path.join(oracle.OUT, "prof" + oracle.WIDE)
PROFDATA = os.path.join(oracle.OUT, "oracle%s.profdata" % oracle.WIDE)
LCOV = os.path.join(oracle.OUT, "oracle%s.lcov" % oracle.WIDE)


def main():
    cov_bin = oracle.build("cov")
    shutil.rmtree(PROF, ignore_errors=True)
    os.makedirs(PROF)
    start = time.time()
    # %8m: a pool of eight profiles merged as the processes exit, instead of
    # one file for each of the catalogue's ~10,000 magick runs.
    env = dict(os.environ, LLVM_PROFILE_FILE=os.path.join(PROF, "oracle-%8m.profraw"))
    subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "oracle.py"),
                    "exec", "--bin", cov_bin], env=env, check=True)
    subprocess.run([oracle.llvm_tool("llvm-profdata"), "merge", "-sparse", "-o", PROFDATA]
                   + sorted(glob.glob(os.path.join(PROF, "*.profraw"))), check=True)
    with open(LCOV + ".tmp", "w") as f:
        subprocess.run([oracle.llvm_tool("llvm-cov"), "export", "-format=lcov",
                        "-instr-profile", PROFDATA, cov_bin], stdout=f, check=True)
    os.replace(LCOV + ".tmp", LCOV)
    print("linecov: %s in %.0fs" % (os.path.relpath(LCOV, oracle.ROOT), time.time() - start))
    return 0


if __name__ == "__main__":
    sys.exit(main())
