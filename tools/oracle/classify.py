#!/usr/bin/env python3
"""Sort surviving mutants into the kinds that recur in every file.

    tools/oracle/classify.py build-oracle/work/mutation-sweep25-final.json [...]
    tools/oracle/classify.py REPORT --kind unmatched     list one kind with source
    tools/oracle/classify.py REPORT --file fx.c          one file only

Reading survivors by hand showed the same few kinds in every MagickCore file:
logging and progress checks, NULL guards before a free, loop bounds that run
one element past the end, and sizes passed to memory allocation or copying.
These rules name them, so a person reads only the rest ("unmatched") and the
real gaps in the catalogue stand out.

The rules match the mutated source line and the mutator. They say what a
survivor most likely is, not what it is: a rule can be fooled, so a survivor
that decides whether a function is safe to refactor still deserves a look.

Survivors are also split by where they sit: "unreached" means no case executes
the line, so the catalogue needs a new input, not a sharper one; "capped" means
not every case reaching the function was tried (see mutate.py --max-cases).
"""

import argparse
import collections
import json
import os
import re
import sys

# (kind, mutators it applies to or None for any, regex on the source line,
#  explanation). First match wins, so the most specific rules come first.
RULES = [
    ("logging", None,
     r"IsEventLogging\(\)|->debug\s*!=|LogMagickEvent",
     "only changes -debug output, which the oracle does not compare"),
    ("progress", None,
     r"progress_monitor|SetImageProgress|proceed\s*==",
     "only changes -monitor progress callbacks"),
    # Only when one of the next two lines frees or destroys: a NULL test
    # elsewhere is ordinary logic. `return(DestroyX(...))` after the test is
    # an error exit, and flipping it returns failure on the normal path.
    ("free-guard", {"cxx_ne_to_eq", "cxx_eq_to_ne"},
     r"[!=]=\s*\([\w\s]+\*+\)\s*NULL\)\s*\n(?!\s*return).*(Destroy|Relinquish|Free|free\()",
     "a NULL test before a free; flipping it leaks or frees nothing, which the output never shows"),
    ("channel-bound", {"cxx_lt_to_le", "cxx_le_to_lt", "cxx_lt_to_ge"},
     r"<=?\s*\(ssize_t\)\s*GetPixelChannels|<=?\s*MaxPixelChannels|number_channels",
     "a per-channel loop runs once more or not at all over a buffer padded past the last channel"),
    ("loop-bound", {"cxx_lt_to_le", "cxx_le_to_lt", "cxx_gt_to_ge", "cxx_ge_to_gt"},
     r"^\s*(for|while)\s*\(|}\s*while\s*\(",
     "the loop runs one extra or one fewer iteration, usually over scratch space; ASan might see some"),
    ("memory-size", {"cxx_mul_to_div", "cxx_add_to_sub", "cxx_sub_to_add", "cxx_div_to_mul"},
     r"memset|memcpy|memmove|Acquire\w*Memory|Acquire\w*Quantum|Resize\w*Memory|sizeof",
     "changes an allocation or copy size; unobservable while the buffer stays big enough"),
    ("threads-resources", None,
     r"Semaphore|OpenMP|number_threads|ThreadResource|GetMagickResource|cycles|throttle",
     "threading and resource limits; the oracle runs single-threaded and within limits"),
]
COMPILED = [(k, m, re.compile(rx), why) for k, m, rx, why in RULES]


def kind_of(result, line, after=""):
    if result["status"] != "survived":
        return result["status"]
    if not result.get("line_executed", True):
        return "unreached"
    for kind, mutators, rx, _ in COMPILED:
        text = line + "\n" + after if kind == "free-guard" else line
        if (mutators is None or result["mutator"] in mutators) and rx.search(text):
            return kind
    return "unmatched"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("reports", nargs="+", help="mutation-*.json reports")
    p.add_argument("--kind", help="list the survivors of this kind with their source line")
    p.add_argument("--file", help="only mutants in this source file (basename)")
    p.add_argument("--json", help="write every result with its kind to this file")
    args = p.parse_args()

    results, sources = [], {}
    for path in args.reports:
        with open(path) as f:
            results.extend(json.load(f))
    if args.file:
        results = [r for r in results if os.path.basename(r["file"]) == args.file]
    for r in results:
        if r["file"] not in sources:
            with open(r["file"], errors="replace") as f:
                sources[r["file"]] = f.read().split("\n")  # not splitlines(): form feeds
        r["src"] = sources[r["file"]][r["line"] - 1].strip()
        after = " ".join(sources[r["file"]][r["line"]:r["line"] + 2])
        r["kind"] = kind_of(r, r["src"], after)

    if args.kind:
        for r in (r for r in results if r["kind"] == args.kind):
            fn = re.split(r"[;:]", r["function"] or "?")[-1]
            print("%s %s:%d %-15s %-24s %s" % ("c" if r.get("capped") else " ",
                                               os.path.basename(r["file"]), r["line"],
                                               r["mutator"][4:], fn[:24], r["src"][:90]))
        return 0

    survivors = [r for r in results if r["status"] == "survived"]
    counts = collections.Counter(r["kind"] for r in survivors)
    why = {k: w for k, _, _, w in RULES}
    why["unreached"] = "no case executes the line: needs a new input"
    why["unmatched"] = "read these: equivalent, or a gap in the catalogue"
    print("%d mutants, %d survivors\n" % (len(results), len(survivors)))
    print("  %-18s %6s %7s  %s" % ("kind", "count", "capped", ""))
    order = ["unreached"] + [k for k, _, _, _ in RULES] + ["unmatched"]
    for k in order:
        if counts[k]:
            capped = sum(1 for r in survivors if r["kind"] == k and r.get("capped"))
            print("  %-18s %6d %7d  %s" % (k, counts[k], capped, why[k]))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
