#!/usr/bin/env python3
"""The readiness gate: may a function be refactored under the oracle?

    tools/oracle/gate.py REPORT [REPORT ...]            one table per source file
    tools/oracle/gate.py REPORT ... --file colorspace.c
    tools/oracle/gate.py REPORT ... --json gated.json   every result with its kind

Reports are mutate.py's mutation-*.json, merged in the order given: a later
report replaces the earlier result of the same mutant, so pass the full run
first and its reruns after it (uncapped, or against new cases only).

Each survivor is sorted by classify.py. The gate is, per function,

    killed / (killed + unmatched + unreached)

Survivors of the unobservable kinds (logging, progress, loop and channel
bounds, free guards, allocation sizes, threads and resources) are left out:
no output-comparing test can kill them. Survivors on lines no case executes
count against the function, since a refactoring there is unprotected. See
docs/refactoring/VERIFICATION.md for the thresholds:

    ready       90% or more
    careful     75-90%: extra review, or add a case first
    not ready   below 75%
"""

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classify  # noqa: E402

UNOBSERVABLE = {"logging", "progress", "free-guard", "channel-bound", "loop-bound",
                "memory-size", "threads-resources"}
READY, CAREFUL = 0.90, 0.75
COLUMNS = ("mutants", "killed", "unobservable", "unmatched", "unreached")
ROW = "  %-28s %7s %6s %12s %9s %9s %6s  %s"


def merged(reports):
    """The results of all reports, a later report winning for the same mutant."""
    by_id = {}
    for path in reports:
        with open(path) as f:
            for result in json.load(f):
                by_id[result["id"]] = result
    return list(by_id.values())


def function_name(result):
    return re.split(r"[;:]", result["function"] or "?")[-1]


def tally(results):
    """Counts per column for a group of classified results."""
    kinds = collections.Counter(r["kind"] for r in results)
    return {"mutants": len(results), "killed": kinds["killed"],
            "unobservable": sum(kinds[k] for k in UNOBSERVABLE),
            "unmatched": kinds["unmatched"], "unreached": kinds["unreached"]}


def gate_value(counts):
    """The gate as a fraction, or None when no mutant counts towards it."""
    denominator = counts["killed"] + counts["unmatched"] + counts["unreached"]
    return counts["killed"] / denominator if denominator else None


def verdict(value):
    if value is None:
        return "no cases"
    if value >= READY:
        return "ready"
    return "careful" if value >= CAREFUL else "not ready"


def print_row(name, counts, show_verdict=True):
    value = gate_value(counts)
    shown = "-" if value is None else "%.0f%%" % (100 * value)
    print(ROW % ((name[:28],) + tuple(counts[c] for c in COLUMNS)
                 + (shown, verdict(value) if show_verdict else "")))


def print_file(path, results):
    print("\n== %s: %d mutants" % (os.path.basename(path), len(results)))
    print(ROW % (("function",) + COLUMNS + ("gate", "verdict")))
    groups = collections.defaultdict(list)
    for r in results:
        groups[function_name(r)].append(r)
    for name, group in sorted(groups.items(), key=lambda item: -len(item[1])):
        print_row(name, tally(group))
    print_row("ALL", tally(results), show_verdict=False)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("reports", nargs="+", help="mutation-*.json reports, full run first")
    p.add_argument("--file", help="only mutants in this source file (basename)")
    p.add_argument("--json", help="write every merged result with its kind to this file")
    args = p.parse_args()

    results = merged(args.reports)
    if args.file:
        results = [r for r in results if os.path.basename(r["file"]) == args.file]
    classify.classify(results)
    by_file = collections.defaultdict(list)
    for r in results:
        by_file[r["file"]].append(r)
    for path in sorted(by_file):
        print_file(path, by_file[path])
    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
