#!/usr/bin/env python3
"""Does a command reach these functions? Check a route before writing a case.

Runs one command on the coverage build (oracle.build("cov")), in a scratch
case directory under the oracle's environment, and reports which of the named
functions it executed:

  python3 tools/oracle/reach.py PruneLevel,IntensityCompare -- \\
      {C}/rose.miff -colorspace gray -colors 8 null:

{C} is the corpus. Files the command needs in its directory (a policy.xml of
its own, an MVG file) go in REACH_FILES, as name=text pairs separated by ';',
with \\n for a newline.
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oracle  # noqa: E402


def main():
    if "--" not in sys.argv or len(sys.argv) < 4:
        sys.exit(__doc__)
    functions = sys.argv[1].split(",")
    argv = [a.replace("{C}", oracle.CORPUS) for a in sys.argv[sys.argv.index("--") + 1:]]
    cov = oracle.build("cov")
    case_dir = tempfile.mkdtemp(prefix="reach-")
    try:
        for spec in filter(None, os.environ.get("REACH_FILES", "").split(";")):
            name, text = spec.split("=", 1)
            path = os.path.join(case_dir, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(text.replace("\\n", "\n"))
        env = oracle.env_for(cov, case_dir,
                             {"LLVM_PROFILE_FILE": os.path.join(case_dir, "%p.profraw")})
        r = subprocess.run([cov] + argv, cwd=case_dir, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=oracle.TIMEOUT)
        print("exit %d%s" % (r.returncode, ("; " + r.stderr.decode()[:200].strip())
                             if r.stderr else ""))
        merged = os.path.join(case_dir, "merged.profdata")
        profdata = oracle.llvm_tool("llvm-profdata")
        subprocess.run([profdata, "merge", "-sparse", "-o", merged]
                       + glob.glob(os.path.join(case_dir, "*.profraw")), check=True)
        covered = set(subprocess.run([profdata, "show", "--covered", "--all-functions", merged],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     check=True).stdout.decode().split())
        for name in functions:
            hit = any(c == name or c.endswith(":" + name) for c in covered)
            print("  %-36s %s" % (name, "reached" if hit else "not reached"))
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
