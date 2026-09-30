#!/usr/bin/env python3
"""Cases that fail on the base build, grouped by why.

    tools/oracle/deadcases.py [--filter RE]

A case that fails the same way on both sides passes the oracle while testing
nothing but an error message: `magick ... -stereo` (the option exists only in
the composite utility), `magick -perceptible` (missing from the option table),
`-fx` expressions that need a second image. Some failures are the point of a
case (an invalid argument, an error path); this lists them all, grouped by the
first line of the error, so a person can tell which are which. Runs the
catalogue once on the base build, about two minutes.
"""

import argparse
import collections
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oracle  # noqa: E402

# The part of an error that names its kind; the rest (file names, positions)
# differs from case to case.
ERROR = re.compile(r"(?m)^\S*: (.*?)(?: `| '| @|$)")


def failing(cases, manifest, binary):
    """{case id: result} for the cases whose steps do not all exit 0."""
    results = oracle.parallel(lambda c: oracle.run_case(binary, "dead", c, manifest),
                              cases, os.cpu_count(), "dead")
    shutil.rmtree(os.path.join(oracle.WORK, "runs", "dead"), ignore_errors=True)
    return {i: r for i, r in results.items() if any(rc != 0 for rc in r["rc"])}


def reason(result):
    text = result.get("err_text") or ""
    m = ERROR.search(text if isinstance(text, str) else str(text))
    return m.group(1)[:70] if m else "exit %s, no error message" % result["rc"]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--filter", help="only cases whose id matches this regex")
    args = p.parse_args()
    binary = oracle.build("base", "origin/main")
    manifest, cases = oracle.load_cases(binary)
    if args.filter:
        cases = [c for c in cases if re.search(args.filter, c["id"])]
    by_id = {c["id"]: c for c in cases}
    groups = collections.defaultdict(list)
    for i, r in failing(cases, manifest, binary).items():
        groups[reason(r)].append(by_id[i]["label"])
    print("%d of %d cases fail on the base build" % (sum(map(len, groups.values())), len(cases)))
    for why, labels in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print("%5d  %s\n       e.g. %s" % (len(labels), why, labels[0][:70]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
