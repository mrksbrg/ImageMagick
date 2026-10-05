#!/usr/bin/env python3
"""The readiness gate: may a function be refactored under the oracle?

    tools/oracle/gate.py REPORT [REPORT ...]            one table per source file
    tools/oracle/gate.py REPORT ... --file colorspace.c
    tools/oracle/gate.py REPORT ... --json gated.json   every result with its kind

Reports are mutate.py's mutation-*.json, merged in the order given: a later
report replaces the earlier result of the same mutant, so pass the full run
first and its reruns after it (uncapped, or against new cases only). A kill
stands, though: a rerun limited with --cases runs a few cases, and its
"survived" says only that those did not kill the mutant. Kills that only one platform makes
(tools/oracle/platform-kills/) are applied last; see platform_kills().

Each survivor is sorted by classify.py. Three figures are printed for every
function and file:

    plain      killed / mutants: the ordinary mutation score
    reach      the share of mutants in functions some case executes
    adjusted   killed / (killed + unmatched + unreached + no coverage):
               the plain score without the survivors no test can kill

The adjusted score is the headline figure: a function no case executes is a
gap like any other, since refactoring it is unprotected. Within one function
it equals the gate, killed / (killed + unmatched + unreached), which decides
the verdict; over a file the gate (gate_value) leaves out the functions no
case reaches, the adjusted score does not.

Survivors of the unobservable kinds (logging, progress, loop and channel
bounds, strict tests against MagickEpsilon, free guards, allocation sizes,
threads and resources) are left out:
no output-comparing test can kill them. So are those read by hand and found
equivalent or unobservable (tools/oracle/verdicts.json); those read and found
to be gaps, or left unresolved, count as unmatched. Survivors on lines no case executes
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

UNOBSERVABLE = {"logging", "progress", "free-guard", "channel-bound", "epsilon-bound",
                "loop-bound", "memory-size", "threads-resources",
                "equivalent", "unobservable"}  # the last two: hand verdicts
OPEN = ("unmatched", "gap", "unresolved")  # a gap is open until its case is in
READY, CAREFUL = 0.90, 0.75
COLUMNS = ("mutants", "killed", "unobservable", "unmatched", "unreached", "no-coverage")
ROW = "  %-28s %7s %6s %12s %9s %9s %11s %6s %6s %8s  %s"


# Cases found nondeterministic after they were credited with kills: those kills do not count.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "unstable-killers.json")) as _f:
    UNSTABLE_KILLERS = {k for k in json.load(_f) if not k.startswith("_")}


def honest(result):
    """The result, a kill by an unstable case read as a survivor."""
    if result["status"] == "killed" and result.get("killer") in UNSTABLE_KILLERS:
        return dict(result, status="survived", killer=None)
    return result


def replaces(result, earlier):
    """Whether a later report's result takes the place of the earlier one.

    Not over a kill, and not with "no-coverage": a rerun limited with --cases
    reports "survived" when its few cases miss the mutant and "no-coverage"
    when they do not reach it, which says nothing about the cases it did not
    run. The catalogue only grows, so a kill stands."""
    if earlier is None:
        return True
    return earlier["status"] != "killed" and result["status"] != "no-coverage"


# Kills only one platform makes (tools/oracle/platform-kills/*.json): a mutant whose effect shows
# under one C library only, e.g. a qsort comparator's tie order (BSD qsort reorders ties, glibc
# may not). Owner's decision, 2026-10-05: such a kill counts, and a function trusted through
# one must have its refactoring checked on that platform. Each entry is a mutate.py result with
# a "platform" field; it is matched by mutator and source position, not by the machine's path.
PLATFORM_KILLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "platform-kills")


def position_key(result_id):
    """mutator:MagickCore/file.c:line:col:line:col, without the checkout's path."""
    mutator, _, rest = result_id.partition(":")
    return mutator + ":" + rest[rest.rfind("MagickCore/"):] if "MagickCore/" in rest else result_id


def platform_kills():
    kills = {}
    if os.path.isdir(PLATFORM_KILLS):
        for name in sorted(os.listdir(PLATFORM_KILLS)):
            if name.endswith(".json"):
                with open(os.path.join(PLATFORM_KILLS, name)) as f:
                    for result in json.load(f):
                        if result.get("status") == "killed":
                            kills[position_key(result["id"])] = result
    return kills


def merged(reports):
    """The results of all reports, a later report winning for the same mutant (see replaces),
    then the platform kills applied to the mutants among them."""
    by_id = {}
    for path in reports:
        with open(path) as f:
            for result in map(honest, json.load(f)):
                if replaces(result, by_id.get(result["id"])):
                    by_id[result["id"]] = result
    kills = platform_kills()
    for result_id, result in by_id.items():
        kill = kills.get(position_key(result_id))
        if kill is not None and result["status"] != "killed":
            by_id[result_id] = dict(result, status="killed", killer=kill.get("killer"),
                                    platform=kill.get("platform"))
    return list(by_id.values())


def function_name(result):
    return re.split(r"[;:]", result["function"] or "?")[-1]


def tally(results):
    """Counts per column for a group of classified results."""
    kinds = collections.Counter(r["kind"] for r in results)
    return {"mutants": len(results), "killed": kinds["killed"],
            "unobservable": sum(kinds[k] for k in UNOBSERVABLE),
            "unmatched": sum(kinds[k] for k in OPEN), "unreached": kinds["unreached"],
            "no-coverage": kinds["no-coverage"]}


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def gate_value(counts):
    """The gate as a fraction, or None when no mutant counts towards it."""
    return ratio(counts["killed"], counts["killed"] + counts["unmatched"] + counts["unreached"])


def plain_score(counts):
    return ratio(counts["killed"], counts["mutants"])


def reach(counts):
    return ratio(counts["mutants"] - counts["no-coverage"], counts["mutants"])


def adjusted_score(counts):
    """The gate with the mutants no case reaches counted as gaps."""
    return ratio(counts["killed"], counts["killed"] + counts["unmatched"]
                 + counts["unreached"] + counts["no-coverage"])


def percent(value):
    return "-" if value is None else "%.0f%%" % (100 * value)


def verdict(value):
    if value is None:
        return "no cases"
    if value >= READY:
        return "ready"
    return "careful" if value >= CAREFUL else "not ready"


def print_row(name, counts, show_verdict=True):
    figures = (plain_score(counts), reach(counts), adjusted_score(counts))
    print(ROW % ((name[:28],) + tuple(counts[c] for c in COLUMNS)
                 + tuple(percent(f) for f in figures)
                 + (verdict(gate_value(counts)) if show_verdict else "",)))


def print_file(path, results):
    print("\n== %s: %d mutants" % (os.path.basename(path), len(results)))
    print(ROW % (("function",) + COLUMNS + ("plain", "reach", "adjusted", "verdict")))
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
