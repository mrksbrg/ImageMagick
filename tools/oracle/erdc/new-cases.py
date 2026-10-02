#!/usr/bin/env python3
"""new-cases.py BINARY COMMIT: a --cases regex for the cases added since COMMIT.

Generates the catalogue from cases.py as it stands and as it stood at COMMIT,
with the same lists from BINARY, and prints a regex matching the ids that are
new. For rerunning a full run's survivors against only the cases its catalogue
lacked."""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import oracle  # noqa: E402


def old_catalogue(commit, lists, writable):
    source = subprocess.run(["git", "show", "%s:tools/oracle/cases.py" % commit],
                            check=True, capture_output=True, text=True).stdout
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(source)
    spec = importlib.util.spec_from_file_location("cases_then", f.name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    os.unlink(f.name)
    return module.generate(lists, writable)


def main():
    binary, commit = os.path.abspath(sys.argv[1]), sys.argv[2]
    manifest, now = oracle.load_cases(binary)
    lists, writable = oracle.build_lists(binary)
    lists["__decode_files__"] = manifest["decode_files"]
    then = {c["id"] for c in old_catalogue(commit, lists, writable)}
    new = sorted(c["id"] for c in now if c["id"] not in then)
    print("^(" + "|".join(re.escape(i) for i in new) + ")$")
    print("%d new cases since %s" % (len(new), commit), file=sys.stderr)


if __name__ == "__main__":
    main()
